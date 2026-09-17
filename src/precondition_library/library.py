"""The program library: storage on disk, and the two dispatch strategies.

Storage is `library/<program-id>/program.yaml` plus a `history.jsonl` of status
changes, as `library/README.md` specifies. The digest `library_hash()` belongs
beside it because issue #4 requires every ledger row to record which frozen
library its episode ran against.

The ablation's two dispatch strategies meet here, as two functions at one seam.
`match_semantic` (arm 2) ranks admitted programs by how similar their text is to
the request; `match_preconditions` (arm 3) returns the admitted programs whose
executable preconditions accept the environment. The arms differ in which
function is called and nothing else, so **each arm's mechanism is injected at
construction rather than named in either matcher**: arm 2's `similarity` is
lexical today and an embedding model behind the same `Similarity` Protocol
tomorrow, and arm 3's predicate evaluator is passed as `evaluate_preconditions`.
That seam is also why this module does not import `runtime.probes`: naming the
probe runtime here is what made arm 2's text matcher depend on arm 3's machinery
and left the two mechanisms at different levels. The evaluator arrives from the
caller instead.

Admission is implemented in `agents.compile`, not here. This module's docstring
once implied otherwise; the safety gate reads a program's probes, runs it in a
throwaway sandbox, and would drag a replay runtime into what is otherwise pure
storage.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from .program import GroundTruthResult, Program, ProgramStatus
from .sandbox import Sandbox
from .signatures import TaskSignature
from .similarity import Similarity, lexical_similarity
from .tasks.intent import IntentSpec
from .tasks.registry import INTENTS


class _ProgramDumper(yaml.SafeDumper):
    """A YAML dumper that writes multi-line strings as literal blocks.

    A program body is the most-read part of the committed artifact, and the
    default emitter folds it into a single quoted line that a diff cannot show
    line by line. Bodies containing a tab or a trailing space cannot use the
    literal style, so those fall back to the default quoting rather than
    producing YAML that will not parse back.
    """


def _represent_str(dumper: _ProgramDumper, data: str) -> yaml.nodes.ScalarNode:
    block_safe = (
        "\n" in data
        and "\t" not in data
        and all(not line.endswith(" ") for line in data.split("\n"))
    )
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|" if block_safe else None)


_ProgramDumper.add_representer(str, _represent_str)

# Which statuses each status may move to. Anything absent is refused, so a
# `quarantined` program is terminal and a `demoted` one cannot be talked back
# into `admitted`: the library's history is evidence, and a status that could
# silently reverse would erase it.
_TRANSITIONS: dict[ProgramStatus, frozenset[ProgramStatus]] = {
    ProgramStatus.CANDIDATE: frozenset({ProgramStatus.ADMITTED, ProgramStatus.QUARANTINED}),
    ProgramStatus.ADMITTED: frozenset({ProgramStatus.DEMOTED, ProgramStatus.QUARANTINED}),
    ProgramStatus.DEMOTED: frozenset({ProgramStatus.QUARANTINED}),
    ProgramStatus.QUARANTINED: frozenset(),
}

MISMATCHES_BEFORE_QUARANTINE = 2
"""How many wrong fires withdraw a program from dispatch (spec §8).

