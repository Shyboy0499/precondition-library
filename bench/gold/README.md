# Gold solutions

One hand-written, obviously-correct solution per fault type. They exist for a
single purpose: to prove the ground-truth checkers work before any agent result
is believed.

Run them first. If a gold solution does not satisfy its fault's checker, the
checker is wrong, and every number produced afterwards — for every arm — is
meaningless. `tests/test_checkers_against_gold.py` is the enforcement; it runs
in CI before anything else is trusted.

These are intentionally written by hand and kept short. If a gold solution needs
a clever trick to satisfy the checker, that is a finding about the checker:
either it is testing more than the fault, or the fault is not as well-defined as
its description claims.
