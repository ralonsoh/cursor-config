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
