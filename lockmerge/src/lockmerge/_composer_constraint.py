"""Just enough of Composer's version constraints to ask "does this locked version satisfy this
requirement?". Unreadable constraints (`dev-` branches, `as` aliases, odd stabilities) return
`None` and are not judged."""

from __future__ import annotations

import re

Version = tuple[tuple[int, ...], int, tuple[int | str, ...]]
"""(numeric parts padded to 4, stability rank, stability suffix)."""

_STABILITY = {"dev": 0, "alpha": 1, "a": 1, "beta": 2, "b": 2, "rc": 3, "": 4, "p": 5, "patch": 5}
_VERSION = re.compile(
    r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?"
    r"(?:[-.]?(?P<stability>alpha|beta|rc|a|b|p|patch|pl)[.-]?(?P<n>\d+)?)?$",
    re.IGNORECASE,
)


def parse_version(text: str) -> Version | None:
    match = _VERSION.match(text.strip())
    if not match:
        return None
    numbers = tuple(int(n) if n is not None else 0 for n in match.groups()[:4])
    stability = (match.group("stability") or "").lower().replace("pl", "p")
    suffix = (int(match.group("n")),) if match.group("n") else ()
    return numbers, _STABILITY[stability], suffix


def _dev(version: Version) -> Version:
    """Composer reads `>=1.2` as `>=1.2.0.0-dev`: a bound with no stability admits prereleases."""
    return (version[0], 0, ()) if version[1:] == (4, ()) else version


def _bounds(token: str) -> list[tuple[str, Version]] | None:
    token = re.sub(r"@\w+$", "", token.strip())
    if not token or token == "*":
        return []
    for op in (">=", "<=", "!=", "==", ">", "<", "="):
        if token.startswith(op):
            version = parse_version(token[len(op) :])
            if version is None:
                return None
            if op in (">=", "<"):
                version = _dev(version)
            return [({"==": "="}.get(op, op), version)]
    if token[0] in "^~":
        version = parse_version(token[1:])
        if version is None:
            return None
        parts = [int(p) for p in re.findall(r"\d+", token[1:])][:4]
        low = _dev(version)
        if token[0] == "~":
            # ~1.2 -> <2.0; ~1.2.3 -> <1.3
            significant = max(len(parts) - 1, 1)
        else:
            # ^1.2.3 -> <2; ^0.3 -> <0.4; ^0.0.3 -> <0.0.4
            significant = next((i + 1 for i, p in enumerate(parts) if p != 0), len(parts))
            significant = min(significant, len(parts))
        upper = [*parts[: significant - 1], parts[significant - 1] + 1] if parts else [1]
        upper += [0] * (4 - len(upper))
        return [(">=", low), ("<", (tuple(upper), 0, ()))]
    if "*" in token or re.search(r"\.x$", token, re.IGNORECASE):
        parts = [int(p) for p in re.findall(r"\d+", token)]
        if not parts:
            return []
        floor = tuple(parts + [0] * (4 - len(parts)))
        ceiling = [*parts[:-1], parts[-1] + 1]
        ceiling += [0] * (4 - len(ceiling))
        return [(">=", (floor, 0, ())), ("<", (tuple(ceiling), 0, ()))]
    version = parse_version(token)
    if version is None:
        return None
    return [("=", version)]


def _test(op: str, version: Version, bound: Version) -> bool:
    a, b = version, bound
    if op == "=":
        return a[0] == b[0] and (a[1], a[2]) == (b[1], b[2])
    if op == "!=":
        return not _test("=", version, bound)
    return {">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b}[op]


def satisfies(version_text: str, constraint: str) -> bool | None:
    """Whether a locked version is within a requirement, or `None` when either is unreadable."""
    version = parse_version(version_text)
    if version is None or " as " in constraint or "dev-" in constraint:
        return None
    for alternative in re.split(r"\s*\|\|?\s*", constraint.strip()):
        if " - " in alternative:
            left, right = alternative.split(" - ", 1)
            low, high = parse_version(left), parse_version(right)
            if low is None or high is None:
                return None
            bounds = [(">=", low), ("<=", high)]
        else:
            bounds = []
            for token in re.split(r"\s*,\s*|\s+", alternative.strip()):
                parsed = _bounds(token)
                if parsed is None:
                    return None
                bounds.extend(parsed)
        if all(_test(op, version, bound) for op, bound in bounds):
            return True
    return False
