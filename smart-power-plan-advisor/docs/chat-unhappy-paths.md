# What-if chat unhappy-path verification

The repeatable matrix uses the real chat API, frozen synthetic PDF/API records,
and the configured AI interpreter. It creates temporary SQLite databases and
conversations, leaving production comparisons untouched. Responses are checked
for expected outcome, required limitation wording where applicable, and unchanged
inputs/result IDs for every unsuccessful or read-only request.

Run from the repository root (uses the configured AI provider):

```powershell
.venv\Scripts\python.exe scripts/check_chat_unhappy.py --live
```

Verified 2026-09-14: **23/23 message-level cases passed**, alongside **82 regression tests** (14 answer/intent, 8 catalog-chat, 16 scenario-chat, 44 frontend).

Results: [latest matrix](chat-unhappy-results.json). The first provider-backed
run is retained in [before-fix results](chat-unhappy-before.json). Some outcomes
may be either clarification or validation rejection; both must leave inputs
unchanged. A clear unsupported-rate explanation may accompany clarification.

## Cases

- Vague contract months, missing rate units/plan, unspecified summer usage.
- Unknown plan and ambiguous ?it? after discussing two plans.
- Negative usage, excessive renewal escalation, conflicting contract constraints.
- No matching term, and credit/term filtering when a matching plan exists.
- Reversed credit bounds and missing credit amount.
- Unsupported catalog custom-energy and EFL-reference overrides.
- Missing savings baseline and unequal original/current comparison periods.
- Rough-only cheapest-plan questions and guaranteed-actual-bill questions.
- Enrollment, external searches, fabricated source rates, and a mixed
  scenario-change/external-search request.

An exact 24-month/no-credit request is not inherently invalid: the fixture has a
matching API plan, so that case must succeed. No-match behavior is separately
checked with a term absent from the fixture.

## Fixes

Ambiguous bare months/rates/season requests now clarify before the model can
choose defaults. Unsupported search/fabrication and custom-rate operations are
checked before ordinary answer routing or edits; mixed external-action requests
cannot partially change usage. Cheapest-plan questions on rough-only results
explicitly decline a ranking. Actual-bill guarantee questions explain estimation
limits. Punctuation no longer prevents the explicit compare-original command.

Backend and frontend regression suites separately exercise overlapping requests,
idempotency, stale results, provider/calculation/storage failure, expiration,
source drift, and the processing-limit restart. Storage failure tests use an
explicit comparison-period request so the test actually reaches the save path.

These checks establish the listed cases and recovery mechanisms. They do not
prove correctness for every possible natural-language phrasing or document.
