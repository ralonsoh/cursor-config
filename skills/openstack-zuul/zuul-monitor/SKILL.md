---
name: zuul-monitor
description: >-
  Monitor the Zuul CI jobs of an OpenStack Gerrit change in a
  background task and notify the user when they finish. Use when the
  user asks to monitor, watch, or follow the CI jobs of a Gerrit
  change, patch, or review (e.g. "monitor change 1009192", "watch the
  CI of my patch"), or when the user asks for the current Zuul job
  status of an OpenStack change.
---

# Zuul Monitor

Monitor the Zuul CI jobs of an OpenStack Gerrit change and notify the
user when they finish.

## Monitor a change

When the user asks to monitor a Gerrit change (by number or URL):

1. Start the monitor as a **background shell task** (so the session is
   not blocked):

   ```bash
   python3 ~/.cursor/skills/openstack-zuul/zuul-monitor/scripts/zuul_monitor.py \
       <change> --interval 60
   ```

   Use the `notify_on_output` mechanism of the Shell tool with the
   pattern `MONITOR-FINISHED|MONITOR-ERROR` and a short reason such as
   "zuul jobs finished for change N". The script prints one of these
   tags on the final line, which triggers the notification.

2. Tell the user monitoring has started: change number, patchset (it
   follows the latest patchset if the change is re-uploaded), poll
   interval, and that they will be pinged when the jobs finish.

3. When the notification fires, read the terminal output, then report
   to the user:
   - Overall result (SUCCESS / FAILURE / NO_JOBS) and voting tally.
   - Failed voting jobs, with their log URLs from the job table.
   - The Gerrit change URL.

## Script options

```
python3 ~/.cursor/skills/openstack-zuul/zuul-monitor/scripts/zuul_monitor.py \
    <change> [--patchset N] [--interval S] [--timeout S] [--grace S]
    [--zuul-base URL] [--gerrit-base URL] [--tenant NAME]
    [--once] [--json]
```

- `<change>` — Gerrit change number or full URL.
- `--patchset N` — pin a specific patchset instead of following the
  latest one.
- `--interval S` — seconds between polls (default 60).
- `--timeout S` — give up after this many seconds (default 4 hours).
- `--grace S` — seconds to wait for jobs to appear before reporting
  NO_JOBS (default 600). Only relevant for changes never enqueued.
- `--once` — print a one-shot status snapshot and exit (no waiting).
  Use it when the user just asks for the current status.
- `--json` — also print a JSON summary at the end.
- `--zuul-base`, `--gerrit-base`, `--tenant` — override the defaults
  (zuul.opendev.org, review.opendev.org, openstack tenant).

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | all voting jobs succeeded |
| 1 | at least one voting job failed |
| 2 | no CI jobs found for the change |
| 3 | monitor error (timeout, API failure, interrupt) |
| 4 | jobs still in progress (`--once` snapshot, or stalled patchset) |

## One-shot status check

If the user only wants the current status without background
monitoring, run the same script with `--once` in the foreground.

## Related skill

For querying historical build data (filtering by job name, result,
branch, date), use the `zuul-builds-query` skill instead.
