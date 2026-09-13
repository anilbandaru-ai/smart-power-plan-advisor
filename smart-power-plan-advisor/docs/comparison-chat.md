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
