"""The program library: storage on disk, and the two dispatch strategies.

Storage is `library/<program-id>/program.yaml` plus a `history.jsonl` of status
changes, as `library/README.md` specifies. The digest `library_hash()` belongs
beside it because issue #4 requires every ledger row to record which frozen
library its episode ran against.

The ablation's two dispatch strategies meet here, as two functions at one seam.
`match_semantic` (arm 2) ranks admitted programs by how similar their text is to
the request; `match_preconditions` (arm 3) returns the admitted programs whose
executable preconditions accept the environment. The arms differ in which
function is called and nothing else, so which *similarity function* arm 2 uses is
chosen when a `Library` is constructed rather than inside either arm: lexical
today, an embedding model behind the same `Similarity` Protocol tomorrow.

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

import yaml

from .program import Program, ProgramStatus
from .runtime.probes import evaluate_preconditions
from .sandbox import Sandbox
from .signatures import TaskSignature
from .similarity import Similarity, lexical_similarity


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


def _canonical(program: Program) -> str:
    """One program's content as a stable string.

    `model_dump(mode="json")` rather than `model_dump_json` so enums become
    plain strings and the encoding cannot depend on the pydantic version's JSON
    defaults; `sort_keys` is what makes the digest independent of field order.
    """
    return json.dumps(program.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


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


class Library:
    """Programs on disk under `library/`, committed as a research artifact."""

    def __init__(self, root: Path, *, similarity: Similarity = lexical_similarity) -> None:
        """Open the library at `root`, with arm 2's similarity function injected.

        The injectable default is the seam the design requires: replacing lexical
        overlap with an embedding model is `Library(root, similarity=embed)`, and
        neither `match_semantic` nor the dispatcher that calls it changes. The
        parameter is keyword-only so the seam cannot be set by accident through
        the positional `root`.
        """
        self.root = root
        self.similarity = similarity

    def load_all(self) -> list[Program]:
        """Every stored program, sorted by id so the order is not filesystem luck."""
        if not self.root.exists():
            return []
        programs = [
            self._load(directory.name)
            for directory in sorted(self.root.iterdir())
            if directory.is_dir() and (directory / "program.yaml").is_file()
        ]
        programs.sort(key=lambda program: program.id)
        return programs

    def add(self, program: Program) -> None:
        """Write a newly compiled candidate. Refuses anything else.

        Admission sets the status after the positive and negative sides both
        pass, so a program arriving here already `admitted` would be claiming a
        gate result it never went through. A duplicate id is refused rather than
        overwritten: `library/README.md` says nothing is deleted, and replacing a
        program's history would be a deletion in all but name.
        """
        if program.status is not ProgramStatus.CANDIDATE:
            raise ValueError(
                f"add() takes a candidate, got {program.status.value!r}; admission sets "
                f"the status afterwards"
            )
        if not program.id or Path(program.id).name != program.id:
            raise ValueError(f"program id {program.id!r} is not a single path component")
        if (self.root / program.id / "program.yaml").exists():
            raise ValueError(f"program {program.id!r} already exists; nothing is overwritten")
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
        threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
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

        `threshold` is an **inclusive** floor, so a threshold of 0.0 admits a
        zero-overlap program and the caller can sweep down to "no floor".
        `limit` caps the result. Ties break by program id, so the order does not
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
        above = [item for item in scored if item.score >= threshold]
        above.sort(key=lambda item: (-item.score, item.program.id))
        return above[:limit]

    def match_preconditions(self, signature: TaskSignature, env: Sandbox) -> list[Program]:
        """Arm 3. Programs whose executable preconditions all accept `env`.

        Eligibility is `admitted` and nothing else. `library/README.md` rule 1
        makes dispatching a `candidate`, `demoted` or `quarantined` program a
        violation of a safety property this repository states, so a matcher that
        returned those as "candidates for later filtering" would depend on every
        caller remembering the rule. `[]` is the fallback path -- the caller
        records it as `EpisodeOutcome.FALLBACK`, not an error.

        Ordered most-specific-first by precondition count, with the id as a
        tie-break so equally specific programs come back in a stable order. A
        program with more preconditions has accepted a narrower state, so a
        general program cannot shadow a targeted one; ordering by the library's
        directory order would let it.

        `signature` is deliberately not consulted. Arm 3's identity is that the
        *environment* decides, not the request text: ranking by the intent would
        make it arm 2 under another name, and the ablation would compare two
        matchers that read the same signal. The parameter is kept because both
        arms are called at the same seam.
        """
        accepted = [
            program
            for program in self.load_all()
            if program.status is ProgramStatus.ADMITTED and evaluate_preconditions(program, env).ok
        ]
        accepted.sort(key=lambda program: (-len(program.preconditions), program.id))
        return accepted

    def _load(self, program_id: str) -> Program:
        path = self.root / program_id / "program.yaml"
        if not path.is_file():
            raise ValueError(f"no program {program_id!r} under {self.root}")
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        return Program.model_validate(document)

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
    ) -> None:
        entry = {
            "program_id": program_id,
            "from": from_status.value if from_status is not None else None,
            "to": to_status.value,
            "episode_id": episode_id,
        }
        with (self.root / program_id / "history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
