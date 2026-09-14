"""The program library: storage on disk, and the two dispatch strategies.

Storage is implemented here: `library/<program-id>/program.yaml` plus a
`history.jsonl` of status changes, as `library/README.md` specifies. The
digest `library_hash()` belongs beside it because issue #4 requires every ledger
row to record which frozen library its episode ran against.

Of the ablation's two dispatch strategies, `match_preconditions` (arm 3) is
implemented here; `match_semantic` (arm 2) remains a stub that raises, because
its representation and similarity threshold are a separate task. They are two
functions at one seam -- both take a `TaskSignature` and return programs -- so
the arms differ in which function is called and nothing else.

Admission is implemented in `agents.compile`, not here. This module's docstring
once implied otherwise; the safety gate reads a program's probes, runs it in a
throwaway sandbox, and would drag a replay runtime into what is otherwise pure
storage.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from .program import Program, ProgramStatus
from .runtime.probes import evaluate_preconditions
from .sandbox import Sandbox
from .signatures import TaskSignature


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


class Library:
    """Programs on disk under `library/`, committed as a research artifact."""

    def __init__(self, root: Path) -> None:
        self.root = root

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

    def match_semantic(self, signature, *, limit: int = 3) -> list[Program]:
        """Arm 2. Rank by embedding similarity of intent; no state awareness.

        Stub: arm 2's representation and similarity threshold are a separate
        task, deliberately not implemented beside `match_preconditions`, so the
        two matchers stay independently reviewable.
        """
        raise NotImplementedError("implemented per plan: phase 2")

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
