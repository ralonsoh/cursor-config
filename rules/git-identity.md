---
description: Git commit identity configuration
alwaysApply: false
---

# Git Commit Identity

When creating git commits, always set the **author** and **committer** to:

- **Name:** `Rodolfo Alonso Hernandez`
- **Email:** `ralonsoh@redhat.com`

Use `--author` for the author and `GIT_COMMITTER_NAME` / `GIT_COMMITTER_EMAIL`
environment variables for the committer:

```
GIT_COMMITTER_NAME="Rodolfo Alonso Hernandez" GIT_COMMITTER_EMAIL="ralonsoh@redhat.com" \
  git commit --author="Rodolfo Alonso Hernandez <ralonsoh@redhat.com>"
```
