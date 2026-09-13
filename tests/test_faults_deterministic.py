"""Same seed, same faulty environment.

The ablation compares arms on shared environments, so non-determinism in fault
injection would introduce variance that looks like a difference between arms.
Determinism is also what lets a reported episode be re-run and inspected later.
"""

from __future__ import annotations

import pytest

from precondition_library.tasks import ALL_FAULTS


@pytest.mark.skip(reason="fault injectors are stubs; implemented per plan, phase 1")
@pytest.mark.parametrize("fault_type", ALL_FAULTS)
def test_same_seed_same_state(fault_type: str) -> None:
    """Two sandboxes built from one seed must match on every probe the
    fingerprint records, and produce the same task text."""
    raise NotImplementedError


@pytest.mark.skip(reason="fault injectors are stubs; implemented per plan, phase 1")
@pytest.mark.parametrize("fault_type", ALL_FAULTS)
def test_different_seeds_differ(fault_type: str) -> None:
    """Occurrences must not be clones of each other, or occurrence_index would
    count repetitions of one scenario instead of recurrences of a task family."""
    raise NotImplementedError
