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
```

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
