---
name: openstack-git-conventions
description: >-
  Formats OpenStack git commit messages and creates commits using Gerrit
  trailers, Change-Id, quoted heredocs, and the git-identity author. Use when
  the user asks to commit, write a commit message, amend, reword, or run git
  commit in an OpenStack/Gerrit repository.
---

# OpenStack Git Conventions

Read `rules/git-identity.mdc` for author and committer identity before
creating a commit.

## Commit message trailers

Every commit message must end with a trailer block. The **mandatory** trailers
are (in this relative order, always at the bottom):

```
Assisted-By: <model name>
Signed-off-by: <author from git-identity rule>
Change-Id: <generated or preserved Change-Id>
```

### Mandatory trailer rules

- Add the git-identity `Signed-off-by` only when no other `Signed-off-by` already exists in the commit.
- Update the model name if the underlying model changes. Use the model name without the company name (e.g. `Claude Opus 4.6`, not `Anthropic Claude Opus 4.6`).
- `Change-Id` is always the very last line of the commit message.

### Preserving existing trailers

When amending or rewording a commit that already contains trailers, preserve them:

- **Change-Id** — always keep the existing value; never regenerate it.
- **Related-Bug:** — preserve any `Related-Bug: #...` references.
- **Co-Authored-By** — preserve any existing `Co-Authored-By:` lines. (Do NOT add new ones.)
- **Signed-off-by** — if the commit already has a `Signed-off-by:` from someone other than the git-identity author, preserve it and do **not** add the git-identity `Signed-off-by`. Only add the git-identity `Signed-off-by` when no other `Signed-off-by` is present.

Place preserved trailers **above** `Assisted-By`. Lines marked
`(optional)` appear only when the original commit had them:

```
Related-Bug: #<number>                          (optional)
Assisted-By: <model name>
Signed-off-by: Other Person <other@example.com> (if present, replaces git-identity SOB)
Co-Authored-By: Name <email>                    (optional)
Change-Id: I<preserved>
```

When no external `Signed-off-by` exists (the common case):

```
Assisted-By: <model name>
Signed-off-by: <author from git-identity rule>
Change-Id: I<generated or preserved>
```

## Commit message style

- Wrap method, function, and variable names in double backticks (``` `` ```), e.g. ``_delete_port()``, ``ls_get()``.
- The title may include a lowercase prefix followed by `:` to indicate the subsystem or area, e.g. `ovn:`, `dhcp:`, `l3:`, `ovs:`, `ml2:`. Only add a prefix when the change is scoped to a specific subsystem.

## Commit message links

- Reference links in the commit body using `[x]` where `x` is a sequential
  number (1, 2, 3, …).
- Place the link definitions after the last body paragraph and before the
  trailer block.
- Format each link definition as `[x]<url>` — no space between `[x]` and
  the URL.
- Only add link definitions that are referenced in the body text.
- Separate the link section from the trailer block with an empty line.

Example:

```
ovn: fix port binding race condition

The ``_bind_port()`` method can fail when two workers attempt to bind
the same port simultaneously [1]. This was reported in a related
Launchpad bug [2].

[1]https://bugs.launchpad.net/neutron/+bug/1234567
[2]https://review.opendev.org/c/openstack/neutron/+/123456

Assisted-By: Claude Opus 4.6
Signed-off-by: Your Name <you@example.com>
Change-Id: I<generated-or-preserved>
```

## Commit via shell

- Only create commits when the user explicitly asks.
- Use `--author` **and** `GIT_COMMITTER_NAME` / `GIT_COMMITTER_EMAIL` from the `git-identity.mdc` rule. Both author and committer must match to avoid Gerrit rejections.
- Pass the message with a **quoted** heredoc so backticks are not stripped by bash command substitution:

```bash
GIT_COMMITTER_NAME="Your Name" GIT_COMMITTER_EMAIL="you@example.com" \
  git commit --author="Your Name <you@example.com>" -m "$(cat <<'EOF'
doc: Document runtime ``uwsgi`` Python module in WSGI guide

Explain that the ``uwsgi`` module is injected at runtime by the uWSGI
server and is used by ``neutron.common.wsgi_utils`` for options such
as ``start-time`` and ``uwsgi.worker_id()``.

Assisted-By: Composer 2.5
Signed-off-by: Your Name <you@example.com>
Change-Id: I<generated-or-preserved>
EOF
)"
```

(`--author`, committer env vars, and `Signed-off-by` must all match the `git-identity.mdc` rule.)

- Use `<<'EOF'` (quoted delimiter), not `<<EOF`. Unquoted heredocs treat `` `...` `` as command substitution and silently remove backticks from the message.
- Generate `Change-Id` for new commits; preserve the original `Change-Id` when amending.
