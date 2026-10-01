# ADR-0015 — Arm 2c dispatches by the normalised request string and abstains on a conflicting key

- **Status:** accepted (2026-10-01)
- **Date:** 2026-10-01
- **Supersedes:** nothing (second of issue #7's four baselines; ADR-0014 is the first)
- **Deciders:** repository owner

## Context

Issue #7 asks for "arm 2c, exact/parameterized intent-key dispatch, the cheapest
credible competitor". Without it, neither dispatcher is tested against a trivial
lookup: if a table keyed on the request string does as well as text similarity
or executable preconditions, the comparison between those two was not measuring
what it claimed.

Two facts about this task family shape the design. First, the episode runner
always sends the **uninformed** request phrasing (`FaultSpec.task_text` samples
the shared distribution), and those phrasings are chosen so the text does not
determine the resolution: one sentence recurs across states that need different
resolutions. Second, the phrasings carry no slot values -- no paths, branch names
or commit ids -- so "parameterised" has little to abstract here.

A lookup keyed on the request therefore meets **conflicting keys**: one key under
which admitted programs implement two or more resolutions. What the lookup does
then decides how strong a competitor it is, and that was the owner's call.

## Decision

1. **The key** is `intent_key.intent_key(text)`: lower-cased, with quoted strings,
   path-like tokens, commit ids (hex with at least one digit) and numbers replaced by
   placeholders, then punctuation dropped and whitespace collapsed. A program's key
   is the key of the request it was compiled from, `Provenance.compiled_from_task`,
   which the compile step records verbatim. A test pins that every shipped phrasing
   keeps a key of its own, so normalisation never makes the table coarser than the
   text.
2. **The abstain rule** (`intent_key.agreeing`, the owner's choice): when every
   admitted program under the key implements one variant, the key fires (the first
   by id); when they implement two or more, it **abstains** and the episode falls
   back exactly as on a miss. The rule reads only the library, never ground truth.
3. Arm 2c (`Arm.INTENT_KEY`) is a **dispatching** arm, run through the same path as
   arms 2 and 3: the same runtime, guard, checker, fallback, compile-on-fallback in
   the online mode, demotion and quarantine, and the same frozen-library mode. Its
   matcher lives behind the library seam (`Library.match_intent_key`) and
   `dispatch.py` only calls it, as for the other two. It has no score, so
   `dispatch_score` stays arm 2's alone and 2c is one operating point, like arm 3.
4. The pair-level analysis gets the same rule (`bench.coverage.intent_key_outcomes`),
   so the arm the episodes run and the arm the primary metric could measure share
   one definition.
5. The runner's arm-to-matcher selection becomes an explicit table (`bench.run._dispatch`)
   that raises for an arm it does not list, replacing an if/else whose final branch
   ran arm 3's matcher for any arm not named earlier.

## Consequences

**Accepted:** on the uninformed regime a lookup can only be right when its key
happens to be unambiguous in the library, so 2c's coverage will be low there and
its abstentions many. That is the honest behaviour of a lookup on this task
family, not a weakness introduced by the rule. With "last write wins" it would
instead fire on most keys and misfire by construction.

**Gained:** the trivial competitor #7 asks for, in its strongest fair form. If
arm 2 or arm 3 cannot beat it at matched coverage, the claim between them is not
worth stating.

**New obligations:** the key is the compile-time request text, so a library whose
programs carry no real request (hand-written gold) gives 2c nothing to fire;
2c is measured on a compiled library (#4's frozen build), not on gold.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Last write wins (a plain cache) | The most literal lookup, but on a phrasing that recurs across states it fires whichever state was stored last and misfires by construction. That makes it a straw man, the failure #7 exists to prevent. |
| Majority variant under the key, abstaining on a tie | Rewards whichever state happened to recur most in the admit set. That is a property of the seed plan, not of the request, so the lookup would be scored partly on scheduling. |
| Key on the intent *family* (classify the request, then fire that intent's most recent program) | Needs a request classifier, which is arm 2's job under another name, and it ignores the state entirely, so it would mostly duplicate 2c's abstain cases as misfires. |
| Key on the compiled program's `intent` field | That field is free text the compile model writes, not the request; keying on it would measure how consistently the model names things. `compiled_from_task` is the request as recorded. |

## What would reverse this decision

- An informed-regime episode run, where wording reveals the resolution: there a
  plain cache would be nearly right, and the abstain rule's caution would cost
  coverage for no gain in mismatch. That would argue for reporting both rules.
- Requests that carry real slot values (paths, branches, ticket ids). The
  parameterisation would then be load-bearing, and its placeholder set would
  need its own validation rather than a unit test.
