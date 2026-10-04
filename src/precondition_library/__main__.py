"""`python -m precondition_library dispatch --repo PATH --library DIR` (issue #181).

Reports which admitted program would fire on an existing checkout and why. It probes a
copy of the checkout and replays nothing.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .dispatch import dispatch_report, render


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m precondition_library")
    commands = parser.add_subparsers(dest="command", required=True)
    dispatch = commands.add_parser(
        "dispatch", help="report which compiled program would fire on a repository, and why"
    )
    dispatch.add_argument("--repo", type=Path, required=True, help="the checkout's top level")
    dispatch.add_argument(
        "--library", type=Path, required=True, help="a library root holding admitted programs"
    )
    dispatch.add_argument("--request", help="what you want done; recorded in the report")
    dispatch.add_argument(
        "--no-fetch", action="store_true", help="skip the pre-fetch of the upstream remote"
    )
    dispatch.add_argument("--json", action="store_true", help="print the report as JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = dispatch_report(args.library, args.repo, request=args.request, fetch=not args.no_fetch)
    print(report.model_dump_json(indent=2) if args.json else render(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
