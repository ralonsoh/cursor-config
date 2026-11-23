# AGENTS.md — agent guidance for this repository


## Git commit messages

- Limit every line to **72 characters**, including the title. Wrap body
  text at word boundaries.
- When a line ending in a colon introduces a list or a code block, the
  list or block starts on the very next line — no extra blank line after
  the colon.
- End every commit message with a trailer block. The mandatory trailers
  are, in this relative order and always at the bottom:
```
Assisted-By: <model name>
Signed-off-by: <author name> <author email>
Change-Id: <generated or preserved Change-Id>
```

- **Assisted-By** — the LLM model used to produce the change. Use the
  model name without the company name (e.g. `Claude Opus 4.6`, not
  `Anthropic Claude Opus 4.6`). Update it if the underlying model
  changes.
- **Signed-off-by** — the author's git identity (see the `git-identity`
  rule in `rules/`). Only add it when no other `Signed-off-by` is
  already present.
- **Change-Id** — always the very last line of the commit message.
  Generate a new one for new commits; preserve the existing value when
  amending or rewording.
- **Never** commit a `Co-authored-by: Cursor <cursoragent@cursor.com>`
  trailer. The agent harness appends it to every `git commit`/`--amend`,
  after the trailer block, which puts it below `Change-Id`. Check
  `git log -1 --format=%B` before considering the commit final and drop
  the line if it is there — e.g. rebuild the commit from a message file
  with `git commit-tree` and `git reset --soft`, or strip it with
  `git log -1 --format=%B | sed '/^Co-authored-by: Cursor/d'`.


## Commit titles

- Updating an existing skill: `Update <skill-name>: <short description>`
- Creating a new skill: `Add new skill: <skill name>`


## Repository layout

- `rules/` — global Cursor rules (`.md` files with YAML frontmatter).
  One of them, `rules/git-identity.md`, is a **gitignored secret** (see
  "Building `rules/git-identity.md`" below).
- `skills/` — Cursor Agent Skills (`<name>/SKILL.md`).
- `llm-proxy/` — LLM proxy configuration (secrets gitignored).


## Building `rules/git-identity.md`

`rules/git-identity.md` is a gitignored secret that holds the git commit
identity (name and email). It is not part of the repository history;
every clone or checkout must create it locally. If it is missing, build
it as follows:

1. Copy the template below into `rules/git-identity.md`.
2. Replace `<NAME>` with the git author name and `<EMAIL>` with the
   git author email (ask the user; never guess or invent them).
3. Do NOT remove the file afterwards — every commit in this
   repository depends on it for the author, committer, and
   `Signed-off-by` values.

Template:

````
---
description: Git commit identity configuration
alwaysApply: false
---

# Git Commit Identity

When creating git commits, always set the **author** and **committer** to:

- **Name:** `<NAME>`
- **Email:** `<EMAIL>`

Use `--author` for the author and `GIT_COMMITTER_NAME` / `GIT_COMMITTER_EMAIL`
environment variables for the committer:

```
GIT_COMMITTER_NAME="<NAME>" GIT_COMMITTER_EMAIL="<EMAIL>" \
  git commit --author="<NAME> <<EMAIL>>"
```
````

Verify after creating it: `git check-ignore rules/git-identity.md` must
succeed (the file is a secret and must never be tracked), and
`git status` must not list it.
