---
name: openstack-code
description: >-
  Reviews or writes OpenStack code using personal coding guidelines, OpenStack
  Python style, and the target repo's own review or writing agent files. Use
  when reviewing a Gerrit change, implementing an OpenStack patch, or writing
  or refactoring Python in an OpenStack repository.
---

# OpenStack Code

Load personal rules and the **target repository's** review or writing guidance
before reviewing or changing OpenStack code. Do not paste those files into
the reply.

## 1. Personal rules (always)

Read, then follow:

- `rules/coding-guidelines.mdc`
- `rules/openstack-code-style.mdc`

These live in the cursor-config tree (symlinked as `~/.cursor/rules/`).

## 2. Target repository

Identify the repo from the files or Gerrit change in scope (the directory that
contains `tox.ini` or `.git`). If several repos are in play, use the one being
reviewed or edited.

## 3. Project-specific guidance

Read `AGENTS.md` at the repo root if it exists. Then load **only** the
review or writing files that match the current task. Do not load bug-triage,
commit-message, or unrelated agent docs unless the user asked for those.

Search the repo root in this order; read each hit:

**Review** (user asked to review a change, patch, or Gerrit CL):

1. Links from `AGENTS.md` whose title or path contains `review`
2. `.agents/*review*`
3. `.cursor/skills/**/*review*`
4. `.cursor/rules/**/*review*`

**Writing** (user asked to implement, add, fix, or refactor code):

1. Links from `AGENTS.md` whose title or path contains `writ`, `coding`,
   `hacking`, or `contributor`
2. `.agents/*{writ,coding,hacking}*`
3. `.cursor/skills/**/*{writ,coding,code}*`
4. `.cursor/rules/**/*{writ,coding,code}*`
5. `HACKING.rst` / `TESTING.rst` only when `AGENTS.md` routes to them for
   this task

If none of these exist, continue with the personal rules only.

Project files override personal style where they conflict (for example a
repo-specific test base class). `coding-guidelines.mdc` still applies for
surgical diffs and no extra scope.

## 4. Do the work

**Review:** report findings in this chat. Do not post votes or comments to
Gerrit unless the user explicitly asks.

**Writing:** change only what the request requires. After Python edits, run
`tox -epep8` from that repo root as required by `openstack-code-style.mdc`.
Use `tox` or `stestr`, never `pytest`, when the project `AGENTS.md` says so.

Do not commit unless the user asks. When they do, use `openstack-git-conventions`.
