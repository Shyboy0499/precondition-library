"""`python -m precondition_library dispatch --repo PATH --library DIR [--replay]` (issue #181).

Reports which admitted program would fire on an existing checkout, and why, probing a
copy of it. With `--replay`, the program is dry-run on a second copy, the result is
shown, and it is replayed on the checkout only after you confirm (or with `--yes`).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

from .dispatch import DispatchReport, DryRun, render, render_dry_run, run_dispatch


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
    dispatch.add_argument("--json", action="store_true", help="print the outcome as JSON")
    dispatch.add_argument(
        "--replay",
        action="store_true",
        help="dry-run the program that would fire, then replay it on the repository if confirmed",
    )
    dispatch.add_argument(
        "--yes", action="store_true", help="with --replay, confirm without asking"
    )
    return parser


def _ask(answer: Callable[[str], str]) -> Callable[[DispatchReport, DryRun], bool]:
    def confirm(report: DispatchReport, dry: DryRun) -> bool:
        print(render(report), end="")
        print(render_dry_run(dry), end="")
        return answer(f"Replay {dry.program} on {report.work}? [y/N] ").strip().lower() in (
            "y",
            "yes",
        )

    return confirm


def main(argv: Sequence[str] | None = None, *, answer: Callable[[str], str] = input) -> int:
    args = _parser().parse_args(argv)
    if args.yes and not args.replay:
        raise SystemExit("--yes only applies with --replay")
    confirm = None
    if args.replay:
        confirm = (lambda report, dry: True) if args.yes else _ask(answer)
    outcome = run_dispatch(
        args.library, args.repo, request=args.request, fetch=not args.no_fetch, confirm=confirm
    )
    if args.json:
        print(outcome.model_dump_json(indent=2))
    elif not args.replay or args.yes or outcome.dry_run is None:
        print(render(outcome.report), end="")
        if outcome.dry_run is not None:
            print(render_dry_run(outcome.dry_run), end="")
    if outcome.replayed is not None:
        if not args.json:
            verdict = "succeeded" if outcome.replayed.ok else f"FAILED: {outcome.replayed.reason}"
            print(f"replayed {outcome.report.fires} on {outcome.report.work}: {verdict}")
        return 0 if outcome.replayed.ok else 1
    if args.replay and outcome.not_replayed and not args.json:
        print(f"not replayed: {outcome.not_replayed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
