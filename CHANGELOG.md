# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

Versions are **0.x** and the design is still moving. Nothing below claims a
measured result; there are none yet. See
[`docs/decisions/`](docs/decisions/) for reversals and the reasoning behind them.

## [Unreleased]

### Changed

- Nothing yet.

## [0.0.1] — 2026-09-13

Design-phase release. No agent exists and no result is claimed.

### Added

- Design of record with a pre-registered analysis
  (`docs/superpowers/specs/2026-09-13-precondition-library-design.md`).
- Repository skeleton: every stub names the invariant it must uphold and the plan
  phase that implements it; 30 tests skipped, each marked with its phase.
- `tests/test_replay_isolated_from_provider.py` — a passing test that fails if
  `runtime.replay` can reach `provider`. The claim that a replay costs zero tokens
  depends on this, so the guardrail ships before the code it guards.
- CI running ruff, `ruff format --check`, mypy, and pytest on Python 3.12 via uv.
- ADR-0001, recording the reframe after a prior-art sweep and a method review:
  Claim 1 dropped as prior art, Claim 2 narrowed to its empirical form, the
  primary metric moved to matched dispatch coverage.
- Verified prior-work table in the README, with five corrected attributions from
  the original sweep kept visible rather than silently fixed.

### Changed

- `ProgramStatus.VERIFIED` renamed to `ADMITTED`. A program that passed this
  project's own gate has not been verified by anyone.
- The pre-registered analysis was revised **before any data existed**; the
  revision is logged in the spec's revision history.

[Unreleased]: https://github.com/Shyboy0499/precondition-library/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/Shyboy0499/precondition-library/releases/tag/v0.0.1
