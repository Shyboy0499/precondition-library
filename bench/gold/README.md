# Gold solutions

Hand-written, obviously-correct resolutions, one per declared variant of the
ambiguous intents. They exist for a single purpose: to prove the ground-truth
checkers work before any agent result is believed.

What runs today for the two ambiguous intents is form validation only: gold
resolutions live in `sync_fork_with_upstream.yaml` and
`restore_submodule_state.yaml`, and `tests/test_gold_programs.py` validates that
they parse, are well-formed, cover every declared resolution, have distinct
bodies, and describe themselves without naming a resolution — a description is
part of the text arm 2 compares a request against (`library._program_text`), so a
label in one would be the leak `test_no_phrasing_names_a_resolution` forbids on
the request side. No probe has ever been executed against a sandbox:
`tests/test_checkers_against_gold.py` is skipped for every fault until checker
execution lands (issue #4), because a checker cannot be validated without a state
to check.

These are intentionally written by hand and kept short. If a gold solution needs
a clever trick to satisfy the checker, that is a finding about the checker:
either it is testing more than the fault, or the fault is not as well-defined as
its description claims.
