"""The real-host stage: do the held-out results survive a real project's history? (ADR-0043)

Every state the held-out stage builds (`bench.heldout`) still starts from the generator's
two-file base: `app.py`, `docs/readme.md` and one commit. A program that lists every tracked
file, reads the first line of `git log` or assumes a tree with no `.gitignore` meets nothing
that would break it there. This stage changes that one thing and nothing else.

**What varies.** Each sandbox's history starts from a pinned public repository, its pinned
commit and the 50 commits before it (`REAL_HOSTS`), instead of the synthetic base. The
generator's base files are committed on top, and the fault is injected exactly as before.

**What does not.** The seeds are the eval block (`bench.splits.EVAL_SEEDS`), so every
instance is one Figure 1 measured on the synthetic base: the comparison is paired, and a
difference is the base's. Seeds below `HELD_OUT_SEED_BASE` draw no held-out axis, so no
held-out name or path is mixed in. The library is the committed frozen one, read-only, and
each block is measured by `bench.heldout.run_held_out`, unchanged.

**What it needs.** Network, once per host: `sandbox.fetch_real_host` fetches the pinned commit
into a local cache under `.sandboxes/`, never committed. Only each host's URL and commit are
recorded here. A host's content is fetched by commit SHA, so a rerun builds byte-identical
states wherever it runs.

**What it may not say.** The held-out stage's two limits apply unchanged (ADR-0033): no floor,
so no sentence that arm 3 beats text similarity here, and blocks of 10 seeds per host, which
are pilots. Four repositories are not a sample of repositories.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from ..sandbox import RealHost, real_host_bases
from .heldout import HELD_OUT_FAULTS, HeldOutSummary, run_held_out
from .library_pairs import FAULT_FREE
from .rescore import scorer
from .splits import EVAL_SEEDS

REAL_HOSTS: tuple[RealHost, ...] = (
    RealHost(
        "psf/requests",
        "https://github.com/psf/requests",
        "611c6162cbc4ac2020a2f91c7cfa4f3abf9bbb60",
    ),
    RealHost(
        "pallets/click",
        "https://github.com/pallets/click",
        "2247b35ea1c47c727d7a06e51fa280e12a863ff6",
    ),
    RealHost(
        "junegunn/fzf",
        "https://github.com/junegunn/fzf",
        "55c122f1a0e1340546c8709682bea5561fe0e8fd",
    ),
    RealHost(
        "expressjs/express",
        "https://github.com/expressjs/express",
        "0dee2c52c7c873498f8ed7d8ee4ddd0a04d3ada8",
    ),
)
"""The pinned hosts, each its default branch's tip on 2026-10-20 (`git ls-remote ... HEAD`).

Two Python projects, a Go one and a JavaScript one, with different `.gitignore` rules: fzf
ignores `vendor`, where `submodule_moved` puts its submodule. The order is part of the
seed-to-host mapping (`host_for_seed`), so appending a host moves seeds; add deliberately."""

REAL_HOST_SEEDS: tuple[int, ...] = EVAL_SEEDS
"""The eval block, so each state is one the primary result measured on the synthetic base."""


def host_for_seed(seed: int) -> RealHost:
    """The host a seed's history starts from: the seeds take the hosts in turn."""
    return REAL_HOSTS[seed % len(REAL_HOSTS)]


def seeds_for_host(host: RealHost, seeds: Sequence[int] = REAL_HOST_SEEDS) -> tuple[int, ...]:
    return tuple(seed for seed in seeds if host_for_seed(seed) == host)


def slug(host: RealHost) -> str:
    """The directory a host's blocks are written under: `psf/requests` -> `psf-requests`."""
    return host.name.replace("/", "-")


class BlockCount(BaseModel):
    host: str
    fault: str
    seeds: int
    arm3_fires: int
    arm3_wrong: int
    fault_free_fires: int


