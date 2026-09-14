The alternatives panel opens automatically after a comparison: scenario settings
start collapsed and the chat, suggested questions, reset and previous controls are
visible. A remembered session is restored; otherwise a session is created without
changing costs. Controls remain disabled while loading. Initialization failure or
session expiration offers Retry chat while preserving comparison results.

# Comparison scenario chat

Run a comparison, then select **Explore alternatives** in Compare Plan Costs. The existing document assistant remains separate. Chat sits between the recommendation summary and compared plans. Replies default to two-line previews with Show more / Show less controls. Monthly breakdowns use full-width desktop tables, year selection and expandable mobile cards.

Try:

- ?Use a maximum contract length of 36 months.?
- ?Only 24-month contracts.? (Exact term; preserves comparison period.)
- ?Compare over 36 months, with a maximum contract of 24 months.?
- ?Increase June through August usage by 20%.?
- ?Avoid plans with bill credits.?
- ?Set the mapped EFL reference price for SimpleSaver 24 to 8 cents per kWh.?
- ?For SimpleSaver 24, assume no bill credit after renewal.?
- ?Compare with original?, ?Why?, ?Previous?, or ?Reset?.

An explicit plan name and units are needed for overrides. Ambiguous requests are clarified. Usage can be relative to the active or original scenario. Overrides persist until cleared or a previous/original scenario is restored. Published EFL examples stay unchanged; monthly rates reflect hypothetical overrides. Existing custom PDF pricing remains explicitly labeled and is not a tariff bill.

Successful changes update the existing recommendation and monthly tables. Active scenario details show the period, exact/max term, credit filter, usage, baseline and hypothetical assumptions. Changing the main form starts a fresh comparison and does not submit chat-only overrides or filters.

## Persistence and failures

Sessions expire after 24 hours and accept up to 100 committed turns. Their SQLite state includes frozen source records, a branchable scenario history, pending clarification and attempt history. Saved scenario comparisons retain their inputs and frozen records, so a new chat can start from them even if the catalog changes. Starting from an ordinary older comparison requires matching source revisions; old PDF pricing requires explicit migration with ?use current custom formula?.

Invalid/conflicting values, unsupported component overrides and no-match attempts preserve the last successful result. No filters are relaxed automatically. Provider/calculation/storage errors are retryable; successful request IDs are deduplicated with body matching. Concurrent requests use optimistic version checks. The UI blocks overlap, drops stale responses, and offers Reload chat on conflict or restart after expiration. Tokens are stored in browser local storage; this follows the application's local, single-user deployment model.

## Configuration and implementation

Free-form interpretation uses OPENAI_API_KEY and COMPARISON_CHAT_MODEL (falls back to AGENT_MODEL, then gpt-4.1-mini). The adapter uses Responses structured output, a 30-second timeout and no automatic retries. No calculations or writes are delegated to the model. Navigation, explanations and selected explicit commands are deterministic. If the provider is unavailable, previous results remain usable.

Plan filters and independent horizons extend RecommendationOptions. PDF hypothetical overrides use typed fields and validate scope/units before applying a full action to copies. Demo plans support their existing base/delivery/credit fields; PDF-specific reference rates and unsupported demo credit rules require a PDF plan. Baselines remain available for savings even when excluded from recommendations. Original and current costs with different periods or pricing methods are not described as like-for-like savings.

The API is /api/comparison-chat (POST), /{session_id} (GET), and /{session_id}/messages (POST). Session operations require X-Scenario-Token; turns require a UUID request_id and expected version. Updates to active state, saved comparisons and request cache commit in one transaction.

