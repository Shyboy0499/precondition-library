# Blind human labels: how to run #299 step 3

The project's labels are its own rules over the observed state. This kit asks independent git
practitioners the same question without showing them the rules, then reports:

- how often each person agrees with the rules;
- how often people agree with each other (Cohen's κ).

You, the owner, run every step except the labelling itself.

## 1. Make the cards, privately

```bash
export HUMAN_LABEL_SALT='<a secret phrase you keep>'
python -m precondition_library.bench.human_labels make \
    --out labelling/cards --key ~/private/human-label-key.json
```

This builds 60 cards: for each of the five measured intents, 8 states of its own fault and 4
fault-free states, drawn from Figure 1's eval seeds. Each card shows:

- the request as a user would send it;
- what the repository shows (status, branches, history, stashes, submodules, the difference from
  upstream, and what a trial merge reports);
- the candidate actions, in neutral words and a random order, plus "nothing needs doing" and
  "none of these is safe".

**Keep the key and the salt to yourself, and never commit either.** This repository is public.
The key maps every card to its state and to our rule's answer. The salt is what makes the card
ids impossible to recompute.

## 2. Give each rater the cards

- Send the `cards/` directory, including its blank `answers.csv`.
- Ask each rater to work alone and fill one letter per card in `answers.csv`.
- A blank answer counts as no answer.
- Name each returned sheet after its rater, for example `ann.csv`.

At least two raters are needed for agreement between people. #299 suggests independent git
practitioners.

## 3. Score

```bash
python -m precondition_library.bench.human_labels score \
    --key ~/private/human-label-key.json ann.csv bob.csv carol.csv
```

The report gives:

- each rater's agreement with the rules: an answer agrees when it is one of the resolutions the
  rules accept, or "nothing" on a state that needs nothing;
- each rater's κ against our labels;
- κ between every pair of raters;
- every card where a rater and the rules disagree.

Commit the scores and the disagreements. Keep out the key, and the cards if the study is still
running.

## What it measures, and what it does not

- **It measures whether people, reading what a user would see, choose what our rules choose.**
  Where they do not, either the rule or the card is wrong. The disagreement list is where to
  look.
- **It does not grade real merges.** Studies 3 and 4 label those by the maintainer's own commit.
