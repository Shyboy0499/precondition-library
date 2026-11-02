"""A state reader that sees only what a library's probes see (#295, item 3).

`bench.state_classifier` showed that a decision tree over the whole `StateFingerprint` matches
arm 3 on Figure 1's pairs (ADR-0047). That tree reads facts arm 3's programs never look at. This
control is the fairer comparison: a tree per intent whose only features are the verdicts of the
library's own precondition probes on the state.

* **Features, per library.** Every distinct precondition among the library's admitted programs
  -- the same probe, expected exit and expected pattern count once -- run on the state, as 1 if it
  holds and 0 if not. These are exactly the facts arm 3 reads on that state.
* **Arm 3 from the same verdicts.** A program fires when all its preconditions hold, the most
  preconditions first and then the id (`Library.match_preconditions`). So arm 3 here is
  recomputed from the very verdicts the tree reads, and is checked against Figure 1's committed
  counts.
* **Training and scoring** are `state_classifier`'s: the build's admit seeds with the fault-free
  state at each, labelled by the intents' rules; one tree per intent with default
  hyper-parameters and `random_state=0`; Figure 1's eval pairs and the held-out pairs, graded by
  `bench.coverage`.

If the tree matches arm 3, executing the probes as a conjunction adds nothing over reading the
same facts any other way: the advantage is in which facts the probes observe. If the tree does
better, the conjunction is the weaker reader of its own evidence. Exploratory, like the
classifier it extends.

    python -m precondition_library.bench.probe_classifier --out results/probe-classifier-<date>
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from ..library import Library
from ..program import Predicate, Program, ProgramStatus
from ..runtime.probes import bindings, evaluate_predicate
from ..sandbox import Sandbox
from ..signatures import StateFingerprint
from ..tasks.faults import build_sandbox
from ..tasks.intent import IntentSpec
from .admit_set import admit_seeds
from .coverage import OperatingPoint, PairOutcome, operating_point
from .heldout import HELD_OUT_FAULTS
from .library_pairs import FAULT_FREE, _measured_intents, is_pair
from .pairs import LabelledPair, label
from .preregistration import REPOSITORY
from .real_merges import LIBRARIES
from .splits import EVAL_SEEDS, HELD_OUT_SEEDS
from .state_classifier import NONE

Verdicts = dict[str, bool]

LIBRARY_ROOTS = tuple(REPOSITORY / library for library in LIBRARIES)
"""The three committed libraries Figure 1 measures, one per replicate."""


def key(predicate: Predicate) -> str:
    """A precondition's identity: what it runs and what it expects, not its name."""
    return json.dumps([predicate.probe, predicate.expect_exit, predicate.expect_pattern])


class ProbeView:
    """One library's admitted programs and the distinct preconditions they run."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.programs: list[Program] = [
            p for p in Library(root).load_all() if p.status is ProgramStatus.ADMITTED
        ]
        self.predicates: dict[str, Predicate] = {}
        for program in self.programs:
            for predicate in program.preconditions:
                self.predicates.setdefault(key(predicate), predicate)

    def verdicts(self, box: Sandbox) -> Verdicts:
        parameters = bindings(box)
        return {
            k: evaluate_predicate(predicate, box, parameters).ok
            for k, predicate in sorted(self.predicates.items())
        }

    def arm3(self, verdicts: Verdicts) -> str | None:
        """`Library.match_preconditions`' first program's variant, from `verdicts` alone."""
        accepted = [
            program
            for program in self.programs
            if all(verdicts[key(predicate)] for predicate in program.preconditions)
        ]
        accepted.sort(key=lambda program: (-len(program.preconditions), program.id))
        return accepted[0].variant if accepted else None


class Observed(BaseModel):
    environment: str
    seed: int
    state: StateFingerprint
    verdicts: list[Verdicts]
    """Per library, in `LIBRARIES`' order."""


def observe(
    views: Sequence[ProbeView], cases: Sequence[tuple[str, int, list[str]]]
) -> list[Observed]:
    """Build each (environment, seed, injected faults) sandbox once, and read it every way."""
    found = []
    for environment, seed, injected in cases:
        box = build_sandbox(seed, injected)
        try:
            found.append(
                Observed(
                    environment=environment,
                    seed=seed,
                    state=StateFingerprint.observe(box),
                    verdicts=[view.verdicts(box) for view in views],
                )
            )
        finally:
            box.destroy()
    return found


