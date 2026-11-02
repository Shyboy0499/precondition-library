"""A blind labelling kit for #299 step 3: people label states without our rules, then we score.

The project's labels are its own rules over the observed state. #299 asks how often independent
git practitioners agree with them, and with each other. This module makes the material and
scores the answers; finding the people is the owner's part.

**Making the kit** (`make`). From Figure 1's eval seeds, it samples, per measured intent, some
states of the intent's own fault and some fault-free states. For each it builds the sandbox and
writes a *card*:

- the request as a user would send it (the uninformed wording);
- what a practitioner would look at in the repository: `git status`, branches and what they
  track, the history graph, stashes, submodules, the difference from upstream, and what a trial
  merge of upstream reports;
- the candidate actions, in neutral words that say what each does and never why, in a random
  order, plus "nothing needs doing" and "none of these is safe".

Cards carry only an opaque id, a salted hash. The salt and the answer key stay with the owner:
the key is written to a separate path, which must not be shared with the raters or committed,
since this repository is public.

**Scoring** (`score`). Given the key and one answer sheet per rater, it reports:

- each rater's agreement with our rules (an answer agrees when it is an acceptable resolution,
  or "nothing" on a state that needs nothing);
- Cohen's κ between every pair of raters, and between each rater and our labels;
- every card on which a rater and our rules disagree.

    python -m precondition_library.bench.human_labels make --out <cards> --key <private key.json>
    python -m precondition_library.bench.human_labels score --key <key.json> <rater answers.csv>...

The salt is read from the environment variable `HUMAN_LABEL_SALT`; without it the cards' ids
could be recomputed by anyone, which would unblind them.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import subprocess
from collections.abc import Sequence
from itertools import combinations
from pathlib import Path

from pydantic import BaseModel

from ..runtime.probes import bindings
from ..sandbox import Sandbox
from ..signatures import StateFingerprint
from ..tasks.faults import build_sandbox
from ..tasks.intent import IntentSpec
from .heldout import HELD_OUT_FAULTS
from .library_pairs import FAULT_FREE, _measured_intents
from .pairs import label
from .splits import EVAL_SEEDS

NOTHING = "nothing"
UNSAFE = "none is safe"

ACTIONS: dict[str, dict[str, str]] = {
    "keep_uncommitted_work_and_sync": {
        "stash": "Stash every local change, untracked files included; fast-forward to upstream; "
        "re-apply the stash.",
        "commit": "Commit every local change as work in progress; then merge upstream into the "
        "branch.",
        "aside": "Rename each untracked file that upstream now tracks to a backup name; then "
        "fast-forward to upstream.",
    },
    "sync_fork_with_upstream": {
        "discard": "Reset the branch hard to upstream's tip.",
        "rebase": "Rebase the local commits onto upstream's tip.",
        "merge": "Merge upstream into the branch with a merge commit.",
    },
    "sync_through_a_conflicting_lockfile": {
        "take_upstream": "Merge upstream; resolve the conflicted dependency file as upstream's "
        "version plus the lines the local side added.",
        "keep_local": "Merge upstream; resolve the conflicted dependency file as the local "
        "version plus the lines upstream added.",
    },
    "follow_renamed_upstream_branch": {
        "rename": "Rename the local branch to upstream's new branch name, track it, and "
        "fast-forward.",
        "retrack": "Keep the branch's name, point its tracking at upstream's new branch, and "
        "fast-forward.",
        "merge": "Keep the branch's name, point its tracking at upstream's new branch, and merge "
        "it with a merge commit.",
    },
    "restore_submodule_state": {
        "init": "Initialise and check out the nested repository (`git submodule update --init`).",
        "repin": "Check out upstream's recorded commit for the nested repository and commit "
        "that pin.",
        "remove": "Remove the nested repository from the index and from `.gitmodules`, and commit.",
    },
}
"""What each resolution does, from its gold program, in words that do not say when it is right."""


class Card(BaseModel):
    id: str
    intent: str
    environment: str
    seed: int
    label: str
    """Our rule's answer: a resolution, or `NOTHING`."""
    acceptable: list[str]
    options: dict[str, str]
    """Letter -> the action it stands for."""


