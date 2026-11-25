"""Just enough of npm's semver to ask "does this installed version satisfy this range?".

Ranges npm accepts but this does not understand (git URLs, tarballs, `file:`, dist-tags, `*`
with odd suffixes) return `None` from `satisfies`, and the caller skips the check rather than
guessing. Covered: exact versions, comparators, `^`, `~`, x-ranges, hyphen ranges, `||`, and
npm's rule that a prerelease satisfies a range only through a comparator on the same
`major.minor.patch`.
"""

from __future__ import annotations

import re

Version = tuple[int, int, int, tuple[str, ...]]

_VERSION = re.compile(
    r"^\s*v?=?\s*(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?\s*$"
)
_PARTIAL = re.compile(
    r"^v?(\d+|[xX*])(?:\.(\d+|[xX*]))?(?:\.(\d+|[xX*]))?(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)
_COMPARATOR = re.compile(r"^(<=|>=|<|>|=|\^|~>?)?\s*(.*)$")


def parse_version(text: str) -> Version | None:
    match = _VERSION.match(text)
    if not match:
        return None
    major, minor, patch, pre = match.groups()
    return int(major), int(minor), int(patch), tuple(pre.split(".")) if pre else ()


def _pre_key(pre: tuple[str, ...]) -> tuple[tuple[int, int | str], ...]:
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in pre)


def _compare(a: Version, b: Version) -> int:
    if a[:3] != b[:3]:
        return -1 if a[:3] < b[:3] else 1
    if a[3] == b[3]:
        return 0
    if not a[3]:
        return 1
    if not b[3]:
        return -1
    ka, kb = _pre_key(a[3]), _pre_key(b[3])
    return -1 if ka < kb else (1 if ka > kb else 0)


Comparator = tuple[str, Version]


def _partial(text: str) -> tuple[list[int | None], tuple[str, ...]] | None:
    match = _PARTIAL.match(text)
    if not match:
        return None
    parts = [None if p is None or p in "xX*" else int(p) for p in match.groups()[:3]]
    # A wildcard makes everything after it a wildcard too: `1.x.3` is `1.x`.
    for i, part in enumerate(parts):
        if part is None:
            parts[i + 1 :] = [None] * (2 - i)
            break
    pre = tuple(match.group(4).split(".")) if match.group(4) else ()
    return parts, pre


def _expand(operator: str, text: str) -> list[Comparator] | None:
    """One range token -> the comparators it means (`[]` is "any version")."""
    if text in ("", "*", "x", "X") and operator in ("", "="):
        return []
    parsed = _partial(text)
    if parsed is None:
        return None
    (major, minor, patch), pre = parsed
    if major is None:
        return [] if operator in ("", "=", ">=", "<=") else None
    if operator in ("", "="):
        if minor is None:
            return [(">=", (major, 0, 0, ())), ("<", (major + 1, 0, 0, ("0",)))]
        if patch is None:
            return [(">=", (major, minor, 0, ())), ("<", (major, minor + 1, 0, ("0",)))]
        return [("=", (major, minor, patch, pre))]
    if operator == "^":
        low = (major, minor or 0, patch or 0, pre)
        if major > 0 or minor is None:
            high = (major + 1, 0, 0, ("0",))
        elif minor > 0 or patch is None:
            high = (0, minor + 1, 0, ("0",))
        else:
            high = (0, 0, patch + 1, ("0",))
        return [(">=", low), ("<", high)]
    if operator in ("~", "~>"):
        low = (major, minor or 0, patch or 0, pre)
        high = (major + 1, 0, 0, ("0",)) if minor is None else (major, minor + 1, 0, ("0",))
        return [(">=", low), ("<", high)]
    if operator in (">", "<=") and (minor is None or patch is None):
        # `>1` means `>=2.0.0`; `<=1.2` means `<1.3.0`.
        if minor is None:
            edge = (major + 1, 0, 0, ("0",) if operator == "<=" else ())
        else:
            edge = (major, minor + 1, 0, ("0",) if operator == "<=" else ())
        return [(">=" if operator == ">" else "<", edge)]
    return [(operator, (major, minor or 0, patch or 0, pre))]


def _hyphen(left: str, right: str) -> list[Comparator] | None:
    low, high = _partial(left), _partial(right)
    if low is None or high is None:
        return None
    (lm, ln, lp), lpre = low
    (hm, hn, hp), hpre = high
    out: list[Comparator] = []
    if lm is not None:
        out.append((">=", (lm, ln or 0, lp or 0, lpre)))
    if hm is not None:
        if hn is None:
            out.append(("<", (hm + 1, 0, 0, ("0",))))
        elif hp is None:
            out.append(("<", (hm, hn + 1, 0, ("0",))))
        else:
            out.append(("<=", (hm, hn, hp, hpre)))
    return out


def _tokens(text: str) -> list[str]:
    # `>= 1.2.3` and `>=1.2.3` are the same token.
    return re.sub(r"(<=|>=|<|>|=|\^|~>?)\s+", r"\1", text.strip()).split()


def parse_range(text: str) -> list[list[Comparator]] | None:
    """`a || b` -> one comparator list per alternative, or `None` if any part is not a range."""
    alternatives: list[list[Comparator]] = []
    for alternative in text.split("||"):
        tokens = _tokens(alternative)
        comparators: list[Comparator] = []
        if len(tokens) == 3 and tokens[1] == "-":
            hyphen = _hyphen(tokens[0], tokens[2])
            if hyphen is None:
                return None
            alternatives.append(hyphen)
            continue
        for token in tokens:
            match = _COMPARATOR.match(token)
            if match is None:
                return None
            expanded = _expand(match.group(1) or "", match.group(2))
            if expanded is None:
                return None
            comparators.extend(expanded)
        alternatives.append(comparators)
    return alternatives


def _test(operator: str, version: Version, bound: Version) -> bool:
    c = _compare(version, bound)
    return {
        "=": c == 0,
        "<": c < 0,
        "<=": c <= 0,
        ">": c > 0,
        ">=": c >= 0,
    }[operator]


def satisfies(version_text: str, range_text: str) -> bool | None:
    """Whether `version_text` is in `range_text`, or `None` when either cannot be read."""
    version = parse_version(version_text)
    if version is None:
        return None
    if range_text.startswith("npm:"):
        # An alias, `npm:name@range`: the range is after the last `@`.
        _, _, range_text = range_text[4:].rpartition("@")
    alternatives = parse_range(range_text)
    if alternatives is None:
        return None
    for comparators in alternatives:
        if not all(_test(op, version, bound) for op, bound in comparators):
            continue
        if version[3] and not any(
            bound[3] and bound[:3] == version[:3] for _, bound in comparators
        ):
            continue
        return True
    return False
