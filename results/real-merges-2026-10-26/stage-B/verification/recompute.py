"""Independent recomputation of stage B from its JSON outputs; imports nothing from the project."""

import json
import math
import random
import sys
from collections import Counter, defaultdict
from fractions import Fraction

d = sys.argv[1]
cases = {c["index"]: c for c in json.load(open(f"{d}/manifest.json"))["cases"]}
labels = {r["index"]: r for r in map(json.loads, open(f"{d}/labels.jsonl"))}
dec = {r["index"]: r for r in map(json.loads, open(f"{d}/decisions.jsonl"))}
assert cases.keys() == labels.keys() == dec.keys()
idx = sorted(cases)
N = len(idx)
print(
    "cases",
    N,
    Counter(cases[i]["kind"] for i in idx),
    "repos",
    len({cases[i]["repo"] for i in idx}),
)
print(
    "per repo",
    Counter(cases[i]["repo"] for i in idx).most_common(),
    "cap 25% of 247 =",
    int(0.25 * 247),
)


def wilson_low(k, n, z=1.959963984540054):
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / den


def wrong(i, v):
    return v not in labels[i]["acceptable"]


def point(rows, thr):  # rows: (i, variant, score)
    fired = [
        (i, v)
        for i, v, s in rows
        if v is not None and (thr is None or (s is not None and s >= thr))
    ]
    return fired


def matched(rows, target_n, n_total):
    thrs = sorted({s for _, v, s in rows if v is not None and s is not None})
    best = None
    for t in thrs:
        f = point(rows, t)
        if not f:
            continue
        cov = Fraction(len(f), n_total)
        key = (abs(cov - Fraction(target_n, n_total)), cov)
        if best is None or key < best[0]:
            best = (key, t, f)
    return best[1], best[2]


def mm(f):
    return sum(wrong(i, v) for i, v in f) / len(f) if f else None


for r, name in enumerate(("run-11", "run-12", "run-13")):
    a3 = [(i, dec[i]["arm3"][r]) for i in idx if dec[i]["arm3"][r] is not None]
    w3 = sum(wrong(i, v) for i, v in a3)
    by = Counter((cases[i]["kind"], wrong(i, v)) for i, v in a3)
    a2rows = [(i, dec[i]["arm2"][r][0], dec[i]["arm2"][r][1]) for i in idx]
    ctrows = [
        (
            i,
            dec[i]["control"][0] if dec[i]["control"] else None,
            dec[i]["control"][1] if dec[i]["control"] else None,
        )
        for i in idx
    ]
    t2, f2 = matched(a2rows, len(a3), N)
    tc, fc = matched(ctrows, len(a3), N)
    print(
        f"\n{name}: arm3 fires {len(a3)}/{N}, wrong {w3}, mismatch {w3 / len(a3):.3f},"
        f" Wilson low {wilson_low(w3, len(a3)):.3f}"
        f"  rule2 falsified: {wilson_low(w3, len(a3)) > 0.10}"
    )
    print(
        "  arm3 by (kind, wrong):", dict(by), " variants:", Counter(v for _, v in a3).most_common(5)
    )
    print(
        f"  arm2 matched: fires {len(f2)}, wrong {sum(wrong(i, v) for i, v in f2)},"
        f" d1 = {mm(f2) - w3 / len(a3):+.3f}"
    )
    print(
        f"  control matched: fires {len(fc)}, wrong {sum(wrong(i, v) for i, v in fc)},"
        f" d2 = {mm(fc) - w3 / len(a3):+.3f};"
        f" control variants {Counter(v for _, v in fc).most_common(4)}"
    )
    s3 = {i for i, _ in a3}
    sc = {i for i, _ in fc}
    print(
        f"  jointly fired with control: {len(s3 & sc)};"
        f" control fires by kind {Counter(cases[i]['kind'] for i in sc)}"
    )
    # H3: conflicted cases with empty acceptable set
    empty = [i for i in idx if cases[i]["kind"] == "positive" and not labels[i]["acceptable"]]
    f3 = sum(1 for i in empty if i in s3)
    fcc = sum(1 for i in empty if i in sc)
    print(
        f"  H3 cases {len(empty)}: arm3 fires {f3}, control fires {fcc},"
        f" diff {fcc / len(empty) - f3 / len(empty):+.3f}"
    )
    # repository-clustered bootstrap, own RNG
    repos = sorted({cases[i]["repo"] for i in idx})
    byrepo = defaultdict(list)
    for i in idx:
        byrepo[cases[i]["repo"]].append(i)
    rng = random.Random(12345)
    ds1 = []
    ds2 = []
    for _ in range(2000):
        pick = [i for rp in (rng.choice(repos) for _ in repos) for i in byrepo[rp]]
        # duplicate cases get distinct keys
        keyed = list(enumerate(pick))
        n = len(keyed)
        a3b = [(k, dec[i]["arm3"][r], i) for k, i in keyed if dec[i]["arm3"][r] is not None]
        if not a3b:
            continue
        m3 = sum(wrong(i, v) for _, v, i in a3b) / len(a3b)
        for rowsrc, out in (
            (lambda i: (dec[i]["arm2"][r][0], dec[i]["arm2"][r][1]), ds1),
            (
                lambda i: (
                    (dec[i]["control"][0], dec[i]["control"][1])
                    if dec[i]["control"]
                    else (None, None)
                ),
                ds2,
            ),
        ):
            rows = [(k, *rowsrc(i)) for k, i in keyed]
            mp = {k: i for k, i in keyed}
            try:
                _, f = matched(rows, len(a3b), n)
            except TypeError:
                continue
            if f is None:
                continue
            out.append(sum(wrong(mp[k], v) for k, v in f) / len(f) - m3)
    for nm, ds in (("H1", ds1), ("H2", ds2)):
        ds.sort()
        lo, hi = ds[int(0.025 * len(ds))], ds[int(0.975 * len(ds)) - 1]
        print(f"  {nm} own bootstrap ({len(ds)}): [{lo:+.3f}, {hi:+.3f}]")
