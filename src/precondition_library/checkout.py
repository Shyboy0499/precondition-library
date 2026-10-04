"""An existing checkout as an environment dispatch and replay accept (issue #181, item 2).

`sandbox.create` builds the only environments the runtime has known: a scratch root, a
clone, and a local bare repository standing in for upstream. A real repository is none
of those, and three of its differences would change what a program does:

* **Its upstream is on the network.** Every compiled sync and submodule program
  fetches, and model-authored shell runs with no network (`runtime.confine`). So the
  tool fetches first, itself, with the user's own git configuration and credentials --
  one fixed `git fetch <remote>`, never model text -- and then mirrors the fetched
  remote-tracking refs into a local bare repository. During a run git reads the
  remote's URL from that mirror (`url.<mirror>.insteadOf`), so a program's `git fetch`
  succeeds with nothing to download, and a `git push` can reach only the mirror.
* **Its parameters are its own** -- `runtime.probes.repository_bindings`, not the
  harness's fixed `upstream` / `main`.
* **Its commits are the user's** -- their `user.name` and `user.email`, dated now. The
  sandbox's pinned identity and date are for reproducible harness SHAs and would stamp
  a fake author onto someone's history.

Everything else is the harness's: the hardened git environment, `HOME` redirected into
the scratch root, no network for model-authored text, the guard's screen with the
checkout as its write boundary, and probes refused when they change the repository.

**What is not isolated, stated rather than implied.** The checkout is the user's real
repository, not a copy: a replayed body changes it, which is the point of replaying, so
a caller must confirm before replaying (#181's later items). **Probes are not made
read-only either.** A probe that writes is refused -- `runtime.probes` snapshots the
environment around it -- but the write is not undone, which on a harness sandbox costs
nothing and on a checkout leaves it in the user's tree. So a dispatcher must probe a
copy of the checkout, never the checkout itself. The mirror shares the
checkout's object store (`objects/info/alternates`), so mirroring copies refs, not
history. `destroy` removes the scratch root and never the checkout.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

from .runtime.probes import repository_bindings
from .sandbox import CheckoutContext, Sandbox, run_git

MIRROR_NAME = "upstream-mirror.git"
"""The bare repository under the scratch root that stands in for the upstream remote."""

BLOCKED_NAME = "no-remote-reachable.git"
"""A path under the scratch root that is never created. Every remote other than the
upstream is redirected here, so model-authored git can neither fetch from it nor push to
it -- in a fork, `origin` is the user's own repository on the network, and a solve on a
disposable copy must not change it."""


class NotACheckoutError(ValueError):
    """The path is not the top level of a git working tree."""


def _user_git(work: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """git as the user runs it: their environment, config and credentials.

    Used for exactly two trusted, fixed operations -- reading their identity and the
    remote's URL, and the one pre-fetch -- and never for model-authored text, which
    always goes through `sandbox.run_env`.
    """
    return subprocess.run(
        ["git", *args], cwd=work, env=dict(os.environ), capture_output=True, text=True, check=check
    )


def _identity(work: Path) -> tuple[str, str] | None:
    name = _user_git(work, "config", "user.name", check=False).stdout.strip()
    email = _user_git(work, "config", "user.email", check=False).stdout.strip()
    return (name, email) if name and email else None


def _remote_urls(work: Path, remote: str) -> list[str]:
    """Every URL git would use for `remote`: its fetch URLs and its push URLs, in order.

    A push URL (`remote.<name>.pushurl`) can differ from the fetch URL, and a redirect that
    covered only the fetch URL would leave `git push <remote>` reaching the real one.
    """
    urls: list[str] = []
    for args in (("--all",), ("--push", "--all")):
        listed = _user_git(work, "remote", "get-url", *args, remote, check=False).stdout
        urls.extend(url for url in listed.splitlines() if url and url not in urls)
    return urls


def _mirror(work: Path, root: Path, remote: str) -> Path:
    """A local bare repository holding `remote`'s fetched branches.

    The mirror borrows the checkout's objects through `alternates`, so only refs are
    written: `refs/remotes/<remote>/*` become the mirror's `refs/heads/*`, which is what
    the real remote's branches look like to a fetch.
    """
    mirror = root / MIRROR_NAME
    run_git(("init", "-q", "--bare", str(mirror)), cwd=root)
    objects = run_git(("rev-parse", "--git-path", "objects"), cwd=work).stdout.strip()
    alternates = mirror / "objects" / "info" / "alternates"
    alternates.write_text(str((work / objects).resolve()) + "\n", encoding="utf-8")
    run_git(
        ("fetch", "-q", "--no-tags", str(work), f"refs/remotes/{remote}/*:refs/heads/*"),
        cwd=mirror,
    )
    head = run_git(
        ("symbolic-ref", "--short", f"refs/remotes/{remote}/HEAD"), cwd=work, check=False
    ).stdout.strip()
    if head.startswith(f"{remote}/"):
        run_git(("symbolic-ref", "HEAD", f"refs/heads/{head[len(remote) + 1 :]}"), cwd=mirror)
    return mirror


def _redirects(work: Path, root: Path, upstream: str | None) -> tuple[tuple[str, str], ...]:
    """Where each remote URL is read from during a run: the mirror, or nowhere.

    The upstream remote's every URL -- fetch and push -- goes to the mirror, so a program
    reads what the trusted pre-fetch brought down and a push lands in the mirror. Every
    other remote's URLs go to `BLOCKED_NAME`, which does not exist, so they fail without
    reaching the network. The first mapping of a URL wins, so an `origin` that shares the
    upstream's URL still reads the mirror.
    """
    pairs: list[tuple[str, str]] = []
    if upstream is not None:
        mirror = _mirror(work, root, upstream)
        pairs.extend((str(mirror), url) for url in _remote_urls(work, upstream))
    blocked = str(root / BLOCKED_NAME)
    remotes = _user_git(work, "remote", check=False).stdout.split()
    for other in remotes:
        if other != upstream:
            pairs.extend((blocked, url) for url in _remote_urls(work, other))
    seen: set[str] = set()
    unique = []
    for base, url in pairs:
        if url not in seen:
            seen.add(url)
            unique.append((base, url))
    return tuple(unique)


def open_checkout(work: Path, *, fetch: bool = True, scratch: Path | None = None) -> Sandbox:
    """`work` as a `Sandbox` the runtime can probe and replay in; `destroy` it when done.

    `fetch` runs the trusted pre-fetch of the derived upstream remote first; turn it
    off to work from what the checkout already has. `scratch` is where the scratch root
    goes (the system temporary directory by default). Raises `NotACheckoutError` when
    `work` is not the top level of a working tree, and `subprocess.CalledProcessError`
    when the pre-fetch fails -- dispatching against a stale remote would observe a
    state the user is not in.
    """
    work = work.resolve()
    top = _user_git(work, "rev-parse", "--show-toplevel", check=False)
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != work:
        raise NotACheckoutError(f"{work} is not the top level of a git working tree")

    parameters = repository_bindings(work)
    remote = parameters.get("upstream_remote")
    if fetch and remote is not None:
        _user_git(work, "fetch", "--quiet", remote)
        parameters = repository_bindings(work)  # a fetch can record the remote's HEAD

    root = Path(tempfile.mkdtemp(prefix="checkout-", dir=scratch))
    return Sandbox(
        root=root,
        work=work,
        upstream=root / MIRROR_NAME,
        checkout=CheckoutContext(
            parameters=parameters,
            identity=_identity(work),
            redirects=_redirects(work, root, remote),
        ),
    )


SNAPSHOT_NAME = "snapshot"
"""The directory under the scratch root that holds a checkout's copy for probing."""


def snapshot(env: Sandbox) -> Sandbox:
    """A copy of the checkout `env` to probe, so a probe that writes cannot touch the original.

    A probe that writes is refused but not undone (`runtime.probes`), so dispatching on a
    checkout probes this copy. It copies the whole working tree with its `.git` -- the
    uncommitted state is part of what a precondition reads, and a fresh clone would lose
    it -- into the scratch root, so `env.destroy` removes it too. The copy keeps the
    checkout's upstream mirror and identity, and binds `work_dir` to itself.

    A linked worktree (whose `.git` is a file pointing into another repository's git
    directory) is refused: its copy would still write into that shared directory.
    """
    context = env.checkout
    if context is None:
        raise ValueError("snapshot copies an existing checkout; a harness sandbox is disposable")
    if (env.work / ".git").is_file():
        raise NotACheckoutError(
            f"{env.work} is a linked worktree; its copy would share the original git directory"
        )
    copy = env.root / SNAPSHOT_NAME
    shutil.copytree(env.work, copy, symlinks=True)
    parameters = {**context.parameters, "work_dir": str(copy)}
    return replace(env, work=copy, checkout=replace(context, parameters=parameters))