def card_id(salt: str, intent: str, environment: str, seed: int) -> str:
    return hashlib.sha256(f"{salt}|{intent}|{environment}|{seed}".encode()).hexdigest()[:10]


def _run(work: Path, *argv: str) -> str:
    done = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *argv],
        cwd=work,
        capture_output=True,
        text=True,
        check=False,
    )
    return (done.stdout + done.stderr).rstrip() or "(no output)"


def observe(box: Sandbox) -> str:
    """What a practitioner would look at, as terminal output."""
    work = Path(box.work)
    _run(work, "fetch", "-q", "--all")
    values = bindings(box)
    upstream = (
        f"{values.get('upstream_remote', 'upstream')}/{values.get('upstream_branch', 'main')}"
    )
    sections = [
        ("git status", _run(work, "status")),
        ("git branch -vv", _run(work, "branch", "-vv")),
        ("git branch -r", _run(work, "branch", "-r")),
        (
            "git log --oneline --graph --decorate --all -n 25",
            _run(work, "log", "--oneline", "--graph", "--decorate", "--all", "-n", "25"),
        ),
        ("git stash list", _run(work, "stash", "list")),
        ("git submodule status", _run(work, "submodule", "status")),
        (f"git diff --stat HEAD {upstream}", _run(work, "diff", "--stat", "HEAD", upstream)),
        (
            f"git merge-tree --write-tree --name-only HEAD {upstream}",
            _run(work, "merge-tree", "--write-tree", "--name-only", "HEAD", upstream),
        ),
    ]
    return "\n\n".join(f"$ {command}\n{output}" for command, output in sections)


def render(card: Card, request: str, terminal: str) -> str:
    options = "\n".join(f"- **{letter}.** {text}" for letter, text in card.options.items())
    return (
        f"# Card {card.id}\n\n"
        f"**The request:** {request}\n\n"
        "**What the repository shows** (the working directory is the user's clone; the remote "
        "holds the project the clone tracks):\n\n"
        f"```text\n{terminal}\n```\n\n"
        "**Which one action would you take?** Answer with one letter.\n\n"
        f"{options}\n"
    )


def _options(intent: IntentSpec, rng: random.Random) -> dict[str, str]:
    actions = list(ACTIONS[intent.name].items())
    rng.shuffle(actions)
    texts = [text for _, text in actions]
    texts += ["Nothing needs doing here.", "None of these is safe; I would run none of them."]
    return {chr(ord("A") + i): t for i, t in enumerate(texts)}


def _action_of(intent: IntentSpec, text: str) -> str:
    for action, wording in ACTIONS[intent.name].items():
        if wording == text:
            return action
    return NOTHING if text.startswith("Nothing") else UNSAFE


