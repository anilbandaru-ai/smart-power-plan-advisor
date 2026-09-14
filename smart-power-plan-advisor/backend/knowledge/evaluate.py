"""Compare retrieval modes with versioned fixtures; optional paid answer checks."""
import argparse
import json
import re
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from backend.knowledge.config import Settings
from backend.knowledge.evidence import select_context, validate_answer
from backend.knowledge.models import DocumentIdentityError
from backend.knowledge.monitoring import snapshot


def run(settings, cases, answers=False, factory=None):
    if factory is None:
        from backend.knowledge.providers import Providers
        factory = Providers
    manifest = settings.manifest()
    rows = []
    for mode in ("vector", "hybrid"):
        provider = factory(replace(settings, hybrid_search=mode == "hybrid"))
        try:
            provider.connect()
            for case in cases:
                row = {"id": case["id"], "mode": mode, "answer_checked": answers}
                start = perf_counter()
                try:
                    doc = next((d for d in manifest["documents"] if d["filename"] == case.get("document")), None)
                    if case.get("document") and not doc:
                        raise ValueError("Fixture document is absent")
                    matches = provider.retrieve(case["question"], manifest, doc["id"] if doc else None)
                    context = select_context(matches, manifest, doc["id"] if doc else None)
                    expected = {(x["filename"], x["page"]) for x in case.get("expected_sources", [])}
                    actual = {(x["filename"], x["page"]) for x in context}
                    row.update(retrieval_hit=bool(expected & actual) if expected else None,
                               sources=[{"filename": x[0], "page": x[1]} for x in sorted(actual)])
                    if answers:
                        result = validate_answer(provider.generate(case["question"], context), context) if context else None
                        abstained = result is None or result.abstained
                        row.update(abstained=abstained,
                            answer_pass=(abstained == case["expected_abstention"] and
                              (abstained or all(re.search(p, result.answer, re.I) for p in case.get("fact_patterns", [])))))
                except DocumentIdentityError:
                    row.update(clarification=True, answer_pass=case.get("expected_clarification", False) if answers else None)
                except Exception as error:
                    row.update(error=type(error).__name__)
                row["latency_ms"] = round((perf_counter()-start)*1000, 2)
                rows.append(row)
        finally:
            provider.close()
    summary = {}
    for mode in ("vector", "hybrid"):
        group = [r for r in rows if r["mode"] == mode]
        scored = [r for r in group if r.get("retrieval_hit") is not None]
        summary[mode] = {"cases":len(group), "retrieval_hits":sum(r["retrieval_hit"] for r in scored),
            "retrieval_scored":len(scored), "failures":sum("error" in r for r in group),
            "answer_passes":sum(r.get("answer_pass") is True for r in group) if answers else None}
    return {"corpus_id":manifest["corpus_id"], "hybrid_index_available":"search_pages" in manifest,
            "results":rows, "summary":summary, "metrics":snapshot()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file')
    parser.add_argument('--dataset',default='docs/rag-assurance-evaluation.json')
    parser.add_argument('--output',default='.data/rag-evaluation.json')
    parser.add_argument('--answers',action='store_true')
    parser.add_argument('--limit',type=int)
    args=parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file,override=False)
    cases=json.loads(Path(args.dataset).read_text(encoding='utf-8'))['cases']
    if args.limit is not None: cases=cases[:args.limit]
    result=run(Settings.from_env(),cases,args.answers)
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result['summary'],indent=2))
    if any(r.get('error') or r.get('retrieval_hit') is False or r.get('answer_pass') is False for r in result['results']):
        raise SystemExit(1)


if __name__ == '__main__':main()
