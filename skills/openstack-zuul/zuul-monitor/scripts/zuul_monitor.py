#!/usr/bin/env python3
"""Monitor the Zuul CI jobs of an OpenStack Gerrit change.

Given a Gerrit change number, resolves its latest patchset (via the
Gerrit REST API), then polls the Zuul status/builds APIs until all
jobs of that patchset finish. Follows new patchsets if the change is
re-uploaded while monitoring.

Prints one progress line per poll and a per-job table at the end. The
last line starts with MONITOR-FINISHED (or MONITOR-ERROR), designed to
be used as a background-task output-notification pattern.

Usage:
    python3 zuul_monitor.py 1009192
    python3 zuul_monitor.py 1009192 --interval 30
    python3 zuul_monitor.py 1009192 --once
    python3 zuul_monitor.py 1009192 --json

Exit codes:
    0  all voting jobs succeeded
    1  at least one voting job failed (FAILURE, UNSTABLE, ...)
    2  no CI jobs found for the change
    3  monitor error (timeout, API failure)
    4  jobs still in progress (only from --once, or a stalled patchset)

Author: Rodolfo Alonso Hernandez
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_ZUUL_BASE = "https://zuul.opendev.org"
DEFAULT_GERRIT_BASE = "https://review.opendev.org"
DEFAULT_TENANT = "openstack"
DEFAULT_INTERVAL = 60
DEFAULT_TIMEOUT = 4 * 3600
DEFAULT_GRACE = 600
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
BUILDS_SETTLE_POLLS = 5

GERRIT_MAGIC = ")]}'"
FINAL_TAG = "MONITOR-FINISHED"
ERROR_TAG = "MONITOR-ERROR"

CHANGE_RE = re.compile(r"(\d{4,})")


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def get_json(url, magic=False):
    """GET a JSON document with retries. Returns parsed JSON."""
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            req = Request(url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                data = resp.read().decode("utf-8")
            if magic and data.startswith(GERRIT_MAGIC):
                data = data[len(GERRIT_MAGIC):]
            return json.loads(data)
        except HTTPError as e:
            last_exc = e
            if e.code in (429, 500, 502, 503) and attempt < MAX_RETRIES - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            last_exc = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    raise RuntimeError(f"request failed after {MAX_RETRIES} attempts: {last_exc}")


def extract_change(value):
    """Extract the change number from a number or a Gerrit URL."""
    value = value.rstrip("/").split("?")[0]
    match = CHANGE_RE.search(value)
    if not match:
        raise ValueError(f"cannot extract a change number from: {value!r}")
    return int(match.group(1))


def resolve_change(gerrit_base, change):
    """Return (current_patchset, project) for a change number."""
    url = f"{gerrit_base}/changes/{change}/detail?o=CURRENT_REVISION"
    detail = get_json(url, magic=True)
    revision = detail["current_revision"]
    patchset = detail["revisions"][revision]["_number"]
    return patchset, detail.get("project")


def get_status_items(zuul_base, tenant, change, patchset):
    url = f"{zuul_base}/api/tenant/{tenant}/status/change/{change},{patchset}"
    return get_json(url)


def get_patchset_builds(zuul_base, tenant, change, patchset):
    url = f"{zuul_base}/api/tenant/{tenant}/builds?change={change}&limit=200"
    builds = get_json(url)
    return [b for b in builds
            if str(b.get("ref", {}).get("patchset", "")) == str(patchset)]


def describe_progress(items):
    """One-line progress summary for the queue items of a patchset."""
    total = finished = 0
    counts = {}
    for item in items:
        for job in item.get("jobs", []):
            total += 1
            result = job.get("result")
            if result:
                finished += 1
                counts[result] = counts.get(result, 0) + 1
    parts = [f"{counts[r]} {r}" for r in sorted(counts)]
    detail = f" ({', '.join(parts)})" if parts else ""
    reasons = [r for item in items for r in item.get("failing_reasons", [])]
    if reasons:
        detail += f" reasons={reasons}"
    return f"{finished}/{total} jobs finished{detail}"


def latest_builds(builds):
    """Latest build per (job_name, pipeline)."""
    latest = {}
    for b in sorted(builds, key=lambda b: b.get("_id") or 0):
        latest[(b.get("job_name"), b.get("pipeline"))] = b
    return sorted(latest.values(), key=lambda b: b.get("job_name") or "")


def summarize(builds):
    """Return (overall_result, jobs) for the patchset.

    overall is NO_JOBS, IN_PROGRESS (voting builds still running), the
    first failing result, or SUCCESS.
    """
    jobs = latest_builds(builds)
    voting = [b for b in jobs if b.get("voting")]
    pending = [b for b in voting if b.get("result") is None]
    failed = [b for b in voting if b.get("result") not in (None, "SUCCESS")]
    if not jobs:
        overall = "NO_JOBS"
    elif pending:
        overall = "IN_PROGRESS"
    elif failed:
        overall = failed[0].get("result") or "FAILURE"
    else:
        overall = "SUCCESS"
    return overall, jobs


def print_job_table(jobs):
    name_w = max([len(b.get("job_name") or "") for b in jobs] + [10])
    header = (f"{'job'.ljust(name_w)}  {'pipeline':<8} {'voting':<6} "
              f"{'result':<10} {'dur(s)':>7}  log url")
    print(header, flush=True)
    for b in jobs:
        name = b.get("job_name") or "?"
        pipeline = b.get("pipeline") or "?"
        voting = "yes" if b.get("voting") else "no"
        result = b.get("result") or "..."
        duration = b.get("duration")
        duration = f"{int(duration)}" if duration else "-"
        log_url = b.get("log_url") or "-"
        print(f"{name.ljust(name_w)}  {pipeline:<8} {voting:<6} "
              f"{result:<10} {duration:>7}  {log_url}", flush=True)


def print_summary(change, patchset, project, gerrit_base, builds,
                  as_json=False):
    overall, jobs = summarize(builds)
    print(flush=True)
    print_job_table(jobs)
    print(flush=True)
    voting = [b for b in jobs if b.get("voting")]
    n_failed = len([b for b in voting if b.get("result") != "SUCCESS"])
    url = (f"{gerrit_base}/c/{project}/+/{change}" if project
           else f"{gerrit_base}/changes/{change}")
    print(f"{FINAL_TAG} change={change} patchset={patchset} "
          f"overall={overall} voting={len(voting) - n_failed}/{len(voting)} "
          f"url={url}", flush=True)
    if as_json:
        print(json.dumps({
            "change": change,
            "patchset": patchset,
            "project": project,
            "overall": overall,
            "voting_total": len(voting),
            "voting_failed": n_failed,
            "url": url,
            "jobs": [{
                "job": b.get("job_name"),
                "pipeline": b.get("pipeline"),
                "voting": b.get("voting"),
                "result": b.get("result"),
                "duration": b.get("duration"),
                "log_url": b.get("log_url"),
                "build_url": (f"https://zuul.opendev.org/t/openstack/build/"
                              f"{b['uuid']}") if b.get("uuid") else None,
            } for b in jobs],
        }, indent=2), flush=True)
    return overall


def monitor(args):
    change = extract_change(str(args.change))
    zuul = args.zuul_base.rstrip("/")
    gerrit = args.gerrit_base.rstrip("/")

    if args.patchset:
        patchset, project = args.patchset, None
        log(f"monitoring change {change} patchset {patchset} (pinned)")
    else:
        patchset, project = resolve_change(gerrit, change)
        log(f"monitoring change {change} patchset {patchset} "
            f"(following latest patchset)")
    log(f"interval={args.interval}s timeout={args.timeout}s")

    start = time.monotonic()
    empty_since = None
    settle_polls = 0
    last_progress = ""

    while True:
        elapsed = time.monotonic() - start
        if elapsed > args.timeout:
            print(f"{ERROR_TAG} change={change} patchset={patchset} "
                  f"reason=timeout after {int(elapsed)}s", flush=True)
            return 3

        # Follow new patchsets unless pinned.
        if not args.patchset:
            try:
                ps_now, proj_now = resolve_change(gerrit, change)
                if ps_now != patchset:
                    log(f"patchset updated {patchset} -> {ps_now}; "
                        "following new patchset")
                    patchset, project = ps_now, proj_now
                    empty_since = None
                    settle_polls = 0
            except Exception as e:  # noqa: BLE001 - keep polling
                log(f"warning: could not re-resolve patchset: {e}")

        try:
            items = get_status_items(zuul, args.tenant, change, patchset)
            builds = get_patchset_builds(zuul, args.tenant, change, patchset)
        except Exception as e:  # noqa: BLE001 - transient API errors
            log(f"warning: API error: {e}; retrying in {args.interval}s")
            time.sleep(args.interval)
            continue

        if args.once:
            if items:
                log(f"status: {describe_progress(items)}")
            else:
                log("status: no active queue items for this patchset")
            if builds:
                overall = print_summary(change, patchset, project, gerrit,
                                        builds, as_json=args.json)
                if overall == "IN_PROGRESS":
                    return 4
                return 0 if overall == "SUCCESS" else 1
            log("no builds recorded for this patchset yet")
            return 2

        if items:
            progress = describe_progress(items)
            if progress != last_progress:
                log(f"progress: {progress}")
                last_progress = progress
            empty_since = None
        else:
            # No queue items: either finished, or not enqueued yet.
            if builds:
                _, jobs = summarize(builds)
                pending = [b for b in jobs
                           if b.get("voting") and b.get("result") is None]
                if pending and settle_polls < BUILDS_SETTLE_POLLS:
                    settle_polls += 1
                    log("queue empty; waiting for builds API to settle")
                else:
                    overall = print_summary(change, patchset, project,
                                            gerrit, builds, as_json=args.json)
                    if overall == "IN_PROGRESS":
                        return 4
                    return 0 if overall == "SUCCESS" else 1
            else:
                if empty_since is None:
                    empty_since = time.monotonic()
                waited = time.monotonic() - empty_since
                if waited > args.grace:
                    print(f"{FINAL_TAG} change={change} "
                          f"patchset={patchset} overall=NO_JOBS "
                          f"voting=0/0 url={gerrit}/changes/{change}",
                          flush=True)
                    return 2
                log(f"no active queue items for patchset {patchset} yet "
                    f"(grace: {int(args.grace - waited)}s left)")

        time.sleep(args.interval)


def main():
    parser = argparse.ArgumentParser(
        description="Monitor the Zuul CI jobs of an OpenStack Gerrit "
                    "change until they finish.")
    parser.add_argument("change",
                        help="Gerrit change number or URL (e.g. 1009192)")
    parser.add_argument("--patchset", type=int,
                        help="pin this patchset instead of following "
                             "the latest one")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"seconds between polls "
                             f"(default: {DEFAULT_INTERVAL})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"give up after this many seconds "
                             f"(default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--grace", type=int, default=DEFAULT_GRACE,
                        help=f"seconds to wait for jobs to appear before "
                             f"reporting NO_JOBS (default: {DEFAULT_GRACE})")
    parser.add_argument("--zuul-base", default=DEFAULT_ZUUL_BASE,
                        help=f"Zuul base URL (default: {DEFAULT_ZUUL_BASE})")
    parser.add_argument("--gerrit-base", default=DEFAULT_GERRIT_BASE,
                        help=f"Gerrit base URL "
                             f"(default: {DEFAULT_GERRIT_BASE})")
    parser.add_argument("--tenant", default=DEFAULT_TENANT,
                        help=f"Zuul tenant (default: {DEFAULT_TENANT})")
    parser.add_argument("--once", action="store_true",
                        help="print one status snapshot and exit")
    parser.add_argument("--json", action="store_true",
                        help="also print a JSON summary at the end")
    args = parser.parse_args()

    try:
        sys.exit(monitor(args))
    except KeyboardInterrupt:
        print(f"{ERROR_TAG} change={args.change} reason=interrupted",
              flush=True)
        sys.exit(3)
    except Exception as e:  # noqa: BLE001 - report and fail cleanly
        print(f"{ERROR_TAG} change={args.change} reason={e}", flush=True)
        sys.exit(3)


if __name__ == "__main__":
    main()