class ProbeTrees:
    """One decision tree per intent over one library's precondition verdicts."""

    def __init__(self, intents: Sequence[IntentSpec], allowed: set[str] | None = None) -> None:
        """`allowed`: the variants the tree may fire. A training state whose correct variant is
        not among them is labelled "fire nothing", as no dispatcher can fire a resolution its
        library holds no program for. None allows every variant."""
        self.intents = list(intents)
        self.allowed = allowed
        self._trees: dict[str, object] = {}
        self._vectoriser: object | None = None

    def fit(self, rows: Sequence[tuple[Verdicts, StateFingerprint]]) -> ProbeTrees:
        from sklearn.feature_extraction import DictVectorizer
        from sklearn.tree import DecisionTreeClassifier

        vectoriser = DictVectorizer(sparse=False)
        matrix = vectoriser.fit_transform([_features(v) for v, _ in rows])
        for intent in self.intents:
            labels = []
            for _, state in rows:
                variant = intent.correct_variant(state)
                usable = variant is not None and (
                    self.allowed is None or variant.id in self.allowed
                )
                labels.append(variant.id if usable else NONE)  # type: ignore[union-attr]
            self._trees[intent.name] = DecisionTreeClassifier(random_state=0).fit(matrix, labels)
        self._vectoriser = vectoriser
        return self

    def decide(self, intent: IntentSpec, verdicts: Verdicts) -> tuple[str | None, float]:
        assert self._vectoriser is not None, "fit first"
        row = self._vectoriser.transform([_features(verdicts)])  # type: ignore[attr-defined]
        tree = self._trees[intent.name]
        probabilities = tree.predict_proba(row)[0]  # type: ignore[attr-defined]
        best = int(probabilities.argmax())
        predicted = str(tree.classes_[best])  # type: ignore[attr-defined]
        return (None if predicted == NONE else predicted), float(probabilities[best])

    def depths(self) -> dict[str, int]:
        return {name: int(tree.get_depth()) for name, tree in self._trees.items()}  # type: ignore[attr-defined]


def _features(verdicts: Verdicts) -> dict[str, float]:
    return {k: float(ok) for k, ok in verdicts.items()}


class Arms(BaseModel):
    tree: OperatingPoint
    """The tree that may fire only variants the library holds a program for: the comparison."""
    tree_unrestricted: OperatingPoint
    """The tree that may fire any variant the intents' rules label, as the fingerprint
    classifier does, programs or not."""
    arm3: OperatingPoint
    agree: int
    """Pairs on which the (restricted) tree and arm 3 make the same decision (both abstain, or
    fire the same variant)."""
    tree_wrong: list[dict[str, object]]
    tree_unrestricted_wrong: list[dict[str, object]]


class LibraryReport(BaseModel):
    library: str
    admitted_programs: int
    distinct_preconditions: int
    tree_depths: dict[str, int]
    blocks: dict[str, Arms]


class Report(BaseModel):
    training_states: int
    pairs: dict[str, int]
    libraries: list[LibraryReport]


def _outcome(pair: LabelledPair, variant: str | None, score: float | None) -> PairOutcome:
    return PairOutcome(
        correct_variant=pair.correct_variant,
        acceptable_variants=pair.acceptable_variants,
        fired_variant=variant,
        score=score if variant is not None else None,
        informed=pair.informed,
    )


def score(
    trees: ProbeTrees,
    unrestricted: ProbeTrees,
    view: ProbeView,
    r: int,
    intents: Sequence[IntentSpec],
    observed: Sequence[Observed],
) -> Arms:
    """Both trees and arm 3 on every pair of `observed`, from library `r`'s verdicts."""
    outcomes: dict[str, list[PairOutcome]] = {"tree": [], "unrestricted": [], "arm3": []}
    wrong: dict[str, list[dict[str, object]]] = {"tree": [], "unrestricted": []}
    agree = 0
    for seen in observed:
        verdicts = seen.verdicts[r]
        fired3 = view.arm3(verdicts)
        for intent in intents:
            pair = label(intent, seen.seed, seen.state, uninformed=True)
            if not is_pair(seen.environment, intent, pair):
                continue
            outcomes["arm3"].append(_outcome(pair, fired3, None))
            for name, chooser in (("tree", trees), ("unrestricted", unrestricted)):
                variant, probability = chooser.decide(intent, verdicts)
                outcome = _outcome(pair, variant, probability)
                outcomes[name].append(outcome)
                if name == "tree":
                    agree += variant == fired3
                if variant is not None and not outcome.fire_is_right(variant):
                    wrong[name].append(
                        {
                            "intent": intent.name,
                            "environment": seen.environment,
                            "seed": seen.seed,
                            "fired": variant,
                            "acceptable": list(pair.acceptable_variants),
                        }
                    )
    return Arms(
        tree=operating_point(outcomes["tree"]),
        tree_unrestricted=operating_point(outcomes["unrestricted"]),
        arm3=operating_point(outcomes["arm3"]),
        agree=agree,
        tree_wrong=wrong["tree"],
        tree_unrestricted_wrong=wrong["unrestricted"],
    )


def _cases(
    faults: Sequence[str], seeds_of: dict[str, Sequence[int]]
) -> list[tuple[str, int, list[str]]]:
    """`state_classifier._states`' sandboxes: each fault's seeds, with the fault-free state."""
    return [
        (environment, seed, injected)
        for fault in faults
        for seed in seeds_of[fault]
        for environment, injected in ((FAULT_FREE, []), (fault, [fault]))
    ]


