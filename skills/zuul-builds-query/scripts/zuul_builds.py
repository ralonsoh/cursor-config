#!/usr/bin/env python3
"""
Zuul Builds Query Tool - Retrieve job executions with filtering.

Queries the Zuul API for build executions, supporting filtering by:
  - job_name: Job name (e.g., neutron-functional)
  - result: Build result (SUCCESS, FAILURE, UNSTABLE, ABORTED, TIMED_OUT, etc.)
  - branch: Git branch (e.g., stable/train)
  - pipeline: Pipeline name (e.g., gate, check, post)
  - project: Project name (e.g., openstack/neutron)
  - change: Change number (e.g., 123456/7)
  - start_time_after: Filter builds after this timestamp (ISO 8601 or epoch)
  - start_time_before: Filter builds before this timestamp (ISO 8601 or epoch)

Usage:
    python3 zuul_builds.py --job-name neutron-functional --result TIMED_OUT
    python3 zuul_builds.py --job-name neutron-functional --branch stable/train --limit 50
    python3 zuul_builds.py --job-name neutron-check --start-time-after "2024-01-01" --result FAILURE

Author: Rodolfo Alonso Hernandez
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# Default Zuul instance
DEFAULT_ZUUL_BASE = "https://zuul.opendev.org"
DEFAULT_TENANT = "openstack"
DEFAULT_LIMIT = 20
MAX_LIMIT = 200
REQUEST_TIMEOUT = 60  # seconds per request
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


class ZuulAPIError(Exception):
    """Raised when the Zuul API returns an error."""
    pass


class ZuulClient:
    """Client for the Zuul REST API."""

    def __init__(self, base_url=DEFAULT_ZUUL_BASE, tenant=DEFAULT_TENANT):
        self.base_url = base_url.rstrip("/")
        self.tenant = tenant

    def _build_url(self, endpoint, params=None):
        """Build a full URL with query parameters."""
        url = f"{self.base_url}/api/tenant/{self.tenant}/{endpoint}"
        if params:
            url += "?" + urlencode(params)
        return url

    def _request(self, url, retries=MAX_RETRIES):
        """Make a GET request with retry logic."""
        for attempt in range(retries):
            try:
                req = Request(url)
                req.add_header("Accept", "application/json")
                with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                    data = resp.read().decode("utf-8")
                return json.loads(data)
            except HTTPError as e:
                # urlopen() raises HTTPError for 4xx/5xx responses.
                if e.code == 500 and attempt < retries - 1:
                    # Deep pagination can return transient 500s; retry.
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                if e.code == 500:
                    skip = (url.split('skip=')[1].split('&')[0]
                            if 'skip=' in url else 'unknown')
                    raise ZuulAPIError(f"Server error 500 at skip={skip}")
                body = e.read().decode("utf-8", errors="replace")[:200]
                raise ZuulAPIError(f"HTTP {e.code}: {body}")
            except (URLError, TimeoutError, OSError) as e:
                if attempt < retries - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                raise ZuulAPIError(f"Request failed after {retries} attempts: {e}")
            except json.JSONDecodeError as e:
                raise ZuulAPIError(f"Invalid JSON response: {e}")
        raise ZuulAPIError(f"Request failed after {retries} attempts")

    def get_builds(self, job_name=None, result=None, branch=None,
                   pipeline=None, project=None, change=None,
                   start_time_after=None, start_time_before=None,
                   skip=0, limit=DEFAULT_LIMIT):
        """
        Query builds with filtering.

        Args:
            job_name: Filter by job name
            result: Filter by result (SUCCESS, FAILURE, UNSTABLE, ABORTED,
                    TIMED_OUT, etc.)
            branch: Filter by branch
            pipeline: Filter by pipeline
            project: Filter by project
            change: Filter by change number
            start_time_after: Filter builds started after this time
            start_time_before: Filter builds started before this time
            skip: Number of results to skip (pagination)
            limit: Maximum number of results to return

        Returns:
            List of build dictionaries
        """
        params = {}
        if job_name:
            params["job_name"] = job_name
        if result:
            params["result"] = result
        if branch:
            params["branch"] = branch
        if pipeline:
            params["pipeline"] = pipeline
        if project:
            params["project"] = project
        if change:
            params["change"] = change

        builds = []
        current_skip = skip
        max_pages = 10  # Prevent infinite pagination
        page_size = min(limit, MAX_LIMIT)

        for page in range(max_pages):
            try:
                page_params = dict(params, skip=current_skip, limit=page_size)
                page_builds = self._request(
                    self._build_url("builds", page_params)
                )
            except ZuulAPIError as e:
                print(f"Warning: {e}", file=sys.stderr)
                break

            if not page_builds:
                break

            # Apply time-based filters client-side (API doesn't support them)
            if start_time_after or start_time_before:
                page_builds = self._filter_by_time(
                    page_builds, start_time_after, start_time_before
                )

            builds.extend(page_builds)

            # Apply client-side limit
            if len(builds) >= limit:
                break

            if len(page_builds) < page_size:
                break

            current_skip += page_size

        return builds[:limit]

    def _filter_by_time(self, builds, start_time_after=None,
                        start_time_before=None):
        """Filter builds by start time."""
        filtered = []
        after_epoch = None
        before_epoch = None

        if start_time_after:
            after_epoch = self._parse_time(start_time_after)
        if start_time_before:
            before_epoch = self._parse_time(start_time_before)

        for build in builds:
            execute_time = build.get("execute_time")
            if not execute_time:
                continue

            build_epoch = self._parse_time(execute_time)
            if after_epoch and build_epoch < after_epoch:
                continue
            if before_epoch and build_epoch > before_epoch:
                continue
            filtered.append(build)

        return filtered

    def _parse_time(self, time_value):
        """Parse a time value to epoch seconds."""
        if isinstance(time_value, (int, float)):
            return float(time_value)
        if isinstance(time_value, str):
            # Try ISO 8601 format
            try:
                dt = datetime.fromisoformat(time_value.replace("Z", "+00:00"))
                return dt.timestamp()
            except ValueError:
                pass
            # Try epoch string
            try:
                return float(time_value)
            except ValueError:
                pass
        raise ValueError(f"Cannot parse time value: {time_value}")

    def get_build(self, build_uuid):
        """Get a single build by UUID."""
        url = self._build_url(f"builds/{build_uuid}")
        return self._request(url)

    def get_job(self, job_name):
        """Get job details."""
        url = self._build_url(f"jobs/{job_name}")
        return self._request(url)

    def get_projects(self):
        """List all projects."""
        url = self._build_url("projects")
        return self._request(url)

    def get_pipelines(self):
        """List all pipelines."""
        url = self._build_url("pipelines")
        return self._request(url)


def format_build(build, show_all=False):
    """Format a build dict for display."""
    lines = []
    lines.append(f"  UUID:       {build.get('uuid', 'N/A')}")
    lines.append(f"  Job:        {build.get('job_name', 'N/A')}")
    lines.append(f"  Result:     {build.get('result', 'N/A')}")
    lines.append(f"  Start:      {build.get('start_time', 'N/A')}")
    lines.append(f"  End:        {build.get('end_time', 'N/A')}")
    lines.append(f"  Duration:   {build.get('duration', 'N/A')}s")
    lines.append(f"  Log URL:    {build.get('log_url', 'N/A')}")

    if show_all:
        lines.append(f"  Execute:    {build.get('execute_time', 'N/A')}")
        lines.append(f"  Voting:     {build.get('voting', 'N/A')}")
        lines.append(f"  Held:       {build.get('held', 'N/A')}")
        lines.append(f"  Pipeline:   {build.get('pipeline', 'N/A')}")
        ref = build.get('ref', {})
        if ref:
            lines.append(f"  Branch:     {ref.get('ref', 'N/A')}")
            lines.append(f"  Change:     {ref.get('change', 'N/A')}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Query Zuul API for job executions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Get all TIMED_OUT builds for neutron-functional
  %(prog)s --job-name neutron-functional --result TIMED_OUT

  # Get last 50 successful builds for a specific branch
  %(prog)s --job-name neutron-check --branch stable/train --result SUCCESS

  # Get builds from a specific date range
  %(prog)s --job-name neutron-functional --start-time-after "2024-01-01" --start-time-before "2024-02-01"

  # Get builds for a specific change
  %(prog)s --job-name neutron-check --change 987654/1

  # Output as JSON
  %(prog)s --job-name neutron-functional --result FAILURE --json
        """
    )

    parser.add_argument("--zuul-base", default=DEFAULT_ZUUL_BASE,
                        help=f"Zuul base URL (default: {DEFAULT_ZUUL_BASE})")
    parser.add_argument("--tenant", default=DEFAULT_TENANT,
                        help=f"Zuul tenant (default: {DEFAULT_TENANT})")
    parser.add_argument("--job-name", dest="job_name",
                        help="Filter by job name")
    parser.add_argument("--result",
                        help="Filter by result (SUCCESS, FAILURE, UNSTABLE, "
                             "ABORTED, TIMED_OUT, etc.)")
    parser.add_argument("--branch",
                        help="Filter by branch (e.g., stable/train)")
    parser.add_argument("--pipeline",
                        help="Filter by pipeline (e.g., gate, check, post)")
    parser.add_argument("--project",
                        help="Filter by project (e.g., openstack/neutron)")
    parser.add_argument("--change",
                        help="Filter by change number (e.g., 123456/7)")
    parser.add_argument("--start-time-after", dest="start_time_after",
                        help="Filter builds started after this time "
                             "(ISO 8601 or epoch)")
    parser.add_argument("--start-time-before", dest="start_time_before",
                        help="Filter builds started before this time "
                             "(ISO 8601 or epoch)")
    parser.add_argument("--skip", type=int, default=0,
                        help="Number of results to skip (default: 0)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"Maximum number of results (default: {DEFAULT_LIMIT}, "
                             f"max: {MAX_LIMIT})")
    parser.add_argument("--json", dest="output_json", action="store_true",
                        help="Output results as JSON")
    parser.add_argument("--count", action="store_true",
                        help="Only print the total count of matching builds")
    parser.add_argument("--show-all", dest="show_all", action="store_true",
                        help="Show all build details")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose output")

    args = parser.parse_args()

    # Validate arguments
    if not any([args.job_name, args.result, args.branch, args.pipeline,
                args.project, args.change, args.start_time_after,
                args.start_time_before]):
        parser.error("At least one filter is required (--job-name, --result, "
                     "--branch, --pipeline, --project, --change, "
                     "--start-time-after, or --start-time-before)")

    if args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.limit > MAX_LIMIT:
        print(f"Warning: Limit capped at {MAX_LIMIT}", file=sys.stderr)
        args.limit = MAX_LIMIT

    # Create client and query
    client = ZuulClient(args.zuul_base, args.tenant)

    if args.verbose:
        print(f"Querying Zuul API: {args.zuul_base}/tenant/{args.tenant}",
              file=sys.stderr)
        filters = {
            k: v for k, v in {
                "job_name": args.job_name,
                "result": args.result,
                "branch": args.branch,
                "pipeline": args.pipeline,
                "project": args.project,
                "change": args.change,
                "start_time_after": args.start_time_after,
                "start_time_before": args.start_time_before,
            }.items() if v
        }
        print(f"Filters: {json.dumps(filters, indent=2)}", file=sys.stderr)

    try:
        builds = client.get_builds(
            job_name=args.job_name,
            result=args.result,
            branch=args.branch,
            pipeline=args.pipeline,
            project=args.project,
            change=args.change,
            start_time_after=args.start_time_after,
            start_time_before=args.start_time_before,
            skip=args.skip,
            limit=args.limit
        )
    except ZuulAPIError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Output results
    if args.count:
        print(len(builds))
    elif args.output_json:
        print(json.dumps(builds, indent=2, default=str))
    else:
        print(f"Found {len(builds)} build(s):\n")
        for i, build in enumerate(builds, 1):
            if i > 1:
                print("-" * 60)
            print(f"[{i}]")
            print(format_build(build, show_all=args.show_all))
        print()


if __name__ == "__main__":
    main()