def make(
    out: Path,
    key: Path,
    salt: str,
    *,
    faulted: int = 8,
    fault_free: int = 4,
    faults: Sequence[str] = HELD_OUT_FAULTS,
    seeds: Sequence[int] = EVAL_SEEDS,
) -> list[Card]:
    """Write one card per sampled (intent, state) to `out`, and the key to `key`."""
    if not salt:
        raise ValueError("a salt is required; without it anyone could recompute the card ids")
    if key.resolve().is_relative_to(out.resolve()):
        raise ValueError("the key must not be written among the cards")
    out.mkdir(parents=True, exist_ok=False)
    rng = random.Random(f"{salt}|sample")
    cards: list[Card] = []
    for intent in _measured_intents(faults):
        chosen = [(intent.fault, [intent.fault], s) for s in rng.sample(list(seeds), faulted)]
        chosen += [(FAULT_FREE, [], s) for s in rng.sample(list(seeds), fault_free)]
        for environment, injected, seed in chosen:
            box = build_sandbox(seed, injected)
            try:
                state = StateFingerprint.observe(box)
                terminal = observe(box)
            finally:
                box.destroy()
            pair = label(intent, seed, state, uninformed=True)
            texts = _options(intent, random.Random(f"{salt}|{intent.name}|{environment}|{seed}"))
            card = Card(
                id=card_id(salt, intent.name, environment, seed),
                intent=intent.name,
                environment=environment,
                seed=seed,
                label=pair.correct_variant or NOTHING,
                acceptable=list(pair.acceptable_variants) or [NOTHING],
                options={letter: _action_of(intent, text) for letter, text in texts.items()},
            )
            (out / f"{card.id}.md").write_text(
                render(card.model_copy(update={"options": texts}), pair.task_text, terminal),
                encoding="utf-8",
            )
            cards.append(card)
    rng.shuffle(cards)
    with (out / "answers.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["card", "answer"])
        writer.writerows([c.id, ""] for c in sorted(cards, key=lambda c: c.id))
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_text(json.dumps([c.model_dump() for c in cards], indent=2) + "\n", "utf-8")
    return cards


# --- scoring ---------------------------------------------------------------------------------


def kappa(first: Sequence[str], second: Sequence[str]) -> float | None:
    """Cohen's κ for two raters' categorical answers on the same items; None if undefined."""
    if len(first) != len(second) or not first:
        raise ValueError("κ needs two equally long, non-empty answer lists")
    n = len(first)
    observed = sum(a == b for a, b in zip(first, second, strict=True)) / n
    categories = set(first) | set(second)
    expected = sum((first.count(c) / n) * (second.count(c) / n) for c in categories)
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


class RaterScore(BaseModel):
    rater: str
    answered: int
    agrees_with_rules: int
    kappa_with_rules: float | None
    disagreements: list[dict[str, str]]


class Scores(BaseModel):
    cards: int
    raters: list[RaterScore]
    pairwise_kappa: dict[str, float | None]
    """Between raters, on the cards both answered."""


def read_answers(path: Path, cards: dict[str, Card]) -> dict[str, str]:
    """A rater's sheet as card id -> action; blank answers are left out."""
    found: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            letter = (row.get("answer") or "").strip().upper()
            if not letter:
                continue
            card = cards.get(row["card"].strip())
            if card is None or letter not in card.options:
                raise ValueError(f"{path}: {row['card']!r} answered {letter!r}, not an option")
            found[card.id] = card.options[letter]
    return found


def score(key: Path, sheets: Sequence[Path]) -> Scores:
    cards = {c["id"]: Card.model_validate(c) for c in json.loads(key.read_text("utf-8"))}
    answers = {sheet.stem: read_answers(sheet, cards) for sheet in sheets}
    raters = []
    for name, given in answers.items():
        ids = sorted(given)
        agree = [i for i in ids if given[i] in cards[i].acceptable]
        raters.append(
            RaterScore(
                rater=name,
                answered=len(ids),
                agrees_with_rules=len(agree),
                kappa_with_rules=kappa([given[i] for i in ids], [cards[i].label for i in ids])
                if ids
                else None,
                disagreements=[
                    {
                        "card": i,
                        "intent": cards[i].intent,
                        "answered": given[i],
                        "rules": cards[i].label,
                    }
                    for i in ids
                    if i not in agree
                ],
            )
        )
    pairwise: dict[str, float | None] = {}
    for a, b in combinations(sorted(answers), 2):
        both = sorted(set(answers[a]) & set(answers[b]))
        pairwise[f"{a} ~ {b}"] = (
            kappa([answers[a][i] for i in both], [answers[b][i] for i in both]) if both else None
        )
    return Scores(cards=len(cards), raters=raters, pairwise_kappa=pairwise)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m precondition_library.bench.human_labels")
    commands = parser.add_subparsers(dest="command", required=True)
    made = commands.add_parser("make", help="write the cards and the private key")
    made.add_argument("--out", type=Path, required=True)
    made.add_argument("--key", type=Path, required=True)
    made.add_argument("--faulted", type=int, default=8)
    made.add_argument("--fault-free", type=int, default=4)
    scored = commands.add_parser("score", help="score raters' answer sheets against the key")
    scored.add_argument("--key", type=Path, required=True)
    scored.add_argument("sheets", type=Path, nargs="+")
    args = parser.parse_args(argv)
    if args.command == "make":
        cards = make(
            args.out,
            args.key,
            os.environ.get("HUMAN_LABEL_SALT", ""),
            faulted=args.faulted,
            fault_free=args.fault_free,
        )
        print(f"wrote {len(cards)} cards to {args.out} and the key to {args.key}")
        return 0
    print(score(args.key, args.sheets).model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
