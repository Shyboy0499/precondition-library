"""The spec's revision table stays in order, however its rows were merged.

Each change that alters the design adds a revision row (`| N | YYYY-MM-DD | ...`). Rows
are numbered when they are written, and several changes in flight each add theirs; when
one merges after another, git can apply a row cleanly in the wrong place -- the table
then reads as if a later revision preceded an earlier one, which no reviewer looks for.
Numbers need not be contiguous (a change can be dropped after its row was numbered);
they must strictly increase, so each row is unique and in the order it was numbered.
"""

from __future__ import annotations

import re
from pathlib import Path

SPEC = (
    Path(__file__).resolve().parents[1]
    / "docs/design/specs/2026-09-13-precondition-library-design.md"
)
ROW = re.compile(r"^\| (\d+) \| \d{4}-\d{2}-\d{2} \|")


def test_revision_rows_strictly_increase() -> None:
    numbers = [
        int(match.group(1))
        for line in SPEC.read_text(encoding="utf-8").splitlines()
        if (match := ROW.match(line))
    ]
    assert numbers, "the spec has no revision rows; the pattern no longer matches the table"
    out_of_order = [
        (before, after) for before, after in zip(numbers, numbers[1:]) if after <= before
    ]
    assert not out_of_order, f"revision rows out of order or repeated: {out_of_order}"
