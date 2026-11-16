"""A compiled reply's YAML is read as the model wrote it, or refused with why.

The tenth live run's first three build episodes lost three compile replies to "not a
YAML mapping", and the repair retry was told nothing more, so it could not fix them.
Worse, a probe written the way the compile prompt's own absence rule shows --
`! git stash list | grep -q 'wip'` -- loads as `git stash list | grep -q 'wip'`:
YAML reads the `!` as a tag and drops it, so the check is silently inverted. These
tests pin that such a reply is refused with a reason the repair can act on, that the
block-scalar form the prompt now asks for keeps the `!`, and that a YAML error's own
message reaches the reason.
"""

from __future__ import annotations

import pytest

from precondition_library.agents.compile import SYSTEM_PROMPT, _parse_document

_ABSENT = "! git stash list | grep -q 'wip'"


def test_a_plain_bang_probe_is_refused_not_inverted() -> None:
    document, reason = _parse_document(f"probe: {_ABSENT}\n")
    assert document is None
    assert "YAML tag" in reason and "loses its negation" in reason and "|-" in reason


def test_the_block_scalar_form_keeps_the_bang() -> None:
    document, reason = _parse_document(f"probe: |-\n  {_ABSENT}\n")
    assert document == {"probe": _ABSENT} and reason == ""


@pytest.mark.parametrize(
    ("text", "names"),
    [
        pytest.param("a: &x y\nb: *x\n", "anchor", id="anchor"),
        pytest.param("a: *x\n", "alias", id="alias"),
        pytest.param("probe: !!str x\n", "YAML tag", id="explicit-tag"),
    ],
)
def test_anchors_aliases_and_tags_are_refused(text: str, names: str) -> None:
    document, reason = _parse_document(text)
    assert document is None and names in reason


def test_a_yaml_error_names_its_line() -> None:
    document, reason = _parse_document('id: x\nprobe: "$(git rev-parse HEAD)" = x\n')
    assert document is None
    assert "line 2" in reason, "the repair needs to know where the reply broke"


def test_a_list_reply_says_so() -> None:
    assert _parse_document("- a\n- b\n") == (None, "its top level is a list, not a mapping")


def test_a_fenced_mapping_still_parses() -> None:
    assert _parse_document("```yaml\nid: x\n```") == ({"id": "x"}, "")


def test_the_prompt_says_how_to_write_shell_that_yaml_would_misread() -> None:
    assert "Shell is not YAML-safe" in SYSTEM_PROMPT
    assert "probe: |-" in SYSTEM_PROMPT
    # The example that taught the inverted form now points at the quoting rule.
    assert "(quoted in YAML, as the next rule says)" in SYSTEM_PROMPT
