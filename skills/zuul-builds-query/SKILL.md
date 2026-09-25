# Zuul Builds Query Skill

Query the Zuul CI API for job executions with filtering by branch, pipeline, result, change, and start time.

## Location

The script is at: `~/.cursor/skills/zuul-builds-query/scripts/zuul_builds.py`

## Usage

### Basic Syntax

```bash
python3 ~/.cursor/skills/zuul-builds-query/scripts/zuul_builds.py [OPTIONS]
```

### Required Filters (at least one)

You must provide at least one filter:
- `--job-name`: Job name (e.g., `neutron-functional`)
- `--result`: Build result (`SUCCESS`, `FAILURE`, `UNSTABLE`, `ABORTED`, `TIMED_OUT`, etc.)
- `--branch`: Git branch (e.g., `stable/train`)
- `--pipeline`: Pipeline name (`gate`, `check`, `post`, `periodic`)
- `--project`: Project name (e.g., `openstack/neutron`)
- `--change`: Change number (e.g., `123456/7`)
- `--start-time-after`: ISO 8601 or epoch timestamp
- `--start-time-before`: ISO 8601 or epoch timestamp

### Common Options

| Option | Description | Default |
|--------|-------------|---------|
| `--zuul-base` | Zuul base URL | `https://zuul.opendev.org` |
| `--tenant` | Zuul tenant | `openstack` |
| `--limit` | Max results (1-200) | 20 |
| `--skip` | Pagination offset | 0 |
| `--json` | Output as JSON | Off |
| `--count` | Only print count | Off |
| `--show-all` | Show all build details | Off |
| `--verbose` | Verbose output | Off |

### Examples

#### Count TIMED_OUT builds for a job
```bash
python3 ~/.cursor/skills/zuul-builds-query/scripts/zuul_builds.py \
    --job-name neutron-functional \
    --result TIMED_OUT \
    --count
```

#### Get last 10 failed builds with details
```bash
python3 ~/.cursor/skills/zuul-builds-query/scripts/zuul_builds.py \
    --job-name neutron-functional \
    --result FAILURE \
    --limit 10 \
    --show-all
```

#### Query by branch and pipeline
```bash
python3 ~/.cursor/skills/zuul-builds-query/scripts/zuul_builds.py \
    --job-name neutron-functional \
    --branch stable/train \
    --pipeline periodic \
    --result FAILURE \
    --limit 5
```

#### Filter by date range
```bash
python3 ~/.cursor/skills/zuul-builds-query/scripts/zuul_builds.py \
    --job-name neutron-functional \
    --result FAILURE \
    --start-time-after "2026-09-01" \
    --start-time-before "2026-09-25" \
    --limit 10
```

#### Get builds for a specific change
```bash
python3 ~/.cursor/skills/zuul-builds-query/scripts/zuul_builds.py \
    --job-name neutron-check \
    --change 1007403/2 \
    --show-all
```

#### Output as JSON for scripting
```bash
python3 ~/.cursor/skills/zuul-builds-query/scripts/zuul_builds.py \
    --job-name neutron-functional \
    --result FAILURE \
    --limit 5 \
    --json
```

## API Limitations

The Zuul API at `zuul.opendev.org` has known pagination issues:
- First page (skip=0, limit=200) works reliably
- Deeper pagination (skip > 200) may return 500 errors or timeout
- The script handles this gracefully with error messages
- For large result sets, use `--count` with a reasonable `--limit` to get a minimum estimate

## Script Features

- **Automatic pagination**: Fetches multiple pages until limit is reached
- **Retry logic**: Retries failed requests up to 3 times
- **Time filtering**: Client-side filtering for `--start-time-after` and `--start-time-before`
- **Multiple output formats**: Human-readable, JSON, or count-only
- **Error handling**: Graceful degradation on API errors

## Available Results

Common build results:
- `SUCCESS` - Build passed
- `FAILURE` - Build failed
- `UNSTABLE` - Build was unstable (tests failed but build succeeded)
- `ABORTED` - Build was aborted
- `TIMED_OUT` - Build timed out
- `NEW` - Build is new/queued

## Available Pipelines

- `check` - Gerrit change verification
- `gate` - Gerrit change gating
- `periodic` - Scheduled periodic builds
- `post` - Post-commit builds
