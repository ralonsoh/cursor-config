# AGENTS.md — agent guidance for this repository


## Git commit messages

- Limit every line to **72 characters**, including the title. Wrap body
  text at word boundaries.
- End every commit message with a trailer block. The mandatory trailers
  are (in this relative order, always at the bottom):

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


## Repository layout

- `rules/` — global Cursor rules (`.md` files with YAML frontmatter).
- `skills/` — Cursor Agent Skills (`<name>/SKILL.md`).
- `llm-proxy/` — LLM proxy configuration (secrets gitignored).
