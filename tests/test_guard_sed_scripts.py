"""`sed -i` is screened by the files it rewrites, not by its script (#214).

The guard read every `sed -i` argument as a write target, so a script starting with `/`
(`sed -i '/^packages/r extra' deps.lock`) looked like an absolute path and the body was
refused. The lockfile gold bodies had to use the `\\%...%` address to get through. The
script is now told apart from the files, and a script's own `w` command is still a
write target, so `sed` cannot write outside the sandbox through it.
"""

from __future__ import annotations

import pytest

from precondition_library.runtime.guard import Verdict, _sed_arguments, screen

ROOT = "/sandbox/root"


@pytest.mark.parametrize(
    "body",
    [
        "sed -i '/^packages = \\[$/r .git/lock-additions' deps.lock",
        "sed -i '\\%^packages = \\[$%r .git/lock-additions' deps.lock",
        "sed -i -e '/elder/d' -e 's/a/b/' deps.lock",
        "sed -i.bak '/x/d' deps.lock",
        "sed --in-place --expression='/x/d' deps.lock",
        "sed -i -f .git/edit.sed deps.lock",
        "sed -i '1w notes/first-line' deps.lock",
        "sed -i 's/how /now /' docs/readme.md",
        "sed -n '/x/p' /etc/hosts",
    ],
)
def test_a_sed_edit_inside_the_sandbox_is_allowed(body: str) -> None:
    decision = screen(body, env_root=ROOT)
    assert decision.verdict is Verdict.ALLOW, decision.reason


@pytest.mark.parametrize(
    "body",
    [
        "sed -i 's/x/y/' /etc/hostname",
        "sed -i -e '/x/d' -- ../outside.txt",
        "sed -i 's/x/y/w /etc/stolen' deps.lock",
        "sed -i '/x/w /tmp/out' deps.lock",
        "sed -i '1w ../outside' deps.lock",
        "sed -i '2w ~/copy' deps.lock",
        "sed -i -e '1,3W /tmp/out' deps.lock",
    ],
)
def test_a_sed_write_outside_the_sandbox_is_still_refused(body: str) -> None:
    decision = screen(body, env_root=ROOT)
    assert decision.verdict is Verdict.REFUSE
    assert decision.reason.startswith("refused write outside env_root")


@pytest.mark.parametrize(
    ("args", "scripts", "files"),
    [
        (["-i", "/a/d", "f1", "f2"], ["/a/d"], ["f1", "f2"]),
        (["-i", "-e", "/a/d", "-e", "s/x/y/", "f"], ["/a/d", "s/x/y/"], ["f"]),
        (["-ne", "/a/p", "f"], ["/a/p"], ["f"]),
        (["-i", "-f", "edit.sed", "f"], [], ["f"]),
        (["--expression=/a/d", "-i", "f"], ["/a/d"], ["f"]),
        (["-i", "s/a/b/", "--", "-odd-name"], ["s/a/b/"], ["-odd-name"]),
    ],
)
def test_the_script_is_told_apart_from_the_files(
    args: list[str], scripts: list[str], files: list[str]
) -> None:
    assert _sed_arguments(args) == (scripts, files)
