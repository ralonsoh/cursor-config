# Cursor Configuration

Personal Cursor IDE rules and skills, designed to be symlinked into
`~/.cursor/` so they apply globally across all projects.

## Setup

```bash
ln -sf /opt/ralonsoh/cursor-config/rules  ~/.cursor/rules
ln -sf /opt/ralonsoh/cursor-config/skills ~/.cursor/skills
```

## Structure

```
rules/
skills/
llm-proxy/
```

## Gemini web proxy

There is no API key for the consumer Gemini tiers, so `llm-proxy/
gemini_web_proxy.py` reuses a browser session instead: it takes the
`__Secure-1PSID` cookie of an account signed in to `gemini.google.com` and
exposes `/v1/chat/completions`, which Cursor's `openAIBaseUrl` understands.

```bash
cd llm-proxy
python3 -m venv .venv
.venv/bin/pip install gemini-webapi
cp config.gemini.toml.example config.gemini.toml   # paste cookies here
.venv/bin/python gemini_web_proxy.py --config config.gemini.toml --check
.venv/bin/python gemini_web_proxy.py --config config.gemini.toml
```

`--check` prints the models the account offers and exits; use it to confirm
the cookie works before pointing Cursor at the proxy. Requests that hit an
unauthenticated session fail immediately with a 401 instead of connecting.

To keep the effort-injection proxy in front of it, chain the two:

```
Cursor -> :8787 cursor_effort_proxy.py -> :6969 gemini_web_proxy.py
```

```bash
cp config.chain.toml.example config.chain.toml
python3 cursor_effort_proxy.py --config config.chain.toml
```

Then in Cursor's custom OpenAI-compatible settings:

- Base URL: `http://127.0.0.1:8787/v1`
- API key: any non-empty string — the Gemini proxy authenticates with cookies

Limitations of driving the web UI:

- The web UI has no function calling. `tool_mode = "prompt"` emulates one
  call per reply by prompting for JSON and parsing it back out, which means
  every reply is buffered and cannot stream. Expect degraded agent mode.
- The library rotates `__Secure-1PSIDTS`, which can sign the same account out
  of a browser used elsewhere. Use a dedicated Google account, and treat
  `config.gemini.toml` as a password.
- Rotated cookies are cached in `~/.cache/gemini-webkit-proxy` with mode 0700.


## Pre-commit hook

`.pre-commit-config.yaml` runs
[gitleaks](https://github.com/gitleaks/gitleaks) over the staged
content of every commit, so an accidentally committed credential is
rejected before it enters history.

Enable it once per clone:

```bash
pre-commit install
```

The `gitleaks` hook is compiled from source by pre-commit, which
provisions its own Go toolchain — no local Go install is required. To
run the checks manually against the staged files:

```bash
pre-commit run
```

`git commit --no-verify` bypasses the hook. A history-wide scan belongs
in CI, where it cannot be skipped.

## Secrets

`skills/remote-vm/vms.json` contains VM credentials and is excluded from
version control via `.gitignore`. Create it manually with:

```json
[
  {
    "name": "vm-name",
    "ip": "x.x.x.x",
    "user": "username",
    "password": "password",
    "description": "VM description"
  }
]
```
