---
name: jira-to-anythingllm
description: Sync JIRA tickets into a local AnythingLLM instance. Fetches issues from configured Jira projects and stores them as embedded documents. Use when the user asks to ingest, sync, upload, or import Jira tickets into AnythingLLM, or wants to update the local knowledge base with new Jira issues.
disable-model-invocation: true
---

# Jira-to-AnythingLLM sync

Incrementally fetches JIRA issues and uploads them as markdown documents into a local AnythingLLM workspace.

## Prerequisites

An AnythingLLM **workspace** must exist before running the script. The
workspace is where documents get embedded (vectorized) and become searchable
via RAG. Uploading documents to AnythingLLM without a workspace only stores
them on disk — they won't be queryable. Create one via the web UI at
the AnythingLLM web UI or via the API:

```bash
curl -X POST <ANYTHINGLLM_BASE_URL>/v1/workspace/new \
  -H "Authorization: Bearer <your-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"name": "<your-workspace-name>"}'
```

The user must also supply (or have set as environment variables):

| Parameter | CLI flag | Env var | Fallback |
|-----------|----------|---------|----------|
| Jira URL | `--jira-url` | `JIRA_URL` | `~/.cursor/mcp.json` → `jira_rh.env.JIRA_URL` |
| Jira username | `--jira-username` | `JIRA_USERNAME` | `~/.cursor/mcp.json` → `jira_rh.env.JIRA_USERNAME` |
| Jira API token | `--jira-token` | `JIRA_API_TOKEN` | `~/.cursor/mcp.json` → `jira_rh.env.JIRA_API_TOKEN` |
| AnythingLLM URL | `--allm-url` | `ANYTHINGLLM_BASE_URL` | `~/.cursor/mcp.json` → `anythingllm.env.ANYTHINGLLM_BASE_URL` |
| AnythingLLM API key | `--allm-key` | `ANYTHINGLLM_API_KEY` | `~/.cursor/mcp.json` → `anythingllm.env.ANYTHINGLLM_API_KEY` |
| AnythingLLM workspace | `--workspace` | `ANYTHINGLLM_WORKSPACE` | `~/.cursor/mcp.json` → `anythingllm.env.ANYTHINGLLM_WORKSPACE` |
| Jira projects | `--project` (repeatable) | — | None; at least one `--project` is required |

All parameters are required. There are no hardcoded defaults — every value
must come from a CLI flag, an environment variable, or `~/.cursor/mcp.json`.

### Example `~/.cursor/mcp.json`

The script reads credentials from the `jira_rh` and `anythingllm` MCP server
entries. A working configuration looks like this:

```json
{
  "mcpServers": {
    "jira_rh": {
      "command": "npx",
      "args": ["-y", "@sooperset/mcp-atlassian"],
      "env": {
        "JIRA_URL": "https://your-company.atlassian.net",
        "JIRA_USERNAME": "your-email@company.com",
        "JIRA_API_TOKEN": "<your-jira-api-token>"
      }
    },
    "anythingllm": {
      "command": "npx",
      "args": ["-y", "@woyo/anythingllm-mcp-server"],
      "env": {
        "ANYTHINGLLM_BASE_URL": "http://localhost:3001/api",
        "ANYTHINGLLM_API_KEY": "<your-anythingllm-api-key>",
        "ANYTHINGLLM_WORKSPACE": "my-workspace"
      }
    }
  }
}
```

With this in place, the script needs only `--project` flags — everything
else is resolved from the MCP config automatically.

## Quick start

Run the sync script:

```bash
python scripts/jira_to_anythingllm.py
```

Common flags:

```bash
# Preview what would be synced
python scripts/jira_to_anythingllm.py --dry-run

# Sync only one project
python scripts/jira_to_anythingllm.py --project MYPROJECT

# Limit to 50 new tickets
python scripts/jira_to_anythingllm.py --limit 50

# Override credentials via CLI
python scripts/jira_to_anythingllm.py \
  --jira-url https://<your-jira-instance> \
  --jira-username <your-email> \
  --jira-token <your-jira-token> \
  --allm-url <your-anythingllm-api-url> \
  --allm-key <your-anythingllm-key> \
  --workspace <your-workspace>
```

## How it works

1. **List stored tickets** — queries the AnythingLLM documents API and the local ticket cache in `/tmp/jira-to-anythingllm/tickets/` to build a set of already-ingested issue keys.
2. **List Jira issues** — paginates the Jira search API (`project = X ORDER BY key ASC`) for each configured project.
3. **Compute delta** — subtracts stored keys from Jira keys.
4. **Fetch & upload** — for each new issue: fetches full metadata + comments → renders markdown → uploads to AnythingLLM → embeds into the workspace.
5. **Progress file** — writes `/tmp/jira-to-anythingllm/logs/progress.json` after every ticket so runs resume safely.

## File layout

```
/tmp/jira-to-anythingllm/
├── tickets/           # cached markdown per issue
│   ├── PROJ-1234.md
│   └── ...
└── logs/
    ├── sync.log       # human-readable log
    └── progress.json  # resume state
```

## Agent workflow

When the user asks to sync Jira tickets into AnythingLLM:

1. Confirm projects and credentials are available (check env / `~/.cursor/mcp.json`).
2. Run the script in the background:
   ```bash
   nohup python ~/.cursor/skills/jira-to-anythingllm/scripts/jira_to_anythingllm.py \
     >> /tmp/jira-to-anythingllm/logs/sync.log 2>&1 &
   ```
3. Report the PID and how to monitor:
   ```bash
   tail -f /tmp/jira-to-anythingllm/logs/sync.log
   python3 -c "import json; p=json.load(open('/tmp/jira-to-anythingllm/logs/progress.json')); print(len(p['completed']), 'done,', len(p['failed']), 'failed')"
   ```
4. The script is idempotent and resumable; re-running only processes missing tickets.