def _pair_cases(faults: Sequence[str], seeds: Sequence[int]) -> list[tuple[str, int, list[str]]]:
    """`state_classifier.outcomes`' sandboxes, in its order."""
    return [
        (environment, seed, injected)
        for seed in seeds
        for environment, injected in [(FAULT_FREE, []), *((f, [f]) for f in faults)]
    ]


VERDICTS = "verdicts.jsonl.gz"
"""Every sandbox's state and per-library verdicts, one per line, with its block, so the
analysis can be repeated (`--from`) without building a sandbox or running a probe."""


def run(
    out: Path,
    *,
    faults: Sequence[str] = HELD_OUT_FAULTS,
    libraries: Sequence[Path] = LIBRARY_ROOTS,
    blocks: Sequence[tuple[str, Sequence[int]]] = (
        ("eval", EVAL_SEEDS),
        ("held-out", HELD_OUT_SEEDS),
    ),
) -> Report:
    if out.exists():
        raise ValueError(f"{out} already exists; the control writes a fresh directory")
    views = [ProbeView(root) for root in libraries]
    seen = {"training": observe(views, _cases(faults, {f: admit_seeds(f) for f in faults}))}
    seen |= {name: observe(views, _pair_cases(faults, seeds)) for name, seeds in blocks}
    out.mkdir(parents=True)
    with gzip.open(out / VERDICTS, "wt", encoding="utf-8") as handle:
        for name, observed in seen.items():
            for o in observed:
                handle.write(json.dumps({"block": name, **o.model_dump(mode="json")}) + "\n")
    return analyse(out, views, faults, seen)


def analyse(
    out: Path,
    views: Sequence[ProbeView],
    faults: Sequence[str],
    seen: dict[str, list[Observed]],
) -> Report:
    """The trees and arm 3 from recorded verdicts; writes the report into `out`."""
    intents = _measured_intents(faults)
    training = seen["training"]
    blocks = [name for name in seen if name != "training"]
    reports = []
    pairs: dict[str, int] = {}
    for r, view in enumerate(views):
        rows = [(t.verdicts[r], t.state) for t in training]
        held = {p.variant for p in view.programs if p.variant is not None}
        trees = ProbeTrees(intents, allowed=held).fit(rows)
        unrestricted = ProbeTrees(intents).fit(rows)
        scored = {name: score(trees, unrestricted, view, r, intents, seen[name]) for name in blocks}
        pairs = {name: arms.tree.coverage.denominator for name, arms in scored.items()}
        reports.append(
            LibraryReport(
                library=str(view.root.relative_to(REPOSITORY))
                if view.root.is_relative_to(REPOSITORY)
                else str(view.root),
                admitted_programs=len(view.programs),
                distinct_preconditions=len(view.predicates),
                tree_depths=trees.depths(),
                blocks=scored,
            )
        )
    report = Report(training_states=len(training), pairs=pairs, libraries=reports)
    (out / "report.json").write_text(report.model_dump_json(indent=2) + "\n", "utf-8")
    (out / "summary.txt").write_text(text(report), encoding="utf-8")
    return report


def recorded(out: Path) -> dict[str, list[Observed]]:
    seen: dict[str, list[Observed]] = {}
    with gzip.open(out / VERDICTS, "rt", encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    for line in lines:
        row = json.loads(line)
        seen.setdefault(row.pop("block"), []).append(Observed.model_validate(row))
    return seen


def text(report: Report) -> str:
    lines = [
        "A tree over only the library's precondition verdicts (#295 item 3), beside arm 3 "
        f"recomputed from the same verdicts; trained on {report.training_states} states",
        "",
        "library  block     preconditions  tree fires/wrong  unrestricted  "
        "arm 3 fires/wrong  agree",
    ]
    for lib in report.libraries:
        for name, arms in lib.blocks.items():
            free = arms.tree_unrestricted
            lines.append(
                f"{lib.library.split('/')[2]:<8} {name:<9} {lib.distinct_preconditions:>13}  "
                f"{arms.tree.coverage.numerator:>5}/{arms.tree.mismatch.numerator:<10} "
                f"{free.coverage.numerator:>5}/{free.mismatch.numerator:<6} "
                f"{arms.arm3.coverage.numerator:>6}/{arms.arm3.mismatch.numerator:<10} "
                f"{arms.agree:>5}/{arms.tree.coverage.denominator}"
            )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m precondition_library.bench.probe_classifier")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--from",
        dest="source",
        type=Path,
        default=None,
        help="repeat the analysis from a run's recorded verdicts, writing into --out",
    )
    args = parser.parse_args(argv)
    if args.source is None:
        print(text(run(args.out)), end="")
        return 0
    if args.out.exists():
        raise SystemExit(f"{args.out} already exists")
    args.out.mkdir(parents=True)
    views = [ProbeView(root) for root in LIBRARY_ROOTS]
    print(text(analyse(args.out, views, HELD_OUT_FAULTS, recorded(args.source))), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
