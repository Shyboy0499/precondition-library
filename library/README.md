# The program library

Compiled programs live here and **are committed on purpose**. The library is not
build output — it is the artifact the project is about, and its git history is
part of the evidence: a program appearing, a program being demoted after it
mis-fired, a precondition being tightened after a negative sandbox caught it.

Layout, one directory per program:

```
library/
└── <program-id>/
    ├── program.yaml     # intent, parameters, preconditions, body, postconditions
    └── history.jsonl    # status changes, and mismatch events, with the episode
                         # that caused each
```

A mismatch event (`{"event": "mismatch", ...}`) is not a status change: it
records one wrong-variant fire while the program stays `admitted`, and the
second such event moves it to `quarantined` (spec §8). The same file therefore
shows both why and when a program was withdrawn.

Three rules keep this directory trustworthy:

1. **Only an `admitted` program may be dispatched.** A program here has not
   necessarily passed admission: it is stored as a `candidate` — compiled, never
   replayed — and becomes `admitted` only after both sides of the gate pass:
   postconditions held on a freshly faulted sandbox, and its preconditions
   rejected every negative sandbox. A program that fails admission keeps its
   status and stays here rather than moving to a scratch directory; a rejected
   program is data the mismatch analysis needs. `bench/` is working scratch
   space, not where rejected programs go.
2. **Nothing is deleted.** A program that mis-fired is marked `demoted` or
   `quarantined` and stays. Removing it would erase the mismatch evidence that
   the primary claim depends on.
3. **A program on an ambiguous intent must declare one of its resolutions.** Every
   program whose `intent` names an intent with two or more resolutions must carry
   a `variant` equal to one of that intent's declared ids. Admission enforces
   this when it gates a compiled program; because a `program.yaml` can also be
   written straight to disk, `Library.load_all` re-checks the invariant on every
   load. A violating program — `variant: null`, or an id the intent does not
   declare — is marked `quarantined` with the reason written to its
   `history.jsonl`, so it is retained for analysis but can never be dispatched:
   both matchers return only `admitted` programs. The check is per program, so a
   single bad file is withdrawn and the rest of the library still loads. A
   program whose `intent` names no ambiguous intent has no declared set to
   violate and is not covered by this rule.

`status` is the field to read first:

| status | meaning |
| --- | --- |
| `candidate` | compiled, not yet admitted; never replayed |
| `admitted` | passed the two-sided admission gate; dispatchable |
| `demoted` | fired on a real episode and could not work — its body ran but its postconditions failed, or its body named a declared parameter the environment could not bind |
| `quarantined` | withdrawn from dispatch, retained for analysis |

`admitted` was previously named `verified`. The rename is deliberate: a program
that passed *this project's own* gate has not been verified by anyone, and the
word would imply an assurance the gate cannot confer. Nothing was lost in the
rename — no program has been through admission yet.
