"""Dispatch the library on an existing checkout: report, dry-run, then replay on confirmation.

The library has dispatched only inside harness sandboxes. This module dispatches it on a
real repository (issue #181), in three steps, each on a different copy of the truth:

1. **Report** -- open the checkout (`checkout.open_checkout`, with the trusted pre-fetch),
   probe a **copy** of it (`checkout.snapshot`), because a probe that writes is refused
   but not undone, and report every admitted program with each precondition's result.
2. **Dry run** -- replay the program that would fire on a **second, fresh copy**, and
   report what it changed there: the commits it made, the working tree's status, which
   parts of the repository moved, and whether its postconditions held. This is the dry
   run `runtime.guard.prepare_dry_run` describes -- git has none, so the body runs
   against a copy and the copy is diffed -- placed here because only this module can
   make a copy of a checkout.
3. **Replay** -- only when the caller confirms, and only if the checkout is still exactly
   as it was when the copies were taken, replay the program on the checkout itself.

**Arm 3's rule, unchanged.** The program that would fire is the first whose every
precondition holds, most specific first (`Library.match_preconditions`' order). Arm 3
reads only the environment, by design, so the request is recorded and not read.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from .checkout import open_checkout, snapshot
from .library import Library
from .program import Program, ProgramStatus
from .runtime.probes import evaluate_preconditions, sandbox_state
from .runtime.replay import ReplayResult, replay
from .sandbox import Sandbox, run_git

DRY_RUN_COPY = "dry-run"
"""The scratch directory the dry run replays in; distinct from the probing copy."""


class PredicateReport(BaseModel):
    name: str
    description: str
    held: bool
    refused: bool
    observed: str


class ProgramReport(BaseModel):
    id: str
    intent: str
    variant: str | None
    accepted: bool
    """Every precondition held, so arm 3 would accept this program here."""
    preconditions: list[PredicateReport]


class DispatchReport(BaseModel):
    work: str
    request: str | None
    """Recorded for the reader; arm 3 does not read it."""
    parameters: dict[str, str]
    fires: str | None
    """The program arm 3 would replay, or `None`: no program applies, so the agent falls back."""
    programs: list[ProgramReport]
    """Accepted programs first, in firing order, then the rest by id."""


class DryRun(BaseModel):
    """What replaying `program` did to a fresh copy of the checkout."""

    program: str
    ok: bool
    reason: str
    """The replay's own reason when it failed; empty when it succeeded."""
    head_before: str
    head_after: str
    commits: list[str]
    """`git log --oneline` of what the replay added to HEAD, newest first; empty when HEAD
    did not move forward (it may have moved elsewhere -- compare the two heads)."""
    status: str
    """`git status --short` after the replay: uncommitted changes it left."""
    changed: list[str]
    """Which parts of the repository changed (`runtime.probes.sandbox_state`'s parts)."""
    postconditions_held: bool | None
    """`None` when the body never ran (refused, or a parameter could not be bound)."""


class DispatchOutcome(BaseModel):
    report: DispatchReport
    dry_run: DryRun | None = None
    """Present when a program fired and a confirmation step was asked for."""
    replayed: ReplayResult | None = None
    """Present only when the caller confirmed and the replay ran on the checkout."""
    not_replayed: str | None = None
    """Why nothing ran on the checkout, when a confirmation step was asked for."""


Confirm = Callable[[DispatchReport, DryRun], bool]
"""Shown the report and the dry run; returns whether to replay on the checkout."""


def _admitted(library_root: Path) -> list[Program]:
    return [p for p in Library(library_root).load_all() if p.status is ProgramStatus.ADMITTED]


def _report(program: Program, env: Sandbox) -> ProgramReport:
    verdict = evaluate_preconditions(program, env)
    descriptions = {p.name: p.description for p in program.preconditions}
    return ProgramReport(
        id=program.id,
        intent=program.intent,
        variant=program.variant,
        accepted=verdict.ok,
        preconditions=[
            PredicateReport(
                name=result.name,
                description=descriptions.get(result.name, ""),
                held=result.ok,
                refused=result.refused,
                observed=result.observed,
            )
            for result in verdict.predicates
        ],
    )


def _dispatch(env: Sandbox, admitted: list[Program], request: str | None) -> DispatchReport:
    copy = snapshot(env)
    reports = [_report(program, copy) for program in admitted]
    by_id = {p.id: p for p in admitted}
    accepted = sorted(
        (r for r in reports if r.accepted),
        key=lambda r: (-len(by_id[r.id].preconditions), r.id),
    )
    rejected = sorted((r for r in reports if not r.accepted), key=lambda r: r.id)
    return DispatchReport(
        work=str(env.work),
        request=request,
        parameters=dict(env.checkout.parameters) if env.checkout is not None else {},
        fires=accepted[0].id if accepted else None,
        programs=[*accepted, *rejected],
    )