A single mismatch on a state whose postconditions fail already demotes the
program, which withdraws it because both matchers return only `admitted`
programs. This threshold covers the other, quieter failure: a program that fires
the wrong resolution *and still satisfies its postconditions* -- `rebase` on a
state that requires `merge` reaches a synced tree -- so it is never demoted and
would otherwise mis-fire forever. The count is recorded in the program's
`history.jsonl`, so the withdrawal names both episodes that caused it.
"""


def _canonical(program: Program) -> str:
    """One program's content as a stable string.

    `model_dump(mode="json")` rather than `model_dump_json` so enums become
    plain strings and the encoding cannot depend on the pydantic version's JSON
    defaults; `sort_keys` is what makes the digest independent of field order.
    """
    return json.dumps(program.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _intent_for_fault(fault_name: str) -> IntentSpec | None:
    """The registered intent a fault's states are served by, else None.

    The registry is the one place that decides which intents are ambiguous and
    which fault each belongs to, so the load-time check reads it rather than
    re-deriving the mapping -- the same source `admit` validates against.
    """
    return next((intent for intent in INTENTS.values() if intent.fault == fault_name), None)


def _undeclared_variant_reason(program: Program) -> str | None:
    """Why `program` cannot be scored, or None when its variant is declared.

    The declared set comes from `Provenance.fault`, not from `intent`: a compiled
    program's intent is prose that matches no registry key, so keying on it
    protected only the hand-written artifacts and missed the programs the check
    exists for (issue #69). The registry is the one place that decides which
    intents are ambiguous, so this reads it rather than re-deriving the list --
    the same source `admit` validates against. A fault with no registered
    ambiguous intent has no declared set to violate, so it is not checked at all;
    that is not the same as an empty set, which would reject every program.

    One definition for both the in-memory verdict `load_all` applies and the
    durable record `quarantine_undeclared` writes, so the two cannot disagree
    about which programs are withdrawn or why.
    """
    fault = program.provenance.fault
    intent = _intent_for_fault(fault)
    if intent is None or not intent.is_ambiguous:
        return None
    declared = sorted(variant.id for variant in intent.variants)
    if program.variant in declared:
        return None
    return (
        f"quarantined on load (issues #66, #69): fault {fault!r} is served by ambiguous "
        f"intent {intent.name!r}, which declares variant id(s) {declared}, but the stored "
        f"program declares {program.variant!r}; admission rejects this shape because a fire "
        f"would be recorded as nothing fired"
    )


DEFAULT_SIMILARITY_THRESHOLD = 0.1
"""Arm 2's default similarity floor.

A parameter with a default rather than a value baked into the matcher, because
the pre-registration requires arm 2's threshold to be tuned on the held-out tune
seed set and the chosen value recorded per episode (`dispatch_score`). This
default is a placeholder for a caller that has not tuned: a non-zero floor so an
untuned arm cannot dispatch on a zero-overlap score. It is not a measured
optimum and carries no result; the comparison runs on the tune-set value.
"""


@dataclass(frozen=True)
class ScoredProgram:
    """A dispatched program and the similarity that selected it.

    The ledger has a `dispatch_score` field for arm 2, and returning the score
    beside the program is what lets the episode runner record it without
    re-running the ranking: a second scoring pass could disagree with the one
    that actually chose the program, and the recorded number would then describe
    a decision that was not made. Arm 3 returns bare programs because the spec
    defines `dispatch_score` as `None` for every arm but this one.
    """

    program: Program
    score: float


def _program_text(program: Program) -> str:
    """The text arm 2 compares a request against: a program's stated purpose.

    Its `intent` and the descriptions of its pre- and postconditions -- the
    English the library presents. The executable strings (`probe`, `body`) are
    excluded because they are shell syntax, not meaning, and including them would
    make part of the score a comparison of implementation style. `variant` is
    excluded because it is the resolution's *label*: letting a program be found
    by the name of the answer would put on the program side the very leak
    `test_no_phrasing_names_a_resolution` forbids on the request side.
    """
    descriptions = [
        predicate.description for predicate in [*program.preconditions, *program.postconditions]
    ]
    return " ".join([program.intent, *descriptions])


def _query_text(signature: TaskSignature) -> str:
    """The request arm 2 matches with: the intent plus the state as text.

    Issue #4 requires arm 2 to receive the state, not just the request, so a
    comparison against arm 3 measures the dispatch mechanism rather than a
    difference in what each arm was shown. The fingerprint contributes only its
    rendered words (`StateFingerprint.as_text`); arm 2 still cannot evaluate
    them, which is the blindness the primary metric exists to see.
    """
    return f"{signature.intent}\n{signature.fingerprint.as_text()}"


class PreconditionEvaluator(Protocol):
    """Arm 3's mechanism: does `program`'s preconditions hold on `env`?

    The callable the harness injects is `runtime.probes.evaluate_preconditions`,
    which runs the program's probes and returns a `GroundTruthResult` naming every
    predicate's verdict. A Protocol rather than an imported function because the
    runtime must not be named here (see the module docstring); a plain callable
    satisfies it structurally, as `lexical_similarity` satisfies `Similarity`.
    """

    def __call__(self, program: Program, env: Sandbox) -> GroundTruthResult: ...


class ProgramIdCollisionError(ValueError):
    """`add` was given an id the library already stores.

    A distinct type so a caller can record a *naming collision* as a collision
    rather than as a malformed reply or a gate rejection. It is a subclass of
    `ValueError` because the format is "refused for a reason", not a missing
    file, and every existing caller that catches `ValueError` keeps working.
    """

    def __init__(self, program_id: str) -> None:
        self.program_id = program_id
        super().__init__(f"program {program_id!r} already exists; nothing is overwritten")


class Library:
    """Programs on disk under `library/`, committed as a research artifact."""

    def __init__(
        self,
        root: Path,
        *,
        similarity: Similarity = lexical_similarity,
        threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        evaluate_preconditions: PreconditionEvaluator | None = None,
    ) -> None:
        """Open the library at `root`, with arm 2's and arm 3's mechanisms injected.

        The injectable defaults are the seams the design requires. Replacing
        lexical overlap with an embedding model is `Library(root,
        similarity=embed)`, and passing the harness's predicate evaluator is
        `Library(root, evaluate_preconditions=evaluate_preconditions)`; neither
        `match_semantic` nor `match_preconditions`, and neither dispatcher, has to
        change. The parameters are keyword-only so a seam cannot be set by
        accident through the positional `root`.

        `evaluate_preconditions` has **no imported default on purpose.** The only
        default would be `runtime.probes.evaluate_preconditions`, and importing it
        is exactly the dependency this seam removes: with it, this module named
        the probe runtime directly, so arm 2's text matcher could not be used
        without arm 3's machinery and the two mechanisms sat at different levels.
        A library used only for storage or for arm 2 may leave it unset;
        `match_preconditions` refuses to run without one rather than silently
        importing it back.

        `threshold` lives here rather than on `match_semantic` so the tune pass
        (#5) configures arm 2 once, at construction, and `dispatch_semantic` stays
        a one-line delegation with no tunable of its own. A per-call parameter
        would let a caller run the arm at a value the harness never recorded;
        `bench/run.py` reads this attribute and writes it on every ledger row, so
        a tuned run is distinguishable from an untuned one.
        """
        self.root = root
        self.similarity = similarity
        self.threshold = threshold
        self.evaluate_preconditions = evaluate_preconditions

    def load_all(self) -> list[Program]:
        """Every stored program, sorted by id so the order is not filesystem luck.

        Loading re-checks the variant invariant admission enforces, so a
        `program.yaml` written straight to disk cannot enter the dispatchable
        set by bypassing `admit` (see `_reject_undeclared_variant`). An offending
        program is returned `quarantined` rather than dropped or allowed to break
        the load, so the caller sees it and the rest of the library still reads.

        **This is a read.** The quarantine is applied in memory and nothing is
        written, because `library_hash` loads every program and a write here would
        change the digest of the library being hashed (the concern left open by
        PR #68), and because a read-only library directory must still read. The
        verdict is durable only once `quarantine_undeclared` records it; until
        then the on-disk `program.yaml` still carries the status the check has
        withdrawn, and both matchers already ignore the program in memory.
        """
        programs = [self._load(directory.name) for directory in self._program_directories()]
        programs.sort(key=lambda program: program.id)
        return programs

    def quarantine_undeclared(self) -> list[str]:
        """Persist the load-time variant quarantine and name the programs moved.

        The explicit write half of `load_all`'s read: each program whose file
        still carries a status the variant check withdraws is written back as
        `quarantined`, with the reason appended to its `history.jsonl`. Without
        this call the artifact would keep claiming a dispatchable status that both
        matchers have already stopped honouring, which is the objection PR #68
        raised against filtering at the point of use. Idempotent: a program whose
        file already says `quarantined` is left alone.
        """
        settled: list[str] = []
        for directory in self._program_directories():
            stored = self._read(directory.name)
            reason = _undeclared_variant_reason(stored)
            if reason is None or stored.status is ProgramStatus.QUARANTINED:
                continue
            self._write(stored.model_copy(update={"status": ProgramStatus.QUARANTINED}))
            self._append_history(
                stored.id,
                from_status=stored.status,
                to_status=ProgramStatus.QUARANTINED,
                episode_id=None,
                reason=reason,
            )
            settled.append(stored.id)
        return settled

    def add(self, program: Program) -> None:
        """Write a newly compiled candidate. Refuses anything else.

        Admission sets the status after the positive and negative sides both
        pass, so a program arriving here already `admitted` would be claiming a
        gate result it never went through. A duplicate id raises
        `ProgramIdCollisionError` rather than being overwritten: `library/README.md`
        says nothing is deleted, and replacing a program's history would be a
        deletion in all but name. The dedicated type lets a caller record the
        collision as a naming collision rather than as a malformed reply (issue
        #80).
        """
        if program.status is not ProgramStatus.CANDIDATE:
            raise ValueError(
                f"add() takes a candidate, got {program.status.value!r}; admission sets "
                f"the status afterwards"
            )
        if not program.id or Path(program.id).name != program.id:
            raise ValueError(f"program id {program.id!r} is not a single path component")
        if (self.root / program.id / "program.yaml").exists():
            raise ProgramIdCollisionError(program.id)
        (self.root / program.id).mkdir(parents=True)
        self._write(program)
        self._append_history(
            program.id,
            from_status=None,
            to_status=program.status,
            episode_id=program.provenance.episode_id,
        )

    def set_status(
        self,
        program_id: str,
        status: ProgramStatus,
        *,
        episode_id: str | None = None,
    ) -> None:
        """Move a stored program to `status`, recording the change in its history.

        `episode_id` names the episode that caused the change, which
        `library/README.md` wants in `history.jsonl`. It is optional only because
        a caller that has no episode (a manual quarantine, a test) still has a
        legitimate transition to record; the future episode runner passes it.

        An unknown id raises rather than creating a program: this is storage for
        compiled artifacts, not a directory allocator. A transition the table
        does not allow raises too, because a silently reversible status would
        destroy the mismatch evidence the library exists to keep.
        """
        program = self._load(program_id)
        if status is program.status:
            return
        allowed = _TRANSITIONS[program.status]
        if status not in allowed:
            raise ValueError(
                f"cannot move program {program_id!r} from {program.status.value!r} to "
                f"{status.value!r}; allowed: {sorted(item.value for item in allowed) or 'nothing'}"
            )
        self._write(program.model_copy(update={"status": status}))
        self._append_history(
            program_id, from_status=program.status, to_status=status, episode_id=episode_id
        )

    def record_mismatch(self, program_id: str, *, episode_id: str | None = None) -> ProgramStatus:
        """Count one wrong fire against a stored program; withdraw it at the cap.

        Spec §8 says a program that mismatches twice is withdrawn from dispatch
        and retained for analysis. The event is appended to the program's
        `history.jsonl` -- the record the library already keeps, so the count is
        durable and both causing episodes are named -- and once it reaches
        `MISMATCHES_BEFORE_QUARANTINE` the program is moved to `quarantined`.
        That transition is in `_TRANSITIONS` from `admitted` and `demoted`; a
        program already quarantined is terminal and is left alone.

        A program that returns a non-quarantined status has only been counted,
        not withdrawn. The runner is the only caller: the ledger's `misfired` is
        derived after the arm stops, so this cannot be decided inside dispatch.
        """
        program = self._load(program_id)
        count = self.mismatch_count(program_id) + 1
        self._append_mismatch_event(program_id, episode_id=episode_id, count=count)
        if count >= MISMATCHES_BEFORE_QUARANTINE and (
            ProgramStatus.QUARANTINED in _TRANSITIONS[program.status]
        ):
            self.set_status(program_id, ProgramStatus.QUARANTINED, episode_id=episode_id)
            return ProgramStatus.QUARANTINED
        return program.status

    def mismatch_count(self, program_id: str) -> int:
        """How many wrong fires `history.jsonl` records for `program_id`.

        Read from the log rather than held in memory, so the count survives a
        process boundary and a reader can reconstruct why a program was
        withdrawn. A missing history file is zero, not an error: a program that
        has never fired has no mismatches.
        """
        history = self.root / program_id / "history.jsonl"
        if not history.is_file():
            return 0
        count = 0
        for line in history.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("event") == "mismatch":
                count += 1
        return count

    def library_hash(self) -> str:
        """A stable sha256 over every stored program's content.

        Issue #4's confound is that arms which admit differently are not
        comparable, so each ledger row records this digest and a reader can see
        that every arm ran against one frozen library rather than an arm-specific
        one. The digest covers each program's canonical content, including its
        id and status, and is taken in sorted id order so it does not depend on
        filesystem order.
        """
        digest = hashlib.sha256()
        for program in self.load_all():
            digest.update(program.id.encode("utf-8"))
            digest.update(b"\0")
            digest.update(_canonical(program).encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()

    def match_semantic(
        self,
        signature: TaskSignature,
        *,
        limit: int = 3,
    ) -> list[ScoredProgram]:
        """Arm 2. Admitted programs ranked by text similarity to the request.

        The query is the signature's intent plus its fingerprint rendered as text
        (`_query_text`), so both arms receive the same representation. The score
        is whatever `self.similarity` computes -- lexical overlap by default, an
        embedding model behind the same Protocol later -- and this method names
        no mechanism of its own, so swapping the seam does not touch the arm.

        Eligibility is `admitted` and nothing else, for the same reason
        `match_preconditions` enforces it: `library/README.md` rule 1 makes
        dispatching a `candidate`, `demoted` or `quarantined` program a violation
        of a safety property this repository states, and arm 2 must not be the arm
        that quietly breaks it.

        `self.threshold` is an **inclusive** floor, so a threshold of 0.0 admits a
        zero-overlap program and the caller can sweep down to "no floor". It is set
        at construction (see `__init__`), not passed here, so the value that ran is
        the value the harness recorded. `limit` caps the result. Ties break by
        program id, so the order does not
        depend on storage order. `[]` is the fallback path -- the caller records
        it as `EpisodeOutcome.FALLBACK`, not an error.

        Arm 2's blindness lives here, not in its input: it sees the state only as
        words, so it cannot check whether a program's preconditions hold. A
        program whose probes would reject this environment is still returned when
        its text is close enough, and that mis-fire is exactly the phenomenon the
        primary metric counts. A test that made this matcher state-aware would be
        testing a different experiment.
        """
        query = _query_text(signature)
        scored = [
            ScoredProgram(program=program, score=self.similarity(query, _program_text(program)))
            for program in self.load_all()
            if program.status is ProgramStatus.ADMITTED
        ]
        above = [item for item in scored if item.score >= self.threshold]
        above.sort(key=lambda item: (-item.score, item.program.id))
        return above[:limit]

    def match_preconditions(self, env: Sandbox) -> list[Program]:
        """Arm 3. Programs whose executable preconditions all accept `env`.

        The predicate evaluator is `self.evaluate_preconditions`, injected at
        construction like arm 2's `similarity`; this method names no mechanism of
        its own, so replacing the evaluator does not touch the arm. That also
        means this module never imports the probe runtime (see the module
        docstring). Arm 3 takes only the environment, deliberately: its identity
        is that the *environment* decides, not the request text, and a `signature`
        parameter would invite a later change to rank by intent -- making it arm 2
        under another name and comparing two matchers that read the same signal.
        The parameter is gone rather than merely unused.

        Eligibility is `admitted` and nothing else. `library/README.md` rule 1
        makes dispatching a `candidate`, `demoted` or `quarantined` program a
        violation of a safety property this repository states, so a matcher that
        returned those as "candidates for later filtering" would depend on every
        caller remembering the rule. `[]` is the fallback path -- the caller
        records it as `EpisodeOutcome.FALLBACK`, not an error. Both matchers share
        this one `load_all` and this one eligibility filter, which is what keeps
        the two arms' *selection* the only thing that differs.

        Ordered most-specific-first by precondition count, with the id as a
        tie-break so equally specific programs come back in a stable order. A
        program with more preconditions has accepted a narrower state, so a
        general program cannot shadow a targeted one; ordering by the library's
        directory order would let it.
        """
        if self.evaluate_preconditions is None:
            raise ValueError(
                "arm 3's matcher needs a predicate evaluator; construct the library as "
                "Library(root, evaluate_preconditions=...) -- importing one here would "
                "put the probe runtime back into the storage layer and re-hide the seam"
            )
        accepted = [
            program
            for program in self.load_all()
            if program.status is ProgramStatus.ADMITTED
            and self.evaluate_preconditions(program, env).ok
        ]
        accepted.sort(key=lambda program: (-len(program.preconditions), program.id))
        return accepted

    def _program_directories(self) -> list[Path]:
        """Every directory under the root that holds a `program.yaml`, sorted.

        Sorted so neither the load order nor the order `quarantine_undeclared`
        writes depends on filesystem luck.
        """
        if not self.root.exists():
            return []
        return sorted(
            directory
            for directory in self.root.iterdir()
            if directory.is_dir() and (directory / "program.yaml").is_file()
        )

    def _read(self, program_id: str) -> Program:
        """The stored program exactly as its file holds it: no check, no write."""
        path = self.root / program_id / "program.yaml"
        if not path.is_file():
            raise ValueError(f"no program {program_id!r} under {self.root}")
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        return Program.model_validate(document)

    def _load(self, program_id: str) -> Program:
        """One program with the load-time variant check applied, in memory."""
        return self._reject_undeclared_variant(self._read(program_id))

    def _reject_undeclared_variant(self, program: Program) -> Program:
        """Withdraw a stored program whose variant cannot be scored, in memory.

        `admit` refuses a program whose `variant` is not one of its fault's
        ambiguous intent's declared ids, because `EpisodeRecord.misfired` is
        `fired_variant is not None and fired_variant != correct_variant`: a
        program firing with `variant: None` records as "nothing fired" and
        quietly deflates the mismatch numerator, and a mislabelled one is scored
        against the wrong resolution. A `program.yaml` written straight to disk
        -- by hand, by a future compile path, or by anything bypassing `admit` --
        has not been through that gate, so the check is repeated here rather than
        trusted (issue #66).

        The check keys on `Provenance.fault`, not on `intent`. `intent` is free
        text -- a compiled program's is prose, as the compile prompt asks -- so
        keying on it protected only the hand-written artifacts whose intent
        happened to be a registry key, and missed exactly the programs the check
        was written for (issue #69). A program whose fault has no registered
        ambiguous intent has no declared set to violate and is left as it is;
        admission still governs its status.

        The verdict is `quarantined`, the lifecycle's existing "withdrawn from
        dispatch, retained for analysis": the program stays for analysis and the
        admitted-only filter in both matchers keeps it out of dispatch. It is
        applied in memory only -- this is a read, and `quarantine_undeclared` is
        the explicit write that says so durably. The check is per program, so one
        offending file is withdrawn while every other program still loads.
        """
        reason = _undeclared_variant_reason(program)
        if reason is None or program.status is ProgramStatus.QUARANTINED:
            return program
        return program.model_copy(update={"status": ProgramStatus.QUARANTINED})

    def _write(self, program: Program) -> None:
        data = program.model_dump(mode="json")
        text = yaml.dump(
            data,
            Dumper=_ProgramDumper,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
        )
        (self.root / program.id / "program.yaml").write_text(text, encoding="utf-8")

    def _append_history(
        self,
        program_id: str,
        *,
        from_status: ProgramStatus | None,
        to_status: ProgramStatus,
        episode_id: str | None,
        reason: str | None = None,
    ) -> None:
        entry = {
            "program_id": program_id,
            "from": from_status.value if from_status is not None else None,
            "to": to_status.value,
            "episode_id": episode_id,
        }
        if reason is not None:
            # Only transitions with no episode to carry the cause need the text;
            # emitting the key unconditionally would change the shape of every
            # existing entry for no reader's benefit.
            entry["reason"] = reason
        with (self.root / program_id / "history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")

    def _append_mismatch_event(
        self, program_id: str, *, episode_id: str | None, count: int
    ) -> None:
        """Record one wrong fire in the program's history, without a status move.

        A separate entry shape from `_append_history` because it is not a
        transition: the program stays `admitted` until the cap is reached, and
        writing a `from == to` status change would make a non-event look like a
        lifecycle step. `event: mismatch` is what `mismatch_count` counts, so the
        two cannot drift.
        """
        entry = {
            "program_id": program_id,
            "event": "mismatch",
            "episode_id": episode_id,
            "count": count,
        }
        with (self.root / program_id / "history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