def run_real_host(
    run: Path,
    out: Path,
    *,
    scorer_name: str = "lexical",
    faults: Sequence[str] = HELD_OUT_FAULTS,
    hosts: Sequence[RealHost] = REAL_HOSTS,
    seeds: Sequence[int] = REAL_HOST_SEEDS,
) -> list[BlockCount]:
    """Measure each (host, fault) block of `run`'s frozen library, one directory each.

    `out/<host>/<fault>/` holds `run_held_out`'s own record, so each block reads like a
    held-out block and is recounted the same way; like it, a block refuses a directory that
    exists. Plots are skipped: a block of 10 seeds is a count, not a figure. Hosts may be
    measured by separate processes into one `out`; `write_summary` then reads them all.
    """
    similarity, identity = scorer(scorer_name)
    counts: list[BlockCount] = []
    with real_host_bases(host_for_seed):
        for host in hosts:
            host_seeds = seeds_for_host(host, seeds)
            if not host_seeds:
                continue
            for fault in faults:
                result = run_held_out(
                    run / "library-two-sided",
                    out / slug(host) / fault,
                    similarity=similarity,
                    scorer_id=identity,
                    source=str(run),
                    faults=(fault,),
                    seeds=host_seeds,
                    plot=False,
                )
                counts.append(block_count(host.name, fault, result))
    return counts


def write_summary(out: Path) -> list[BlockCount]:
    """Write `out/realhost.json`: the pins and every block's counts, read back from disk."""
    counts = read_blocks(out)
    if not counts:
        raise ValueError(f"{out} holds no measured block")
    sources = {
        HeldOutSummary.model_validate_json(path.read_text(encoding="utf-8")).source
        for path in out.glob("*/*/summary.json")
    }
    (out / "realhost.json").write_text(
        json.dumps(
            {
                "sources": sorted(sources),
                "hosts": [
                    {
                        "name": host.name,
                        "url": host.url,
                        "commit": host.commit,
                        "depth": host.depth,
                        "seeds": list(seeds_for_host(host)),
                    }
                    for host in REAL_HOSTS
                ],
                "blocks": [count.model_dump() for count in counts],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return counts


def block_count(host: str, fault: str, result: HeldOutSummary) -> BlockCount:
    """One block's counts, from its summary: fires, wrong fires, and fires on no fault."""
    return BlockCount(
        host=host,
        fault=fault,
        seeds=len(result.seeds),
        arm3_fires=result.arm3_fires,
        arm3_wrong=result.arm3_wrong,
        fault_free_fires=sum(fire.environment == FAULT_FREE for fire in result.wrong_fires),
    )


def read_blocks(out: Path) -> list[BlockCount]:
    """Every block's counts, read back from the committed per-block `summary.json` files."""
    counts = []
    for summary_path in sorted(out.glob("*/*/summary.json")):
        result = HeldOutSummary.model_validate_json(summary_path.read_text(encoding="utf-8"))
        host = next(h.name for h in REAL_HOSTS if slug(h) == summary_path.parent.parent.name)
        counts.append(block_count(host, summary_path.parent.name, result))
    return counts


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m precondition_library.bench.realhost",
        description=(
            "Measure the committed frozen library on fault states built over pinned real "
            "repositories (ADR-0043). No model call; fetches each host once."
        ),
    )
    parser.add_argument("--run", type=Path, help="a finished run directory")
    parser.add_argument("--out", type=Path, required=True, help="the stage's output directory")
    parser.add_argument(
        "--scorer", choices=("lexical", "embedding", "cross-encoder"), default="lexical"
    )
    parser.add_argument("--faults", nargs="+", default=list(HELD_OUT_FAULTS))
    parser.add_argument(
        "--hosts",
        nargs="+",
        choices=[host.name for host in REAL_HOSTS],
        help="measure only these hosts (default: all), e.g. one per process",
    )
    parser.add_argument(
        "--summarize",
        action="store_true",
        help="measure nothing; write realhost.json from the blocks already in --out",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.summarize:
        counts = write_summary(args.out)
    else:
        if args.run is None:
            raise SystemExit("--run is required unless --summarize")
        hosts = [h for h in REAL_HOSTS if args.hosts is None or h.name in args.hosts]
        counts = run_real_host(
            args.run, args.out, scorer_name=args.scorer, faults=args.faults, hosts=hosts
        )
    for count in counts:
        print(
            f"{count.host:20} {count.fault:18} seeds {count.seeds:2}  arm 3 fires "
            f"{count.arm3_fires:2}, wrong {count.arm3_wrong:2}, on no fault "
            f"{count.fault_free_fires}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
