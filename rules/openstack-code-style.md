---
description: OpenStack Python coding style (PEP 8 + hacking) and mandatory pep8 tox checks
globs: **/*.py
alwaysApply: false
---

# OpenStack Code Style

Follow [PEP 8](https://peps.python.org/pep-0008/) and the [OpenStack Style Guidelines](https://docs.openstack.org/hacking/latest/user/hacking.html), enforced by the [hacking](https://docs.openstack.org/hacking/latest/user/usage.html) flake8 plugins. Match conventions in the surrounding file and project.

## Mandatory pep8 check

After adding or modifying Python code in an OpenStack project, run pep8 from that project's root (where `tox.ini` lives):

```bash
tox -epep8
```

- Run this in the **same repo** you changed (e.g. `neutron`, `nova`, `neutron-lib`).
- Do not consider the work done until `tox -epep8` passes.
- Fix every reported violation; use `# noqa: Hxxx` only when a rule exception is genuinely justified.

## Style essentials

**Imports** — import modules, not objects (except typing/stdlib/sqlalchemy/i18n exceptions). One import per line; no wildcard imports; no relative imports. Order: stdlib → third-party → project, each group alphabetically, blank line between groups.

**Exceptions** — never bare `except:`; catch the most specific exception. Use `LOG.warning`, not `LOG.warn`.

**Formatting** — prefer parentheses over backslashes for line continuation. Break long dicts/lists across lines with trailing commas on the last item. Wrap long call arguments across lines.

**Docstrings** — one-line summary (< 80 chars), blank line, then details. No leading space; multi-line docstrings start and end on their own lines.

**Logging & i18n** — delay string interpolation at log calls (`LOG.error("Missing %s", param)`). Use `_()`, `_LE()`, etc.; for multiple variables use keyword placeholders.

**Tests** — add tests for new features and bug fixes. Use specific exceptions in `assertRaises`, not `Exception`. Prefer `assertIsNone`, `assertEqual`, `assertIn`, `assertIsInstance`. Use `unittest.mock`, not the third-party `mock` package.

**Licensing** — new source files need the Apache 2.0 header (full text or `# SPDX-License-Identifier: Apache-2.0`). Empty non-code files stay empty.

**General** — UNIX newlines only. TODOs include author: `# TODO(username)`. No author tags in files. Do not shadow builtins. Do not import eventlet in new code.

## Examples

```python
# BAD
except:
    pass

from nova.api import manager
import logging

# GOOD
except exception.InstanceNotFound:
    raise

import logging

from nova.api import manager
```

```python
# BAD
LOG.error("Missing parameter: %s" % param)

# GOOD
LOG.error("Missing parameter: %s", param)
```
