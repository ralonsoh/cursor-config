#!/usr/bin/env python3
"""Incrementally sync JIRA issues into a local AnythingLLM instance.

For each configured project the script:
  1. Queries AnythingLLM for already-stored ticket keys.
  2. Lists all issue keys in the Jira project.
  3. Fetches only the missing tickets (metadata + comments) → markdown.
  4. Uploads to AnythingLLM and embeds into the target workspace.

Progress is persisted so the script can be stopped and resumed safely.

Usage:
    ./jira_to_anythingllm.py
    ./jira_to_anythingllm.py --dry-run
    ./jira_to_anythingllm.py --project MYPROJECT --limit 10
    ./jira_to_anythingllm.py --jira-url URL --jira-username U --jira-token T \\
        --allm-url URL --allm-key K --workspace ws1
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults (overridable via CLI / env / mcp.json)
# ---------------------------------------------------------------------------
DEFAULT_PROJECTS: tuple[str, ...] = ()
DEFAULT_JIRA_URL = ''
DEFAULT_ALLM_URL = ''
DEFAULT_WORKSPACE = ''

BASE_DIR = Path('/tmp/jira-to-anythingllm')
ISSUES_DIR = BASE_DIR / 'tickets'
LOG_DIR = BASE_DIR / 'logs'
PROGRESS_FILE = LOG_DIR / 'progress.json'
LOG_FILE = LOG_DIR / 'sync.log'
MCP_CONFIG = Path.home() / '.cursor' / 'mcp.json'

FOLDER = 'jira-bugs'
REQUEST_DELAY = 0.25
MAX_COMMENTS = 50
COMMENT_BODY_LIMIT = 8000
ISSUE_KEY_RE = re.compile(r'^([A-Z]+-\d+)\.md$')

ISSUE_FIELDS = (
    'summary,status,description,comment,assignee,reporter,priority,issuetype,'
    'created,updated,labels,components,resolution'
)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open('a', encoding='utf-8') as fh:
        fh.write(line + '\n')


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------
def _mcp_env(server: str) -> dict:
    if not MCP_CONFIG.exists():
        return {}
    config = json.loads(MCP_CONFIG.read_text(encoding='utf-8'))
    return config.get('mcpServers', {}).get(server, {}).get('env', {})


def _resolve(cli_val: str | None, env_key: str, mcp_server: str,
             mcp_key: str, default: str = '') -> str:
    if cli_val:
        return cli_val.strip()
    val = os.environ.get(env_key, '').strip()
    if val:
        return val
    return _mcp_env(mcp_server).get(mcp_key, default).strip()


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------
def load_progress() -> dict:
    progress: dict = {
        'completed': {},
        'failed': {},
        'projects': {},
        'started_at': datetime.now(timezone.utc).isoformat(),
    }
    if PROGRESS_FILE.exists():
        data = json.loads(PROGRESS_FILE.read_text(encoding='utf-8'))
        progress['completed'] = data.get('completed', {})
        progress['failed'] = data.get('failed', {})
        progress['projects'] = data.get('projects', {})
        if data.get('started_at'):
            progress['started_at'] = data['started_at']
    return progress


def save_progress(progress: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    progress['updated_at'] = datetime.now(timezone.utc).isoformat()
    PROGRESS_FILE.write_text(
        json.dumps(progress, indent=2, sort_keys=True), encoding='utf-8',
    )


# ---------------------------------------------------------------------------
# Atlassian Document Format → plain text
# ---------------------------------------------------------------------------
def adf_to_text(node) -> str:
    if node is None:
        return ''
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ''
    node_type = node.get('type')
    if node_type == 'text':
        return node.get('text', '')
    if node_type == 'hardBreak':
        return '\n'
    parts = [adf_to_text(child) for child in node.get('content', [])]
    text = ''.join(parts)
    if node_type in ('paragraph', 'heading', 'listItem', 'blockquote'):
        return text + '\n'
    if node_type == 'bulletList':
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        return '\n'.join(f'- {l}' for l in lines) + '\n'
    if node_type == 'orderedList':
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        return '\n'.join(f'{i}. {l}' for i, l in enumerate(lines, 1)) + '\n'
    if node_type == 'codeBlock':
        return f'```\n{text}\n```\n'
    return text


def _user_name(user: dict | None) -> str:
    if not user:
        return 'Unassigned'
    return user.get('displayName') or user.get('name') or 'Unknown'


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def _http(method: str, url: str, headers: dict,
          data: bytes | None = None, timeout: int = 120) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


# ---------------------------------------------------------------------------
# Jira API
# ---------------------------------------------------------------------------
def jira_get(path: str, auth: str, base: str) -> dict:
    url = f'{base}/rest/api/3/{path.lstrip("/")}'
    headers = {
        'Accept': 'application/json',
        'Authorization': auth,
        'User-Agent': 'jira-to-anythingllm/1.0',
    }
    for attempt in range(6):
        status, body = _http('GET', url, headers, timeout=90)
        if status == 429:
            wait = attempt + 2
            log(f'Jira rate-limited, sleeping {wait}s')
            time.sleep(wait)
            continue
        payload = json.loads(body.decode('utf-8'))
        if status >= 400:
            msgs = '; '.join(payload.get('errorMessages', [body.decode()]))
            if status in (401, 403, 404):
                return {'error': True, 'status': status,
                        'errorMessages': payload.get('errorMessages', [msgs])}
            raise RuntimeError(msgs)
        return payload
    raise RuntimeError(f'Jira rate limit exceeded for {path}')


def list_project_keys(project: str, auth: str, base: str) -> list[str]:
    keys: list[str] = []
    params: dict[str, str] = {
        'jql': f'project = {project} ORDER BY key ASC',
        'maxResults': '5000', 'fields': 'key',
    }
    while True:
        qs = urllib.parse.urlencode(params)
        data = jira_get(f'search/jql?{qs}', auth, base)
        keys.extend(i['key'] for i in data.get('issues', []))
        if data.get('isLast', True):
            break
        params = {
            'jql': f'project = {project} ORDER BY key ASC',
            'maxResults': '5000', 'fields': 'key',
            'nextPageToken': data['nextPageToken'],
        }
    return keys


def _fetch_all_comments(key: str, auth: str, base: str) -> list[dict]:
    comments: list[dict] = []
    start = 0
    while True:
        path = f'issue/{urllib.parse.quote(key)}/comment?startAt={start}&maxResults=100'
        data = jira_get(path, auth, base)
        if data.get('error'):
            break
        batch = data.get('comments', [])
        comments.extend(batch)
        if start + len(batch) >= data.get('total', len(batch)):
            break
        start += len(batch)
    return comments


def fetch_issue_md(key: str, url: str, auth: str, base: str) -> str:
    data = jira_get(
        f'issue/{urllib.parse.quote(key)}?fields={urllib.parse.quote(ISSUE_FIELDS)}',
        auth, base,
    )
    if not data:
        raise RuntimeError('empty Jira response')
    if data.get('error'):
        msgs = '; '.join(data.get('errorMessages', ['access denied']))
        return f"Source URL: {url}\nIssue {key}: [NOT ACCESSIBLE]\n\n{msgs}\n"

    f = data.get('fields', {})
    components = ', '.join(c.get('name', '') for c in f.get('components') or [])
    labels = ', '.join(f.get('labels') or [])
    lines = [
        f"Source URL: {url}",
        f"Issue {key}: {f.get('summary', '')}",
        '',
        '## Metadata',
        f"- Type: {(f.get('issuetype') or {}).get('name', 'Unknown')}",
        f"- Status: {(f.get('status') or {}).get('name', 'Unknown')}",
        f"- Priority: {(f.get('priority') or {}).get('name', 'Unknown')}",
        f"- Resolution: {(f.get('resolution') or {}).get('name', 'Unresolved')}",
        f"- Reporter: {_user_name(f.get('reporter'))}",
        f"- Assignee: {_user_name(f.get('assignee'))}",
        f"- Components: {components or 'none'}",
        f"- Labels: {labels or 'none'}",
        f"- Created: {f.get('created')}",
        f"- Updated: {f.get('updated')}",
        '', '## Description', '',
        adf_to_text(f.get('description')).strip() or '(no description)',
    ]

    comments = f.get('comment', {}).get('comments', [])
    total = f.get('comment', {}).get('total', len(comments))
    if total > len(comments):
        comments = _fetch_all_comments(key, auth, base)
    if comments:
        selected = comments[-MAX_COMMENTS:]
        lines.extend(['', '## Comments'])
        if total > len(selected):
            lines.append(f'(showing last {len(selected)} of {total} comments)')
        for c in selected:
            author = (c.get('author') or {}).get('displayName', 'unknown')
            body = adf_to_text(c.get('body')).strip()
            if len(body) > COMMENT_BODY_LIMIT:
                body = body[:COMMENT_BODY_LIMIT] + '\n\n[truncated]'
            lines.extend(['', f"### Comment — {author} ({c.get('created', '')})",
                          '', body])
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------------------
# AnythingLLM API
# ---------------------------------------------------------------------------
def allm_get(path: str, base: str, key: str) -> dict:
    url = f'{base}/v1/{path.lstrip("/")}'
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {key}'}
    status, body = _http('GET', url, headers, timeout=60)
    payload = json.loads(body.decode('utf-8'))
    if status >= 400:
        raise RuntimeError(payload.get('error') or body.decode())
    return payload


def list_stored_keys(allm_base: str, allm_key: str) -> set[str]:
    stored: set[str] = set()
    payload = allm_get('documents', allm_base, allm_key)

    def walk(items: list) -> None:
        for item in items or []:
            if item.get('type') == 'file':
                for candidate in (Path(item.get('url', '')).name,
                                  item.get('name', ''), item.get('title', '')):
                    if not candidate:
                        continue
                    m = ISSUE_KEY_RE.match(candidate)
                    if m:
                        stored.add(m.group(1))
                        break
                    tm = re.search(r'JIRA ([A-Z]+-\d+)', candidate)
                    if tm:
                        stored.add(tm.group(1))
            elif item.get('items'):
                walk(item['items'])

    walk(payload.get('localFiles', {}).get('items', []))

    if ISSUES_DIR.exists():
        for p in ISSUES_DIR.glob('*.md'):
            m = ISSUE_KEY_RE.match(p.name)
            if m:
                stored.add(m.group(1))
    return stored


def _upload(file_path: Path, title: str, allm_base: str, allm_key: str) -> str:
    boundary = '----JiraToAnythingLLMBoundary'
    file_bytes = file_path.read_bytes()
    metadata = json.dumps({'title': title, 'fileName': file_path.name})
    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
        f'Content-Type: text/markdown\r\n\r\n'
    ).encode() + file_bytes + (
        f'\r\n--{boundary}\r\n'
        f'Content-Disposition: form-data; name="metadata"\r\n\r\n'
        f'{metadata}\r\n'
        f'--{boundary}--\r\n'
    ).encode()
    headers = {
        'Authorization': f'Bearer {allm_key}',
        'Content-Type': f'multipart/form-data; boundary={boundary}',
    }
    status, resp = _http('POST',
                         f'{allm_base}/v1/document/upload/{urllib.parse.quote(FOLDER)}',
                         headers, data=body, timeout=180)
    payload = json.loads(resp.decode())
    if status >= 400 or not payload.get('success') or not payload.get('documents'):
        raise RuntimeError(payload.get('error') or 'upload failed')
    return payload['documents'][0]['location']


def _embed(doc_loc: str, allm_base: str, allm_key: str, workspace: str) -> None:
    body = json.dumps({'adds': [doc_loc]}).encode()
    headers = {'Authorization': f'Bearer {allm_key}',
               'Content-Type': 'application/json'}
    status, resp = _http(
        'POST', f'{allm_base}/v1/workspace/{workspace}/update-embeddings',
        headers, data=body, timeout=300,
    )
    if status >= 400:
        payload = json.loads(resp.decode())
        raise RuntimeError(payload.get('error') or resp.decode())


def upload_issue(key: str, source_url: str, jira_auth: str, jira_base: str,
                 allm_base: str, allm_key: str, workspace: str) -> str:
    ISSUES_DIR.mkdir(parents=True, exist_ok=True)
    fp = ISSUES_DIR / f'{key}.md'
    title = f'JIRA {key}'
    md = fetch_issue_md(key, source_url, jira_auth, jira_base)
    fp.write_text(md, encoding='utf-8')
    tm = re.search(rf'Issue {key}: (.+)', md)
    if tm and '[NOT ACCESSIBLE]' not in tm.group(1):
        title = f'JIRA {key} - {tm.group(1).strip()}'
    loc = _upload(fp, title, allm_base, allm_key)
    _embed(loc, allm_base, allm_key, workspace)
    return title


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description='Sync JIRA issues into AnythingLLM.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    g = p.add_argument_group('Jira')
    g.add_argument('--jira-url', default=None,
                   help='Jira base URL (fallback: env JIRA_URL / mcp.json)')
    g.add_argument('--jira-username', default=None,
                   help='Jira username (fallback: env JIRA_USERNAME / mcp.json)')
    g.add_argument('--jira-token', default=None,
                   help='Jira API token (fallback: env JIRA_API_TOKEN / mcp.json)')

    g = p.add_argument_group('AnythingLLM')
    g.add_argument('--allm-url', default=None,
                   help='AnythingLLM API base URL (fallback: env ANYTHINGLLM_BASE_URL / mcp.json)')
    g.add_argument('--allm-key', default=None,
                   help='AnythingLLM API key (fallback: env ANYTHINGLLM_API_KEY / mcp.json)')
    g.add_argument('--workspace', default=None,
                   help='AnythingLLM workspace slug (fallback: env ANYTHINGLLM_WORKSPACE / mcp.json)')

    g = p.add_argument_group('Sync options')
    g.add_argument('--project', action='append', dest='projects',
                   help='Jira project key (repeatable; required via CLI, env, or script defaults)')
    g.add_argument('--limit', type=int, default=0,
                   help='Max new issues to process (0 = unlimited)')
    g.add_argument('--dry-run', action='store_true',
                   help='List pending issues without uploading')
    g.add_argument('--delay', type=float, default=REQUEST_DELAY,
                   help=f'Seconds between uploads (default: {REQUEST_DELAY})')
    return p.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    args = parse_args()
    projects = tuple(args.projects or DEFAULT_PROJECTS)
    if not projects:
        log('ERROR: No projects specified. Use --project, or set defaults in '
            'the script.')
        return 1

    jira_base = _resolve(args.jira_url, 'JIRA_URL', 'jira_rh',
                         'JIRA_URL', DEFAULT_JIRA_URL)
    if jira_base:
        jira_base = jira_base.rstrip('/')
    if not jira_base:
        log('ERROR: Jira URL not found. Use --jira-url, JIRA_URL env var, '
            'or configure jira_rh in ~/.cursor/mcp.json')
        return 1
    jira_user = _resolve(args.jira_username, 'JIRA_USERNAME', 'jira_rh',
                         'JIRA_USERNAME')
    jira_token = _resolve(args.jira_token, 'JIRA_API_TOKEN', 'jira_rh',
                          'JIRA_API_TOKEN')
    if not jira_user or not jira_token:
        log('ERROR: Jira credentials not found. Use --jira-username/--jira-token, '
            'JIRA_USERNAME/JIRA_API_TOKEN env vars, or configure jira_rh in '
            '~/.cursor/mcp.json')
        return 1
    jira_auth = 'Basic ' + base64.b64encode(
        f'{jira_user}:{jira_token}'.encode()).decode()

    allm_base = _resolve(args.allm_url, 'ANYTHINGLLM_BASE_URL', 'anythingllm',
                         'ANYTHINGLLM_BASE_URL', DEFAULT_ALLM_URL)
    if allm_base:
        allm_base = allm_base.rstrip('/')
    if not allm_base:
        log('ERROR: AnythingLLM URL not found. Use --allm-url, '
            'ANYTHINGLLM_BASE_URL env var, or configure anythingllm in '
            '~/.cursor/mcp.json')
        return 1
    allm_key = _resolve(args.allm_key, 'ANYTHINGLLM_API_KEY', 'anythingllm',
                        'ANYTHINGLLM_API_KEY')
    if not allm_key:
        log('ERROR: AnythingLLM API key not found. Use --allm-key, '
            'ANYTHINGLLM_API_KEY env var, or configure anythingllm in '
            '~/.cursor/mcp.json')
        return 1
    workspace = _resolve(args.workspace, 'ANYTHINGLLM_WORKSPACE', 'anythingllm',
                         'ANYTHINGLLM_WORKSPACE', DEFAULT_WORKSPACE)
    if not workspace:
        log('ERROR: AnythingLLM workspace not found. Use --workspace, '
            'ANYTHINGLLM_WORKSPACE env var, or configure anythingllm in '
            '~/.cursor/mcp.json')
        return 1

    progress = load_progress()
    stored_keys = list_stored_keys(allm_base, allm_key)
    already_done = set(progress['completed']) | stored_keys

    log(f'Projects: {", ".join(projects)} | workspace={workspace} | '
        f'already stored={len(already_done)}')

    pending: list[tuple[str, str, str]] = []
    for project in projects:
        log(f'Listing issues in {project}...')
        keys = list_project_keys(project, jira_auth, jira_base)
        progress['projects'][project] = {
            'total': len(keys),
            'listed_at': datetime.now(timezone.utc).isoformat(),
        }
        save_progress(progress)
        log(f'{project}: {len(keys)} total, '
            f'{sum(1 for k in keys if k not in already_done)} new')
        for key in keys:
            if key not in already_done:
                pending.append((project, key, f'{jira_base}/browse/{key}'))

    if args.limit > 0:
        pending = pending[:args.limit]

    log(f'Pending upload: {len(pending)} issues')
    if args.dry_run:
        for proj, key, url in pending[:20]:
            log(f'  would upload {key} ({proj}) {url}')
        if len(pending) > 20:
            log(f'  ... and {len(pending) - 20} more')
        return 0

    processed = 0
    for idx, (proj, issue_key, source_url) in enumerate(pending, 1):
        prefix = f'[{idx}/{len(pending)}] {issue_key}'
        try:
            log(f'{prefix}: fetching...')
            title = upload_issue(issue_key, source_url, jira_auth, jira_base,
                                 allm_base, allm_key, workspace)
            progress['completed'][issue_key] = {
                'project': proj, 'url': source_url, 'title': title,
                'uploaded_at': datetime.now(timezone.utc).isoformat(),
            }
            progress['failed'].pop(issue_key, None)
            save_progress(progress)
            already_done.add(issue_key)
            tag = 'stub' if '[NOT ACCESSIBLE]' in title else 'OK'
            log(f'{prefix}: uploaded {tag}')
            processed += 1
        except Exception as exc:  # noqa: BLE001
            progress['failed'][issue_key] = {
                'project': proj, 'url': source_url,
                'error': str(exc),
                'failed_at': datetime.now(timezone.utc).isoformat(),
            }
            save_progress(progress)
            log(f'{prefix}: FAILED - {exc}')
        time.sleep(args.delay)

    log(f'Done: processed={processed}, total_completed={len(progress["completed"])}, '
        f'failed={len(progress["failed"])}')
    return 1 if progress['failed'] else 0


if __name__ == '__main__':
    sys.exit(main())
