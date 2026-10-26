"""A control that reads the state and decides, without compiled preconditions (#295).

Figure 1 compares two dispatchers: arm 3 runs each compiled program's executable preconditions,
and arm 2 scores text similarity against a state it cannot evaluate. But a state's correct
resolution is *defined* as a rule over the observed `StateFingerprint` -- each intent's
`decided_by` -- so any dispatcher that recovers that rule from the state wins, executable or not.
This module is that dispatcher, with no model call and no compiled program:

* **Features.** Every fingerprint field as a scalar (a boolean, a count, a list's length), the
  size of every pair of list fields' overlap, and whether every pair of string fields is equal.
  Generic relations, not any intent's rule: the tree has to find the rule.
* **Training.** The states the build was learned from -- each measured fault's admit seeds
  (`bench.admit_set`), with the fault-free state at each -- labelled by the intents' own rules,
  the label source admission is validated against. One decision tree per intent, default
  hyper-parameters, `random_state=0`.
* **Scoring.** The eval pairs, built and labelled exactly as `bench.library_pairs` builds
  Figure 1's, and graded by `bench.coverage`. A tree fires its predicted resolution, with the
  leaf's class probability as its score, and abstains where it predicts none.

It needs no library, so one result stands beside all three replicates. If it matches arm 3, the
gap Figure 1 shows is reading the state against not reading it, not executable checks against
similarity.
"""

from __future__ import annotations

import argparse
import itertools
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from ..signatures import StateFingerprint
from ..tasks.faults import build_sandbox
from ..tasks.intent import IntentSpec
from .admit_set import admit_seeds
from .coverage import OperatingPoint, PairOutcome, operating_point, sweep
from .heldout import HELD_OUT_FAULTS
from .library_pairs import FAULT_FREE, _measured_intents, is_pair
from .pairs import LabelledPair, label
from .splits import EVAL_SEEDS, HELD_OUT_SEEDS

NONE = "(none)"
"""The class a tree predicts where the intent's rule labels no resolution."""

_LIST_FIELDS = tuple(
    name
    for name, field in StateFingerprint.model_fields.items()
    if str(field.annotation).startswith("list")
)
_STRING_FIELDS = tuple(
    name for name, field in StateFingerprint.model_fields.items() if field.annotation is str
)


def features(state: StateFingerprint) -> dict[str, float]:
    """Generic numeric features of one observed state, the same for every intent."""
    out: dict[str, float] = {}
    for name in StateFingerprint.model_fields:
        value = getattr(state, name)
        if isinstance(value, bool):
            out[name] = float(value)
        elif isinstance(value, int):
            out[name] = float(value)
        elif isinstance(value, list):
            out[f"len({name})"] = float(len(value))
    for left, right in itertools.combinations(_LIST_FIELDS, 2):
        out[f"|{left} & {right}|"] = float(
            len(set(getattr(state, left)) & set(getattr(state, right)))
        )
    for left, right in itertools.combinations(_STRING_FIELDS, 2):
        out[f"{left} == {right}"] = float(getattr(state, left) == getattr(state, right))
    return out


def _states(
    faults: Sequence[str], seeds_of: dict[str, Sequence[int]]
) -> list[tuple[str, int, StateFingerprint]]:
    """Each (environment, seed, observed state) the given seeds build, fault-free included."""
    built: list[tuple[str, int, StateFingerprint]] = []
    for fault in faults:
        for seed in seeds_of[fault]:
            for environment, injected in ((FAULT_FREE, []), (fault, [fault])):
                box = build_sandbox(seed, injected)
                try:
                    built.append((environment, seed, StateFingerprint.observe(box)))
                finally:
                    box.destroy()
    return built


