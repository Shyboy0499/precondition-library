"""What a single task family member must provide.

A fault is only admissible if it satisfies three properties, because the
ablation depends on all three:

1. It recurs, so a program has something to amortize across.
2. Its correctness is checkable by git alone, with no LLM in the loop —
   otherwise scoring an episode costs exactly what the project is trying
   to avoid paying.
3. It is branchy. A fault solvable by one aliased command has a baseline cost
   of zero, so nothing can be saved on it and the episode is dead weight.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class GroundTruth:
    """The result of checking an environment, produced without any model."""

    ok: bool
    detail: str


class FaultSpec:
    """One member of the task family, injected deterministically."""

    name: str
    description: str
    change_surface: tuple[str, ...] = ()
    """The repo-relative paths a *resolution* of this fault may add, modify or delete.

    **Declared rather than derived from what the injector touched**, and the difference is
    the repairs that legitimately write a path the injection did not name: a generated file
    rewritten from its source is the ordinary case, and a derived surface would refuse it for
    being outside the fault. Declaring costs a fault the obligation to say, which is why the
    default is the *strictest* value.

    Empty means **committed content must not change at all**. That is right for
    `branch_renamed`: renaming a branch and re-pointing the tracking is a ref operation, so a
    resolution that commits anything did something the fault did not ask for. A fault that
    forgot to declare therefore fails its own gold resolution rather than passing on a
    permissive default.

    Checked by `tasks.invariants.recorded_state_intact` against the committed diff from the
    recorded base, so it shares the one fact that already covers the recorded refs.
    """

    def inject(self, seed: int, sandbox) -> None:
        """Mutate `sandbox` into the faulty state. Same seed, same state.

        **Must leave `upstream/main` resolvable** (issue #4, ADR-0018).
        `StateFingerprint.observe` reads the tracked ref, so a state that prunes or
        deletes it has no fingerprint, and a state with no fingerprint cannot be one of
        admission's negative sandboxes. A fault whose story is a missing upstream branch
        (as `branch_renamed`'s is) leaves the stale remote-tracking ref in place -- what a
        non-pruning fetch leaves -- and carries the change in another field.
        `tests/test_one_free_variable.py` builds every state admission builds and checks
        the ref resolves."""
        raise NotImplementedError("implemented per plan: phase 1")

    def task_text(self, seed: int) -> str:
        """The request handed to the agent, sampled from the intent's paraphrase
        distribution.

        Delegates to the intent so there is one source of truth per family. The
        distribution must not name the fault in most samples: when the text
        identifies the answer, the text *is* the label and a dispatch comparison
        becomes vacuous. How far that holds is measured, not assumed -- see
        bench/textcontrol.py.
        """
        raise NotImplementedError("implemented per plan: phase 1")

    def check(self, sandbox) -> GroundTruth:
        """Did the environment reach the expected state? Pure git. No model."""
        raise NotImplementedError("implemented per plan: phase 1")

    def variant_for_seed(self, seed: int) -> str | None:
        """Which declared resolution this fault's injector selects at `seed`, if any.

        Admission's same-intent negative class needs a seed whose injected state a
        resolution *other* than the program's own is correct in, and it must pick
        that seed without building a sandbox to observe: scanning seeds by building
        environments would be slow and would make the gate's cost depend on the
        search. A fault whose intent has two or more resolutions implements this
        from the same `sample_index` mapping its `inject` uses, so the seed a
        sibling is chosen from cannot disagree with the state that gets injected.

        A fault with no ambiguous intent has no sibling resolutions to expose and
        returns None; admission then builds no same-intent sandboxes for it.
        """
        return None

    def state_for_seed(self, seed: int) -> str | None:
        """Which injected state this fault's injector builds at `seed`, if it says.

        Finer than `variant_for_seed` where two states share a label: lockfile's
        `additions_only` and `upstream_removed` both resolve to `take_upstream`, but
        `keep_local` is acceptable in the first and wrong in the second. Admission
        enumerates states with this, so it builds both (the eighth live run admitted a
        `keep_local` program that fired on every `upstream_removed` eval state, because
        admission had built only `additions_only`). A fault that returns None is
        enumerated by its labels, as before.
        """
        return None

    def instance_for_seed(self, seed: int) -> str | None:
        """The instance identity this fault's injector builds at `seed`, if any.

        `variant_for_seed` answers *which resolution is correct*; this answers
        *which environment within that resolution* the seed builds -- the
        resolution plus the drawn Tier 1 axis values, as a stable string. The
        mismatch comparison's unit of analysis is the environment, so independence
        is keyed on this and not on the resolution (ADR-0005 decision 4): two seeds
        that select one resolution but draw different axis values are two
        independent environments, and only a genuine repeat of one instance is a
        replay.

        It must be a pure function of `seed` that shares its draw with `inject` --
        the `state_for_seed` pattern -- or `bench.splits` would label a row from a
        draw the environment was not built from. A fault with no ambiguous intent
        draws no instance and returns None. A fault that declares a resolution but
        returns None here is a programming error rather than a fallback:
        `occurrence_roles` refuses it rather than silently keying independence on
        the resolution, which is the defect ADR-0005 removes.
        """
        return None

    def axes_for_resolution(self, resolution: str) -> Mapping[str, tuple[str, ...]]:
        """Which axes a resolution may vary along, with each axis's value pool.

        ADR-0005 decision 2 requires the implementation to state this per fault and
        per resolution: an axis appears only when that resolution's `decided_by`
        predicate is invariant under it, and a state shape that cannot vary a safe
        axis declares none rather than pretending to. A fault with no drawn axes
        returns an empty mapping.
        """
        return {}

    def drawn_axes_for_seed(self, seed: int) -> Mapping[str, str]:
        """The value each declared axis takes at `seed`, by axis name.

        The read side of the declaration `axes_for_resolution` states: a test can
        check that every declared axis really varies over the seeds that select a
        resolution, and that the draw moves no axis the resolution did not declare.
        A fault with no drawn axes returns an empty mapping.
        """
        return {}
