"""BM25 page retrieval and reciprocal-rank fusion; no reranker."""
import math
import re
from collections import Counter

STOP = set("what is are the a an of for and or in to its this that about please tell me".split())


def tokens(text):
    return [t for t in re.findall(r"[a-z]+|\d+(?:\.\d+)?", text.lower()) if t not in STOP]


def keyword_search(question, manifest, allowed=None, limit=16):
    pages = [p for p in manifest.get("search_pages", [])
             if allowed is None or p["metadata"]["document_id"] in allowed]
    query = set(tokens(question))
    if not pages or not query:
        return []
    counts = [Counter(tokens(p["metadata"]["filename"] + " " + p["metadata"]["parent_text"])) for p in pages]
    lengths = [sum(c.values()) for c in counts]
    avg = sum(lengths) / len(pages) or 1
    df = {t: sum(t in c for c in counts) for t in query}
    ranked = []
    for page, count, length in zip(pages, counts, lengths):
        score = sum(math.log(1 + (len(pages) - df[t] + .5) / (df[t] + .5)) *
                    count[t] * 2.2 / (count[t] + 1.2 * (.25 + .75 * length / avg))
                    for t in query if count[t])
        if score:
            ranked.append({**page, "score": 0, "keyword_score": score})
    return sorted(ranked, key=lambda p: (-p["keyword_score"], p["id"]))[:limit]


def fuse(vector, lexical):
    values, scores = {}, Counter()
    for ranking in (vector, lexical):
        seen = set()
        for rank, match in enumerate(ranking, 1):
            key = match["metadata"]["parent_id"]
            if key in seen:
                continue
            seen.add(key)
            values.setdefault(key, match)
            scores[key] += 1 / (60 + rank)
    return [{**values[k], "rank_score": scores[k]} for k in sorted(scores, key=lambda k: (-scores[k], k))]


def enrich(matches, manifest, allowed=None):
    """Attach identity and explicit referenced pages without fabricating missing text."""
    docs = {d["id"]: d for d in manifest["documents"]}
    page_map = {(r["metadata"]["document_id"], r["metadata"]["page"]): r for r in manifest.get("search_pages", [])}
    result, seen = [], set()
    for match in matches:
        meta = match["metadata"]
        key = (meta["document_id"], meta["page"])
        if key in seen or (allowed is not None and key[0] not in allowed):
            continue
        result.append(match); seen.add(key)
        refs = set(int(n) for n in re.findall(r"(?:see|on|continued on)\s+page\s+(\d+)", meta["parent_text"], re.I))
        for number in sorted(refs):
            neighbor = page_map.get((key[0], number))
            if neighbor and (key[0], number) not in seen:
                result.append({**neighbor, "score": 0, "keyword_score": 1})
                seen.add((key[0], number))
        if len(result) >= 4:
            break
    output = []
    selected = {(m["metadata"]["document_id"], m["metadata"]["page"]) for m in result[:4]}
    for rank, match in enumerate(result[:4]):
        meta = dict(match["metadata"])
        doc = docs[meta["document_id"]]
        refs = [int(n) for n in re.findall(r"(?:see|on|continued on)\s+page\s+(\d+)", meta["parent_text"], re.I)]
        warnings = []
        if any((meta["document_id"], n) not in selected for n in refs):
            warnings.append("Referenced pages are missing from context; do not claim complete conditions.")
        if meta.get("extraction") == "ocr":
            warnings.append("OCR-derived text; table alignment and numeric accuracy are not independently verified.")
        date = doc.get("identity", {}).get("facts", {}).get("issue_date", {}).get("value")
        warnings.append(f"Document issue date: {date or 'unknown'}; current offer availability is unverified.")
        meta.update(identity=doc.get("identity", {}), document_version=doc["sha256"], warnings=warnings)
        output.append({**match, "metadata": meta, "rank_score": 1 / (rank + 1)})
    return output
