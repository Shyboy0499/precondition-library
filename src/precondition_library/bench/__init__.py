"""The old home of the experiment code, kept only as aliases.

Every module that lived here moved into a package named for what it is (`experiment`,
`experiment.scorers`, `experiment.stages`, `controls`, `studies`, `audits`). Frozen
pre-registrations, committed results and their verification scripts quote the old paths
(`python -m precondition_library.bench.real_merges`), and a registration cannot be edited
without breaking its pin, so each old path stays: importing it returns the moved module itself,
and running it with `-m` runs the moved module. New code imports the new paths.
"""

from __future__ import annotations

import importlib
import runpy
import sys

MOVED: dict[str, str] = {}
"""Old module name (under `precondition_library.bench`) -> its new dotted path, as `alias` saw
them."""


def alias(old: str, new: str) -> None:
    """Make the module `old` (an alias file's `__name__`) stand for the module `new`.

    Imported, the alias replaces itself in `sys.modules` with the moved module, so both names
    are one object and patching either patches both. Run with `-m` (`old` is then `"__main__"`),
    it runs the moved module as `__main__`, exactly as `python -m <new>` would.
    """
    if old == "__main__":
        runpy.run_module(new, run_name="__main__", alter_sys=True)
        return
    MOVED[old.rsplit(".", 1)[1]] = new
    sys.modules[old] = importlib.import_module(new)


__all__ = ["MOVED", "alias"]
