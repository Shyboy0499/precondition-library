<!--
Keep the section headings. Delete the italic guidance once you have filled a section in.
-->

## Summary

*What this changes, in two or three sentences a reader can act on.*

## Linked issue

*`Closes #N` or `References #N`. If there is no issue, explain why not — an unreviewed change
with no recorded reasoning is exactly what this repository's process exists to prevent.*

## What changed

*The specifics. For a design change, name the spec section and say whether it is a clarification
or a reversal.*

## How this was verified

*Commands run and their output. "CI will tell me" is not verification; CI only re-runs what you
already ran.*

---

## Checklist

- [ ] CI is green (ruff, `ruff format --check`, mypy, pytest — run locally first)
- [ ] Linked to an issue, or the absence of one is explained above
- [ ] **Does this change what the experiment measures?** Answered explicitly, either way
- [ ] If it reverses or narrows a decision, an ADR was added under `docs/decisions/`
- [ ] If it adds a citation: checked against the source, with the work's status recorded
      (peer-reviewed / preprint / under review) and its figures verified
- [ ] If it adds a number: the text says where that number came from
- [ ] If it claims something is implemented, enforced, or existing: checked that it actually is
      (stubs and skipped tests are described as such)
- [ ] No claim is stated as a finding. Hypotheses are phrased as hypotheses, intentions as
      intentions, and questions as questions
- [ ] If it touches `runtime/`, the import-isolation test still passes and the change does not
      make a replay able to reach the provider

## Notes for the reviewer

*What you are least sure about, and which decision you would most like challenged. If you are
reviewing your own PR, this section is where you say what a hostile reviewer should attack.*
