"""`python -m precondition_library dispatch|learn ...` -- the library on an existing repository.

* `dispatch --repo PATH --library DIR [--replay]` (issue #181) reports which admitted
  program would fire on the checkout, and why, probing a copy of it. With `--replay`, the
  program is dry-run on a second copy, the result is shown, and it is replayed on the
  checkout only after you confirm (or with `--yes`).
* `learn --repo PATH --library DIR --fault FAMILY --request TEXT` (issue #188, ADR-0026)
  has the agent solve a copy of the checkout, shows you what the solve did, and -- only
  if you confirm -- compiles it and admits it through the harness's gate into `DIR`. It
  calls a model, so it needs a key: name where it is with `--api-key-env NAME` or
  `--api-key-file PATH`; the key itself is never an argument.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

from .bench.live import read_api_key, read_api_key_env
from .dispatch import DispatchReport, DryRun, render, render_dry_run, run_dispatch
from .learn import SolveEffect, learn, render_effect
from .learn import render as render_learned
from .provider import DEFAULT_MODEL, DeepSeekProvider, Provider
from .tasks.registry import ambiguous_intents

MakeProvider = Callable[[str, str], Provider]
"""Builds the model provider from an API key and a model name."""


def _deepseek(api_key: str, model: str) -> Provider:
    return DeepSeekProvider(api_key=api_key, model=model)


def _common(command: argparse.ArgumentParser) -> None:
    command.add_argument("--repo", type=Path, required=True, help="the checkout's top level")
    command.add_argument(
        "--library", type=Path, required=True, help="a library root holding admitted programs"
    )
    command.add_argument(
        "--no-fetch", action="store_true", help="skip the pre-fetch of the upstream remote"
    )
    command.add_argument("--json", action="store_true", help="print the outcome as JSON")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m precondition_library")
    commands = parser.add_subparsers(dest="command", required=True)

    dispatch = commands.add_parser(
        "dispatch", help="report which compiled program would fire on a repository, and why"
    )
    _common(dispatch)
    dispatch.add_argument("--request", help="what you want done; recorded in the report")
    dispatch.add_argument(
        "--replay",
        action="store_true",
        help="dry-run the program that would fire, then replay it on the repository if confirmed",
    )
    dispatch.add_argument(
        "--yes", action="store_true", help="with --replay, confirm without asking"
    )

    learn_command = commands.add_parser(
        "learn", help="solve a copy of a repository, confirm, and learn a program from it"
    )
    _common(learn_command)
    learn_command.add_argument(
        "--fault",
        required=True,
        choices=sorted(intent.fault for intent in ambiguous_intents()),
        help="the family the chore belongs to; admission builds its sandboxes from it",
    )
    learn_command.add_argument("--request", required=True, help="what you want done")
    key = learn_command.add_mutually_exclusive_group(required=True)
    key.add_argument("--api-key-env", metavar="NAME", help="environment variable holding the key")
    key.add_argument("--api-key-file", type=Path, metavar="PATH", help="file holding the key")
    learn_command.add_argument("--model", default=DEFAULT_MODEL)
    learn_command.add_argument("--yes", action="store_true", help="accept the solve without asking")
    return parser


def _ask_replay(answer: Callable[[str], str]) -> Callable[[DispatchReport, DryRun], bool]:
    def confirm(report: DispatchReport, dry: DryRun) -> bool:
        print(render(report), end="")
        print(render_dry_run(dry), end="")
        return answer(f"Replay {dry.program} on {report.work}? [y/N] ").strip().lower() in (
            "y",
            "yes",
        )

    return confirm


def _ask_learn(answer: Callable[[str], str]) -> Callable[[SolveEffect], bool]:
    def confirm(effect: SolveEffect) -> bool:
        print(render_effect(effect), end="")
        reply = answer("Is this what you wanted, and should it be learned? [y/N] ")
        return reply.strip().lower() in ("y", "yes")

    return confirm


def _dispatch(args: argparse.Namespace, answer: Callable[[str], str]) -> int:
    if args.yes and not args.replay:
        raise SystemExit("--yes only applies with --replay")
    confirm = None
    if args.replay:
        confirm = (lambda report, dry: True) if args.yes else _ask_replay(answer)
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


def _learn(
    args: argparse.Namespace, answer: Callable[[str], str], make_provider: MakeProvider
) -> int:
    api_key = (
        read_api_key_env(args.api_key_env)
        if args.api_key_env is not None
        else read_api_key(args.api_key_file)
    )
    confirm = (lambda effect: True) if args.yes else _ask_learn(answer)
    outcome = learn(
        args.library,
        args.repo,
        request=args.request,
        fault=args.fault,
        provider=make_provider(api_key, args.model),
        confirm=confirm,
        fetch=not args.no_fetch,
    )
    print(outcome.model_dump_json(indent=2) if args.json else render_learned(outcome), end="")
    return 0 if outcome.admitted else 1


def main(
    argv: Sequence[str] | None = None,
    *,
    answer: Callable[[str], str] = input,
    make_provider: MakeProvider = _deepseek,
) -> int:
    args = _parser().parse_args(argv)
    if args.command == "learn":
        return _learn(args, answer, make_provider)
    return _dispatch(args, answer)


if __name__ == "__main__":
    raise SystemExit(main())
