---
name: openstack-new-release
description: >-
  Creates a patch in the OpenStack releases repository to add a new version for
  a library or project deliverable. Use when the user asks to release a new
  version, update deliverables, or create a releases repo patch for a project
  like neutron-lib, oslo.config, or neutron.
---

# OpenStack New Release

Create a patch in the [openstack/releases](https://opendev.org/openstack/releases)
repository that adds a new version entry for a specified project.

## Required Input

Collect from the user before starting:

| Input | Example |
|-------|---------|
| **Project** | `neutron-lib`, `neutron`, `oslo.config` |
| **Version** | `4.0.0` |

If either is missing, ask for it.

## Prerequisites

- Local clone of the releases repo (default: `/opt/stack/releases`)
- Local clone of the project repo (default: `/opt/stack/<project>`)
- Both repos on up-to-date branches (`git fetch`)
- If the required project is not in the current workspace, ask to add it

## Workflow

Copy this checklist and track progress:

```
Release patch progress:
- [ ] Step 1: Resolve deliverable file and release series
- [ ] Step 2: Validate version number
- [ ] Step 3: Resolve git hash and changelog
- [ ] Step 4: Edit deliverable YAML
- [ ] Step 5: Create commit (only if user asks)
```

### Step 1: Find the deliverable file and release series

**Find all deliverable files for the project:**

```bash
find /opt/stack/releases/deliverables -name '<project>.yaml' | sort
```

The deliverable filename matches the project name (e.g. `neutron-lib.yaml`).

**Determine the target release series:**

1. Read `/opt/stack/releases/data/series_status.yaml` — entries are ordered newest-first.
2. **Default:** use the first series with `status: development`. If none, use the first with `status: maintained`.
3. Confirm the project has a deliverable file under that series directory (e.g. `deliverables/hibiscus/neutron-lib.yaml`).

**If the project appears in multiple active series** (e.g. both `gazpacho` and `hibiscus`), or the user likely wants a stable/EOL series, **ask which series** before editing. Do not guess.

**If no deliverable file exists** in the target series, stop and tell the user — a new deliverable file for a series is a separate task.

### Step 2: Validate the version number

Read the target deliverable YAML and find the **current latest version** (last entry under `releases:`).

**Version must be greater than the current latest.** Compare with:

```bash
printf '%s\n' '<current>' '<new>' | sort -V
```

If the new version is not strictly greater, stop and report the conflict.

**Check OpenStack semver guidelines** (see [references/versioning.md](references/versioning.md)):

1. Confirm the version format matches the deliverable `release-type` (default: `X.Y.Z` semver).
2. Infer the expected bump type from changes since the last tag:
   - **Major (X.0.0):** backwards-incompatible API or behavior changes
   - **Minor (X.Y.0):** new features, new dependencies, or higher minimum dependency versions
   - **Patch (X.Y.Z):** bug fixes only, no dependency lower-bound increases
3. **Warn the user** if the requested version does not match the inferred bump type. Proceed only after explicit confirmation.

Also check dependency changes when reviewing the changelog:

```bash
cd /opt/stack/<project>
git diff <prev_tag>..HEAD -- requirements.txt setup.cfg test-requirements.txt
```

A higher minimum dependency version requires at least a **minor** bump, not patch.

### Step 3: Resolve git hash and changelog

**Project repo:** default `/opt/stack/<project>`. If missing, read the `repo:` field from the deliverable YAML (e.g. `openstack/neutron-lib`) and locate the local clone.

**Branch:** use `master` (or `main`) for the development series. For maintained/stable series, use the appropriate `stable/<release-id>` branch.

**Hash:** full 40-character SHA of HEAD on that branch:

```bash
cd /opt/stack/<project>
git fetch
git rev-parse HEAD
```

**Previous tag:** the current latest version from the deliverable YAML (e.g. `3.25.0`).

**Changelog for commit body:**

```bash
cd /opt/stack/<project>
git log --oneline --no-merges <prev_tag>..<new_hash>
```

If the previous version was never tagged in the project repo, use the hash from the deliverable YAML of that version instead of the tag name.

### Step 4: Edit the deliverable YAML

File: `/opt/stack/releases/deliverables/<series>/<project>.yaml`

**Append** a new entry at the end of the `releases:` list (never insert in the middle):

```yaml
  - version: <new_version>
    projects:
      - repo: openstack/<project>
        hash: <full_40_char_sha>
```

Rules from OpenStack releases documentation:

- Always add new releases to the **end** of the list
- Never update hashes or versions of previously released entries
- Preserve existing YAML formatting and indentation (2 spaces)

**Alternative:** the releases repo provides `tox -e venv -- new-release <series> <deliverable> <type>` (`major`, `feature`, `bugfix`), which auto-calculates version and hash. Use it only when the user wants an **automatic** bump, not a specific version.

### Step 5: Create the commit

Only commit when the user explicitly asks.

**Commit title** (first line):

```
Release <project> <version> version
```

Examples: `Release neutron-lib 4.0.0 version`, `Release oslo.config 9.4.0 version`

For milestone releases in a named series, optionally append the series: `Release neutron-lib 3.25.0 in Hibiscus`

**Commit body:** paste the git log output, prefixed with the command:

```
$ git log --oneline --no-merges <prev_tag>..<short_hash>
<one line per commit from git log output>
```

Use the short hash (7 chars) in the command line, as in real release commits.

**OpenStack commit trailer:**

```
Signed-off-by: <Name> <email>
```

Get name/email from `git config user.name` and `git config user.email` in the releases repo.

**Example full commit message:**

```
Release neutron-lib 4.0.0 version

$ git log --oneline --no-merges 3.25.0..f7a9e8a5
f7a9e8a5 Document ML2 VLAN tri-state capability behavior
9810f963 Add default __mapper_args__ to BASEV2 declarative base
...

Signed-off-by: Rodolfo Alonso Hernandez <ralonsoh@redhat.com>
```

After committing, show `git diff HEAD~1` and `git status` so the user can review before pushing to Gerrit.

## Project Name Resolution

Users may provide names in different forms. Normalize as follows:

| User says | Deliverable file | Typical local path |
|-----------|------------------|--------------------|
| `neutron-lib` | `neutron-lib.yaml` | `/opt/stack/neutron-lib` |
| `neutron` | `neutron.yaml` | `/opt/stack/neutron` |
| `oslo.config` | `oslo.config.yaml` | `/opt/stack/oslo.config` |
| `python-neutronclient` | `python-neutronclient.yaml` | `/opt/stack/python-neutronclient` |

If unsure, search: `find /opt/stack/releases/deliverables -name '*.yaml' -exec grep -l '<name>' {} \;`

## Common Pitfalls

- **Wrong series:** default to latest development series; ask when ambiguous
- **Reusing a version number:** never allowed — each release gets a new version
- **Short hash in YAML:** deliverable files require the full 40-character SHA
- **Missing Signed-off-by:** required for OpenStack Gerrit review
- **Depends-On in release patches:** do not use — release CI validates merged commits only
- **Multiple release patches in a series:** submit one release at a time, not a dependent patch series

## References

- OpenStack versioning rules: [references/versioning.md](references/versioning.md)
- Full releases documentation: https://releases.openstack.org/reference/using.html
- Series status: `/opt/stack/releases/data/series_status.yaml`
