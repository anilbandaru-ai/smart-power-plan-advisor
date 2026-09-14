"""Evidence-backed identity; unknown fields never become guessed constraints."""
import re

FIELDS = ("name", "provider", "contract_term", "service_area", "issue_date")


def normalize(value):
    cleaned = re.sub(r"(?<=\d)sm\b|\bplan$", "", str(value).lower()).strip()
    return " ".join(re.findall(r"[a-z0-9]+", cleaned))


def identify(pages):
    from backend.catalog.parser import parse_known
    try:
        plan = parse_known(pages)
    except (ValueError, IndexError, KeyError):
        plan = None
    facts = {}
    if plan:
        for key in FIELDS:
            fact = getattr(plan, key)
            if fact:
                proof = fact.evidence
                page = next((p for p in pages if p["page"] == proof.page), None)
                if page and " ".join(proof.quote.split()) in " ".join(page["text"].split()):
                    facts[key] = {"value": fact.value, "page": proof.page, "quote": proof.quote}
    if not facts and pages:
        rows = [r.strip() for r in pages[0]["text"].splitlines() if r.strip()]
        if (len(rows) >= 5 and rows[0].lower() == "electricity facts label (efl)"
                and re.fullmatch(r"(?:Oncor(?: Electric Delivery)?|CenterPoint(?: Energy)?)(?: service area)?", rows[3], re.I)
                and re.match(r"(?:Issue Date|Date):", rows[4], re.I)):
            for key, quote in zip(("provider", "name", "service_area", "issue_date"), rows[1:5]):
                val = quote.split(":", 1)[1].strip() if key == "issue_date" else quote
                facts[key] = {"value": val, "page": pages[0]["page"], "quote": quote}
            for page in pages:
                term = re.search(r"Contract Term\s*\|?\s*(\d+)\s*[Mm]onths", page["text"])
                if term:
                    facts["contract_term"] = {"value": term.group(1), "page": page["page"], "quote": term.group(0)}
    return {"facts": facts, "missing": [k for k in FIELDS if k not in facts]}


def value(doc, key):
    return doc.get("identity", {}).get("facts", {}).get(key, {}).get("value", "")


def field_key(doc, field):
    normalized = normalize(value(doc, field))
    if field == "service_area":
        for utility in ("centerpoint", "oncor"):
            if re.search(r"\b" + utility + r"\b", normalized):
                return utility
    return normalized


def resolve(question, manifest, scope=None):
    """Only explicitly named known plans constrain search; preserve all versions."""
    docs = manifest["documents"]
    if scope:
        return {scope}, None
    query = normalize(question)
    named = [d for d in docs if value(d, "name") and
             re.search(r"(?:^| )" + re.escape(normalize(value(d, "name"))) + r"(?: |$)", query)]
    if not named:
        families = [(d, re.sub(r"\s+\d+$", "", normalize(value(d, "name")))) for d in docs if value(d, "name")]
        family = [d for d, name in families if name and re.search(r"(?:^| )" + re.escape(name) + r"(?: |$)", query)]
        if family:
            return {d["id"] for d in family}, "Specify the full plan name, contract length and delivery utility; no exact plan identity matched."
        return None, None
    # Longest explicit name avoids matching a short plan name inside a longer one.
    length = max(len(normalize(value(d, "name"))) for d in named)
    named = [d for d in named if len(normalize(value(d, "name"))) == length]
    for field in ("service_area", "provider", "issue_date"):
        specified = [d for d in named if value(d, field) and field_key(d, field) in query]
        if specified:
            named = specified
    distinct = {(value(d, "provider"), value(d, "name"), value(d, "contract_term"),
                 value(d, "service_area"), value(d, "issue_date"), d["sha256"]) for d in named}
    if len(distinct) > 1:
        choices = [f"{value(d, 'name')} / {value(d, 'service_area') or 'unknown utility'} / "
                   f"{value(d, 'issue_date') or 'undated'} ({d['id']})" for d in named]
        return {d["id"] for d in named}, "Multiple document identities or versions match. Specify one: " + "; ".join(choices)
    return {d["id"] for d in named}, None