class StateClassifier:
    """One decision tree per intent, over `features`, fit on rule-labelled states."""

    def __init__(self, intents: Sequence[IntentSpec]) -> None:
        self.intents = list(intents)
        self._trees: dict[str, object] = {}
        self._vectoriser: object | None = None

    def fit(self, states: Sequence[StateFingerprint]) -> StateClassifier:
        from sklearn.feature_extraction import DictVectorizer
        from sklearn.tree import DecisionTreeClassifier

        vectoriser = DictVectorizer(sparse=False)
        matrix = vectoriser.fit_transform([features(state) for state in states])
        for intent in self.intents:
            labels = []
            for state in states:
                variant = intent.correct_variant(state)
                labels.append(variant.id if variant is not None else NONE)
            self._trees[intent.name] = DecisionTreeClassifier(random_state=0).fit(matrix, labels)
        self._vectoriser = vectoriser
        return self

    def decide(self, intent: IntentSpec, state: StateFingerprint) -> tuple[str | None, float]:
        """The resolution this intent's tree fires on `state`, or None, with its probability."""
        assert self._vectoriser is not None, "fit first"
        row = self._vectoriser.transform([features(state)])  # type: ignore[attr-defined]
        tree = self._trees[intent.name]
        probabilities = tree.predict_proba(row)[0]  # type: ignore[attr-defined]
        best = int(probabilities.argmax())
        predicted = str(tree.classes_[best])  # type: ignore[attr-defined]
        return (None if predicted == NONE else predicted), float(probabilities[best])


class ClassifierReport(BaseModel):
    block: str
    training_states: int
    pairs: int
    at_every_fire: OperatingPoint
    curve: list[OperatingPoint]
    wrong_fires: list[dict[str, object]]


def outcomes(
    classifier: StateClassifier, faults: Sequence[str], seeds: Sequence[int]
) -> tuple[list[LabelledPair], list[PairOutcome]]:
    """Figure 1's pairs on `seeds`, and the classifier's decision on each."""
    intents = _measured_intents(faults)
    pairs: list[LabelledPair] = []
    decided: list[PairOutcome] = []
    for seed in seeds:
        for environment, injected in [(FAULT_FREE, []), *((f, [f]) for f in faults)]:
            box = build_sandbox(seed, injected)
            try:
                state = StateFingerprint.observe(box)
            finally:
                box.destroy()
            for intent in intents:
                pair = label(intent, seed, state, uninformed=True)
                if not is_pair(environment, intent, pair):
                    continue
                variant, score = classifier.decide(intent, state)
                pairs.append(pair)
                decided.append(
                    PairOutcome(
                        correct_variant=pair.correct_variant,
                        acceptable_variants=pair.acceptable_variants,
                        fired_variant=variant,
                        score=score if variant is not None else None,
                        informed=pair.informed,
                    )
                )
    return pairs, decided


def run(out: Path, *, faults: Sequence[str] = HELD_OUT_FAULTS) -> list[ClassifierReport]:
    if out.exists():
        raise ValueError(f"{out} already exists; the control writes a fresh directory")
    training = _states(faults, {fault: admit_seeds(fault) for fault in faults})
    classifier = StateClassifier(_measured_intents(faults)).fit([s for _, _, s in training])
    reports = []
    for block, seeds in (("eval", EVAL_SEEDS), ("held-out", HELD_OUT_SEEDS)):
        pairs, decided = outcomes(classifier, faults, seeds)
        wrong = [
            {
                "intent": pair.intent,
                "seed": pair.seed,
                "fired": outcome.fired_variant,
                "acceptable": list(pair.acceptable_variants),
            }
            for pair, outcome in zip(pairs, decided, strict=True)
            if outcome.fired_variant is not None
            and not outcome.fire_is_right(outcome.fired_variant)
        ]
        reports.append(
            ClassifierReport(
                block=block,
                training_states=len(training),
                pairs=len(pairs),
                at_every_fire=operating_point(decided),
                curve=sweep(decided),
                wrong_fires=wrong,
            )
        )
    out.mkdir(parents=True)
    for report in reports:
        (out / f"{report.block}.json").write_text(report.model_dump_json(indent=2) + "\n", "utf-8")
    (out / "summary.txt").write_text(text(reports), encoding="utf-8")
    return reports


def text(reports: Sequence[ClassifierReport]) -> str:
    lines = ["Fingerprint classifier control (#295): no model call, no compiled program"]
    for report in reports:
        point = report.at_every_fire
        lines.append(
            f"  {report.block}: {report.pairs} pairs, trained on {report.training_states} states; "
            f"fires {point.coverage.numerator}/{point.coverage.denominator}, wrong "
            f"{point.mismatch.numerator}/{point.mismatch.denominator}"
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m precondition_library.bench.state_classifier")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    print(text(run(args.out)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