def _head(work: Path) -> str:
    return run_git(("rev-parse", "HEAD"), cwd=work).stdout.strip()


def _dry_run(env: Sandbox, program: Program) -> DryRun:
    copy = snapshot(env, DRY_RUN_COPY)
    before_state = sandbox_state(copy)
    head_before = _head(copy.work)
    result = replay(program, copy)
    head_after = _head(copy.work)
    after_state = sandbox_state(copy)
    commits = run_git(
        ("log", "--oneline", f"{head_before}..{head_after}"), cwd=copy.work, check=False
    ).stdout.splitlines()
    status = run_git(("status", "--short"), cwd=copy.work).stdout
    return DryRun(
        program=program.id,
        ok=result.ok,
        reason=result.reason,
        head_before=head_before,
        head_after=head_after,
        commits=commits,
        status=status,
        changed=[name for name in before_state if before_state[name] != after_state.get(name)],
        postconditions_held=None if result.postconditions is None else result.postconditions.ok,
    )


def run_dispatch(
    library_root: Path,
    work: Path,
    *,
    request: str | None = None,
    fetch: bool = True,
    scratch: Path | None = None,
    confirm: Confirm | None = None,
) -> DispatchOutcome:
    """Report on `work`; with `confirm`, dry-run the firing program and replay if confirmed.

    Without `confirm` this only reports, and nothing touches the checkout. With it, the
    program that would fire is dry-run on a fresh copy, `confirm` is shown the report and
    the dry run, and on `True` the program is replayed on the checkout -- unless the dry run
    failed, or the checkout changed after the copies were taken, in which case nothing runs
    and `not_replayed` says why.
    """
    admitted = _admitted(library_root)
    env = open_checkout(work, fetch=fetch, scratch=scratch)
    try:
        taken = sandbox_state(env)
        report = _dispatch(env, admitted, request)
        outcome = DispatchOutcome(report=report)
        if confirm is None:
            return outcome
        if report.fires is None:
            outcome.not_replayed = "no program's preconditions all hold here"
            return outcome
        program = next(p for p in admitted if p.id == report.fires)
        outcome.dry_run = _dry_run(env, program)
        if not outcome.dry_run.ok:
            outcome.not_replayed = f"the dry run failed: {outcome.dry_run.reason}"
            return outcome
        if not confirm(report, outcome.dry_run):
            outcome.not_replayed = "not confirmed"
            return outcome
        if sandbox_state(env) != taken:
            outcome.not_replayed = (
                "the repository changed after it was copied, so the dry run no longer "
                "describes it; run dispatch again"
            )
            return outcome
        outcome.replayed = replay(program, env)
        return outcome
    finally:
        env.destroy()


def dispatch_report(
    library_root: Path,
    work: Path,
    *,
    request: str | None = None,
    fetch: bool = True,
    scratch: Path | None = None,
) -> DispatchReport:
    """Probe every admitted program in `library_root` against a copy of `work`; no replay."""
    return run_dispatch(library_root, work, request=request, fetch=fetch, scratch=scratch).report


def render(report: DispatchReport) -> str:
    """The report as text a person reads before deciding whether to replay."""
    lines = [f"repository: {report.work}"]
    if report.request:
        lines.append(f"request: {report.request} (recorded; preconditions decide)")
    lines.append("bindings: " + ", ".join(f"{k}={v}" for k, v in sorted(report.parameters.items())))
    lines.append(
        f"would fire: {report.fires}"
        if report.fires
        else "would fire: nothing -- no program's preconditions all hold; the agent falls back"
    )
    for program in report.programs:
        mark = "ACCEPTS" if program.accepted else "refuses"
        lines.append("")
        lines.append(f"{program.id} [{program.variant or '-'}] {mark}")
        for pre in program.preconditions:
            state = "refused" if pre.refused else ("held" if pre.held else "failed")
            lines.append(f"  {state:7} {pre.name}: {pre.description} -- {pre.observed}")
    return "\n".join(lines) + "\n"


def render_dry_run(dry: DryRun) -> str:
    """What the dry run changed on its copy, for the person deciding whether to replay."""
    lines = [
        f"dry run of {dry.program} on a copy: {'succeeded' if dry.ok else 'FAILED'}"
        + (f" ({dry.reason})" if dry.reason else ""),
        f"  HEAD {dry.head_before[:12]} -> {dry.head_after[:12]}",
    ]
    lines += [f"  + {commit}" for commit in dry.commits]
    lines.append("  changed: " + (", ".join(dry.changed) if dry.changed else "nothing"))
    if dry.status.strip():
        lines.append("  left uncommitted:")
        lines += [f"    {line}" for line in dry.status.splitlines()]
    held = {None: "not run", True: "held", False: "FAILED"}[dry.postconditions_held]
    lines.append(f"  postconditions: {held}")
    return "\n".join(lines) + "\n"
