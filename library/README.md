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
    └── history.jsonl    # status changes with the episode that caused them
```

Two rules keep this directory trustworthy:

1. **A program here has passed admission.** Postconditions held on a freshly
   faulted sandbox, and its preconditions rejected every negative sandbox. A
   program that has not passed both lives in `bench/` scratch space, not here.
2. **Nothing is deleted.** A program that mis-fired is marked `demoted` or
   `quarantined` and stays. Removing it would erase the mismatch evidence that
   the primary claim depends on.

`status` is the field to read first:

| status | meaning |
| --- | --- |
| `candidate` | compiled, not yet admitted; never replayed |
| `admitted` | passed the two-sided admission gate; dispatchable |
| `demoted` | fired on a real episode, postconditions failed |
| `quarantined` | withdrawn from dispatch, retained for analysis |

`admitted` was previously named `verified`. The rename is deliberate: a program
that passed *this project's own* gate has not been verified by anyone, and the
word would imply an assurance the gate cannot confer. Nothing was lost in the
rename — no program has been through admission yet.
