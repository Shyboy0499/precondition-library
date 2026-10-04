"""Which compiled program would fire on an existing checkout, and why (issue #181, item 4).

The library has dispatched only inside harness sandboxes. This module dispatches it on a
real repository: it opens the checkout (`checkout.open_checkout`, with the trusted
pre-fetch), probes a **copy** of it (`checkout.snapshot`), because a probe that writes is
refused but not undone, and reports every admitted program with each precondition's
result. Nothing is replayed here; replaying is a separate, confirmed step.

**Arm 3's rule, unchanged.** The program that would fire is the first whose every
precondition holds, most specific first (`Library.match_preconditions`' order). Arm 3
reads only the environment, by design, so the request is recorded in the report and not
read by the decision.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from .checkout import open_checkout, snapshot
from .library import Library
from .program import Program, ProgramStatus
from .runtime.probes import evaluate_preconditions


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


def _report(program: Program, env) -> ProgramReport:
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


def dispatch_report(
    library_root: Path,
    work: Path,
    *,
    request: str | None = None,
    fetch: bool = True,
    scratch: Path | None = None,
) -> DispatchReport:
    """Probe every admitted program in `library_root` against a copy of `work`."""
    admitted = [p for p in Library(library_root).load_all() if p.status is ProgramStatus.ADMITTED]
    env = open_checkout(work, fetch=fetch, scratch=scratch)
    try:
        copy = snapshot(env)
        reports = [_report(program, copy) for program in admitted]
        parameters = dict(env.checkout.parameters) if env.checkout is not None else {}
    finally:
        env.destroy()
    by_id = {p.id: p for p in admitted}
    accepted = sorted(
        (r for r in reports if r.accepted),
        key=lambda r: (-len(by_id[r.id].preconditions), r.id),
    )
    rejected = sorted((r for r in reports if not r.accepted), key=lambda r: r.id)
    return DispatchReport(
        work=str(env.work),
        request=request,
        parameters=parameters,
        fires=accepted[0].id if accepted else None,
        programs=[*accepted, *rejected],
    )


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
