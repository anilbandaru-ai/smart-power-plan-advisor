# Agentic RAG assurance

This upgrade adds ingestion auditing, optional local OCR, document identity,
hybrid retrieval, evidence warnings, independent claim verification, retry
recovery, evaluation and monitoring. **Reranking is not implemented.**

## Ingestion and OCR

Run from the application directory with the existing RAG dependencies:

```powershell
.\.venv\Scripts\python.exe -m backend.knowledge.cli --env-file .env audit
.\.venv\Scripts\python.exe -m backend.knowledge.cli --env-file .env ingest
```

The audit writes `.data/rag-audit.json` (override with `--audit-output`). It lists
selected and excluded PDFs; per-page text tokens, characters, detected tables/rows,
blank/duplicate skips, extraction mode and errors. Audit continues after individual
failures. Ingest refuses selected failures before provider calls. The combined
`update_data.py` workflow also audits before preparation. Preview remains read-only.
Counts describe extraction output, not proof that every visual element was understood.

OCR is optional: install the Tesseract executable locally, then configure
`RAG_OCR_ENABLED=true` and, if needed, `RAG_OCR_COMMAND` with its executable path.
Unreadable nonblank pages are rendered locally at 200 DPI and processed with a
60-second subprocess timeout. Source PDFs are never overwritten. Missing OCR,
poor text, oversized pages or rendering failures require review. OCR pages retain
provenance warnings; native table detection does not reconstruct scanned table
geometry. OCR numbers and alignment still need human review. No OCR provider key,
model download or automatic software installation is added.

## Identity and versions

Ingestion records provider, plan name, term, utility and document date with exact
page/quote evidence using reviewed extraction and a constrained identity-only EFL
header parser. It also stores the PDF hash. Unknown fields remain explicit. This
metadata does not approve a PDF's pricing rules for comparison.

Explicit recognized names constrain retrieval. Similar terms, utilities or
versions trigger clarification; no automatic newest-version selection occurs.
Partial known plan families request the complete name. Unknown layouts still rely
on filenames and question clarification: identity extraction is not universal.
Direct API document scope remains authoritative. The browser searches all documents.
Document dates do not establish current availability. The verifier checks conflicts
in supplied evidence; it cannot discover unseen conflicts throughout the market.

## Hybrid retrieval and complete evidence

`RAG_HYBRID_SEARCH=true` combines up to 16 Pinecone child matches with local BM25
page matches through reciprocal-rank fusion. Full pages, not isolated snippets,
provide the final context. Corpus hash, document hash, filename, page and scope
checks apply to both paths. Duplicate parent pages are merged. Keyword scores
are distinct from vector cosine scores and are not confidence probabilities.

The active manifest contains the local page index. Publishing it remains atomic
after remote upserts; old manifests work with vector fallback until reingested.
`RAG_HYBRID_SEARCH=false` enables the eight-candidate vector baseline. Neither mode
uses a reranker. Pinecone or embedding failures remain retryable provider failures;
the system does not silently represent keyword-only results as hybrid retrieval.

Explicit references such as "see page 2" expand to that page when indexed. At most
four parent pages reach generation. Missing referenced pages, OCR provenance and
document-date uncertainty are included in context. Whole pages preserve available
table headings and footnotes. Implicit continuations and missing external terms
cannot be guaranteed complete; the support verifier must reject unwarranted claims
of completeness. No automatic web fetching of linked documents occurs.

## Claim support and security

Exact excerpt validation runs first. A separate structured model call then checks
every answer unit against selected citations and full source context. All units
must be covered by known source IDs and supported for the correct plan/version;
units, thresholds, exceptions, missing references and conflicts are checked.
Unknown IDs, missing verdicts, unsupported claims, undisclosed conflicts or verifier
failure withhold the answer. Neither the verifier nor retrieved content can invoke
tools. Model-assisted checking improves scrutiny; it is not a mathematical proof
of entailment and can still make mistakes.

The existing decision/generation budget remains six calls; up to two verification
calls bring the maximum to eight per logical turn. Each verifier input has a
12,000-token limit and 1,800-token output cap. This adds latency and provider cost.
Deliberate ungrounded abstentions retain safe generic wording. Document facts in
an abstention still require support. No unverified answer fallback is provided.

## Conversation recovery

Completed retrieval history and duplicate current-turn pages are omitted from
model context while preserving checkpoint evidence and clarification pairs.
New factual turns retrieve fresh evidence. Explicit plan switches are covered by
prompt instructions and regression tests. Provider failures restore the prior
checkpoint and return retryable HTTP 503; the frontend preserves its draft and
request ID. Clarification interruptions are restored as well. Genuine context
limits still require a new conversation. Sessions remain process-local and server
reload clears them. Rollback uses the pinned LangGraph in-memory saver structures;
SDK upgrades require recovery regression tests.

## Evaluation and monitoring

```powershell
.\.venv\Scripts\python.exe -m backend.knowledge.evaluate --env-file .env
.\.venv\Scripts\python.exe -m backend.knowledge.evaluate --env-file .env --answers
```

The default dataset is `docs/rag-assurance-evaluation.json`. Use `--dataset`,
`--output` and `--limit` to control runs. Both modes make retrieval-provider calls;
`--answers` adds generation and claim verification. Reports include expected-page
hits, abstention/fact-pattern checks, failures and latency. These tests are a small
regression set, not a calibrated quality guarantee. Expand it as documents change.
Provider failures and unexpected results cause a nonzero exit code.

`GET /api/knowledge/metrics` exposes process-local aggregate counters for retrieval
misses, verification rejections, failures, latency and token usage. Logs contain
sanitized numeric events, not questions, PDF text, tokens or keys. Counters reset
on restart. Optional `RAG_INPUT_USD_PER_MILLION` and `RAG_OUTPUT_USD_PER_MILLION`
produce a blended model-cost estimate; without configured rates, monetary cost is
null. Estimates exclude Pinecone, OCR infrastructure and failed requests whose
usage is unavailable. No billing-grade accounting or external metrics service
is implied. Keep this unauthenticated local application on loopback.

Structured verification uses the existing [OpenAI structured output API](https://developers.openai.com/api/docs/guides/structured-outputs).

## Verification results (2026-09-13)

- Supplied corpus: 25 PDFs passed audit; 25 have extracted identity fields, with
  41 unique indexed parent pages and 66 child chunks. Published the augmented
  manifest and Pinecone namespace successfully.
- Live evaluation: all 10 cases passed in both vector and hybrid modes (20 checks),
  including unknown-plan, injected-instruction, current-availability and missing-
  terms abstentions. Both modes hit all five scored source targets. This sample
  shows parity, not evidence that hybrid improves overall accuracy. See
  [recorded results](rag-assurance-results.json).
- Live agent: contract term, explicit switch from Frontier to CenterPoint
  SimpleSaver 12, and bill-credit follow-up all answered with citations.
- Full Python run: 193 tests, 190 passed, one skipped, two pre-existing catalog
  problems (Windows symlink privilege and unsupported CenterPoint billing layout).
  Additional assurance tests were added afterward and passed in the targeted run.
- 47 JavaScript UI tests passed. No visual browser validation was performed.
- Local Tesseract is not installed. OCR subprocess behavior is tested with mocks;
  actual OCR accuracy on scanned PDFs has not been evaluated on this machine.

A short live smoke attempt lost its in-memory session while backend auto-reload
was applying code changes; a fresh conversation completed the three-turn check.
