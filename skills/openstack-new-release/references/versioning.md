# OpenStack Library and Deliverable Versioning

This reference summarizes how OpenStack projects choose version numbers when
adding entries to deliverable YAML files in the [openstack/releases](https://opendev.org/openstack/releases)
repository. Official guidance lives in the releases documentation; use this
document when validating a proposed version during a release patch.

## Semantic versioning (semver)

OpenStack deliverables use [Semantic Versioning 2.0.0](https://semver.org/) unless
the deliverable YAML specifies a different `release-type` (for example,
cycle-based service versioning).

For typical libraries and tools, versions follow **MAJOR.MINOR.PATCH** (`X.Y.Z`):

| Component | When to increment |
|-----------|-------------------|
| **MAJOR (X)** | Backwards-incompatible changes to public API or behavior consumers rely on |
| **MINOR (Y)** | New backwards-compatible functionality, new dependencies, or raised minimum dependency versions |
| **PATCH (Z)** | Backwards-compatible bug fixes only |

Pre-release and special tags (milestones, RCs) follow the deliverable's
`release-type` and series conventions; see the deliverable file and
[release models](https://releases.openstack.org/reference/release_models.html).

## Choosing major, minor, or patch

When reviewing commits since the last released tag:

### Major bump (X.0.0)

Use when the release includes changes that break compatibility for downstream
users or operators, such as:

- Removing or renaming public APIs, CLI options, or configuration options
- Changing default behavior in a way that requires consumer updates
- Dropping support for a Python version or platform that was previously supported
  (project policy varies; treat as major when documented as breaking)

Reset MINOR and PATCH to `0` after a major bump.

### Minor bump (X.Y.0)

Use when the release adds capability without breaking existing consumers, including:

- New features, API extensions, or optional configuration
- **New runtime or test dependencies**
- **Increasing the minimum required version** of any dependency in
  `requirements.txt`, `setup.cfg`, `setup.py`, `pyproject.toml`, or related pins

Reset PATCH to `0` after a minor bump.

Check dependency lower bounds explicitly:

```bash
git diff <prev_tag>..HEAD -- requirements.txt setup.cfg test-requirements.txt pyproject.toml
```

If any minimum version increases, the release must be at least a **minor** bump,
not a patch.

### Patch bump (X.Y.Z)

Use only when the release contains **bug fixes** and does **not**:

- Add features or new dependencies
- Raise minimum dependency versions
- Change behavior in ways that require operator or developer action

## Dependency rules (critical)

From [Using the releases repository](https://releases.openstack.org/reference/using.html):

> If there is a change going into this release which requires a higher minimum
> version of a dependency, then the **minor** version should be incremented.

**Exception (stable branches):** On some maintained stable branches, versions are
pinned between minor releases. Global-requirements syncs may use a **patch**
bump without incrementing minor to avoid cross-branch consumption issues.
Those changes typically need review from the stable maintenance team
(`stable-maint-core` on Gerrit).

## Version number rules for new releases

- **Always use a new version number** for each release. Never rewrite or retag
  an entry already published in the deliverable file.
- **Append** new releases at the end of the `releases:` list in YAML.
- **Do not** bump versions artificially so unrelated deliverables stay aligned;
  compatible projects are expected to drift over time.
- **Initial versions:** use `0.1.0` for early unstable work; use `1.0.0` for the
  first production-ready release. Avoid starting at a version number that
  collides with an unrelated mature deliverable and confuses consumers.

Compare candidate versions with the current latest entry:

```bash
printf '%s\n' '<current>' '<proposed>' | sort -V
```

The proposed version must sort **strictly after** the current latest.

## `new-release` command types

The releases repo tool `tox -e venv -- new-release SERIES DELIVERABLE TYPE`
maps semantic intent to version bumps:

| TYPE | Typical semver effect |
|------|------------------------|
| `bugfix` | Patch increment |
| `feature` | Minor increment (features, new deps, higher dependency mins) |
| `major` | Major increment (backwards-incompatible changes) |
| `milestone` | Date-based milestone tags (deliverable-specific) |
| `rc` | Release candidate (services; may create stable branch) |

Use the command when the user wants an **automatic** bump from the last entry;
use a manual YAML edit when they specify an exact version.

## Service deliverables vs libraries

**Libraries** (`release-type: semver` or similar): follow X.Y.Z rules above.

**Services** (integrated in a named release): often use cycle-based versioning
(for example `26.0.0`, milestone tags, RCs). Read the deliverable YAML
`release-type` and the series release model before validating.

## Further reading

- [Using the releases repository](https://releases.openstack.org/reference/using.html) — authoritative release request rules
- [Deliverable types](https://releases.openstack.org/reference/deliverable_types.html)
- [Release models](https://releases.openstack.org/reference/release_models.html)
- [Semantic Versioning 2.0.0](https://semver.org/)
- Local series overview: `/opt/stack/releases/data/series_status.yaml`