Structured-output integration follows the official [OpenAI Python example](https://github.com/openai/openai-python/blob/main/examples/responses/structured_outputs.py).

## Verification

Automated coverage includes contract/horizon separation, filtered baseline savings, no-match recovery, atomic invalid changes, clarification context, duplicate body matching, stale versions, concurrent commits, provider/calculation/storage failures, expiry, source drift, legacy migration, original/current usage changes, scoped overrides and clearing them, renewal-only credit overrides and saved hypothetical scenarios. Frontend tests check retries, blocked overlap, stale responses after detachment, expiration/conflict recovery and ordinary rendering.

Headless Edge with the real FastAPI app and local PDF catalog exercised clarification, a 24-month scenario, no matches, simulated provider failure, reload, undo, input invalidation and a 390px mobile viewport. Six interpretation cases passed in a final check: four used the configured live model and two used deterministic explicit-command handlers. This is a smoke evaluation, not a guarantee that every natural-language phrasing will be interpreted correctly. No external provider was used for the calculation or persistence tests.

Final targeted results: 15 scenario tests and 31 UI tests passed. Full-suite run: 95/96 Python tests passed, with the existing Windows symlink fixture failure; two further scenario tests were then added and passed in the targeted suite. Python compilation, JavaScript syntax and diff whitespace checks passed.

UI redesign verification: all 33 frontend tests passed. Headless Edge verified inline message expansion, chat placement, year navigation, desktop table width, mobile cards, clarification/no-match/failure recovery, reload and undo. Desktop and 390px mobile screenshots were visually reviewed. No pricing or API changes.

## Combined catalog and TXU comparisons

Explore alternatives is available after successful catalog/TXU comparisons,
including rough-only results. Chat starts with the saved ZIP, selected utility,
usage, preferences and rough assumptions. Source revisions must still match when
starting from a normal saved comparison; an existing conversation continues using
its frozen records without provider calls or catalog changes.

Usage, term/credit preferences, comparison period and renewal scenarios reuse the
saved pricing basis: custom EFL for new catalog PDFs, components for API offers and
older component snapshots. Hypothetical delivery, base/usage and credit components can be edited for calculable
plans. Energy/tier overrides require component pricing; specify
a component index when ambiguous. A mapped EFL average cannot replace a catalog
energy rate. Rough-only plans retain their reviewed assumptions and cannot be
promoted into exact ranking through component overrides.

Reviewed rough profiles are frozen with the session. Rough illustrations remain
12-month estimates even if the calculated-plan period is 24/36 months, and are
labeled separately. Their saved assumptions persist through usage scenarios,
previous/reset and saved-scenario restoration. No rough-only winner is claimed.
PDF/API provenance stays distinct and original source evidence is not rewritten
by hypothetical overrides. The existing OpenAI interpreter configuration is reused;
this integration was tested with mocked interpretation, not live model calls.


Question-specific answers and follow-up focus are implemented in
`backend/scenario/answers.py`. Answers and sources are stored with each turn.
They use frozen catalog terms and saved calculations, without a new RAG search or
AI-generated numerical explanation. Credit threshold probes are read-only. Unknown
plan IDs, multiple possible targets and unsupported details do not invent answers.
The browser shows the answer's beginning and exposes available safe source links
under Show more. A structured conversation_limit error offers a fresh session.


CHAT-25 verification (2026-09-14): 10 answer tests, 6 catalog-chat tests,
16 existing scenario tests and 44 frontend tests passed. A final targeted check
also verified pricing-aware interpreter context and credit-threshold capabilities.
Five live interpretation checks covered bill-credit follow-ups, a 999-kWh query,
usage changes, unsupported custom energy-rate overrides and an unknown plan.
A read-only local SimpleSaver 24 check returned the $125 credit at >=1,000 kWh,
correct saved monthly credits and the page-1 excerpt. These are targeted checks,
not a guarantee of correctness for every natural-language question. No new RAG
retrieval was added; monthly answer summaries currently cover the first year.


Enrollment requests such as "Enroll in SimpleSaver 24" or "Sign me up" are
rejected before AI interpretation. The chat explains that enrollment must happen
with the provider. Mixed enrollment/scenario requests do not partially change the
comparison. Questions about recorded enrollment fees remain information requests.
A pending plan clarification accepts only a bare plan name or ID; mentioning a
plan inside a new command does not turn that command into a clarification answer.


Scenario settings start collapsed; expanding them is preserved during the conversation.
After a submitted question receives a reply, only the internal message area scrolls to the latest answer.
Automatic startup/restoration does not scroll to old replies. Reduced motion is respected.

The empty message area takes no space. Once messages appear, it has a stable, viewport-responsive height. Replies that leave the
comparison unchanged do not rebuild the plan results; changed scenarios still update costs.

Expanded what-if replies use readable paragraphs, emphasized labels, detail lists
and separate source blocks. After each returned answer, the question box regains
keyboard focus without scrolling the page. Initial restoration does not steal focus.

Named comparisons such as "Compare Gexa Saver Plus 12 with SimpleSaver 12"
resolve both exact plans before AI interpretation and preserve the current usage
and horizon. Unknown or ambiguous names prompt clarification. Original-versus-current
comparison is reserved for an explicit original/initial-scenario request.
