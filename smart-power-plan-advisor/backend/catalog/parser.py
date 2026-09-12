"""Recognized EFL labels only. Unknown layouts fall back to review-required extraction."""
import re
import json
from hashlib import sha256
from pathlib import Path
from decimal import Decimal
from backend.catalog.models import ExtractedPlan

N = r'([0-9]+(?:\.[0-9]+)?)'


def layout_fingerprint(pages):
    # Preserve every nonnumeric token/operator; header identity and document dates may vary.
    text = ' '.join(' '.join(page['text'].split()) for page in pages)
    match = re.search(r'Electricity Price|Average Monthly (?:Use|Usage)', text, re.I)
    if match:
        text = text[match.start():]
    text = re.sub(r'[0-9]+(?:[.,][0-9]+)*', '#', text.casefold())
    return sha256(text.encode()).hexdigest()


def parse_known(pages):
    known_layouts = json.loads(Path(__file__).with_name('layouts.json').read_text())
    if layout_fingerprint(pages) not in known_layouts:
        return None
    first = pages[0]['text']
    rows = [line.strip() for line in first.splitlines() if line.strip()]
    normalized = [(page['page'], ' '.join(page['text'].split())) for page in pages]
    text = normalized[0][1]
    header = re.search(r'Electricity Facts Label \(EFL\)\s+(Reliant Energy Retail Services, LLC|U\.S\. Retailers LLC dba Discount Power|Value Based Brands LLC d/b/a 4Change Energy)\s+(.+?)\s+Oncor Electric Delivery(?: service area)?\s+(?:Issue Date:|Date:)', text, re.I)
    if header:
        provider, name = header.group(1), header.group(2)
    else:
        label = next((i for i, row in enumerate(rows) if row.lower() == 'electricity facts label (efl)'), None)
        if label is None or len(rows) < label + 4:
            return None
        provider, name = rows[label + 1], rows[label + 2]
        if not any(v in provider for v in ('Gexa Energy', 'Frontier Utilities', 'AP GAS & ELECTRIC', 'TriEagle Energy', 'TXU Energy')):
            return None
    def proof(quote):
        for page, content in normalized:
            if quote in content:
                return {'page': page, 'quote': quote}
        raise ValueError('Parser excerpt not found')
    def fact(value, quote=None):
        return {'value': value, 'evidence': proof(quote or value)} if value else None
    area = 'Oncor' if re.search(r'\bOncor\b', text) else 'CenterPoint' if 'CenterPoint' in text else None
    joined = ' '.join(t for _, t in normalized)
    # Match each fact on a single original page to preserve provenance.
    def find(pattern):
        for _, content in normalized:
            match = re.search(pattern, content, re.I)
            if match:
                return match
        return None
    date = find(r'(?:Issue Date:|Date:)\s*([A-Za-z]+ \d{1,2}, \d{4}|\d{2}/\d{2}/\d{4})') or find(r'(\d{4}-\d{2}-\d{2}|September \d{1,2}, \d{4})')
    term = find(r'Contract Term:?\s*\|\s*(\d+)\s*months')
    product = find(r'Type of Product:?\s*\|\s*(Fixed Rate|Fixed|Variable)')
    termination = find(r'Do I have a termination fee[^|]+\|\s*([^|]+?)(?= Can my price|$)')
    components, unsupported, notes = [], [], []
    def component(kind, amount, quote, low=None, inclusive=True, high=None, high_inclusive=False):
        components.append(dict(kind=kind, amount=str(amount), unit='cents_per_kwh' if kind in ('energy','delivery_energy') else 'usd_per_month',
            minimum_kwh=low,minimum_inclusive=inclusive,maximum_kwh=high,maximum_inclusive=high_inclusive,evidence=proof(quote)))
    energy = find(r'Energy Charge[: |]+' + N + r'\s*¢\s*per kWh') or find(r'Energy Rate\s*\(¢\)\s*per kWh:\s*' + N + r'\s*¢') or find(r'Energy Charge:\s*Per kWh \(¢\) All kWh\s*' + N + r'\s*¢')
    if energy:
        component('energy', energy.group(1), energy.group(0))
    base = find(r'Base Charge[: |]+\$' + N + r'\s*(?:per billing cycle|per month)') or find(r'Base Charge:\s*Per Month \(\$\)\s*\$?' + N) or find(r'Base Charge \(\$\) per month:\s*\$' + N)
    if base:
        component('base', base.group(1), base.group(0))
    for _, content in normalized:
        for label in re.finditer(r'(?:Oncor Electric Delivery Delivery Charges|Energy Delivery Charges|TDU Delivery Charges)[: |]+',content,re.I):
            rest=content[label.end():]
            fixed=re.match(r'\$'+N+r'\s*per (?:billing cycle|month)(?:\s+and\s+'+N+r'\s*¢\s*per kWh)?',rest,re.I)
            variable=re.match(N+r'\s*¢\s*per kWh(?:\s+and\s+\$'+N+r'\s*per month)?',rest,re.I)
            match=fixed or variable
            if not match:continue
            quote=label.group(0)+match.group(0)
            kinds=['delivery_fixed','delivery_energy'] if fixed else ['delivery_energy','delivery_fixed']
            for kind,amount in zip(kinds,match.groups()):
                if amount is not None and not any(c['kind']==kind for c in components):component(kind,amount,quote)
    usage=find(r'Usage Charge:\s*\$'+N+r'\s*per billing cycle\s*<\s*(\d+)\s*kWh\s*\$'+N+r'\s*per billing cycle\s*≥\s*(\d+)\s*kWh')
    if usage:
        component('usage_charge',usage.group(1),usage.group(0),high=usage.group(2))
        component('usage_charge',usage.group(3),usage.group(0),low=usage.group(4))
    credit=find(r'(?:Monthly Bill Credit|Usage Credit)[: |]+\$'+N+r'\s*(?:Per billing cycle)(?: for usage)?\s*\(?(>=|>|≥)\s*([\d,]+)\)?\s*kWh')
    if credit:
        component('credit',credit.group(1),credit.group(0),low=credit.group(3).replace(',',''),inclusive=credit.group(2)!='>')
    else:
        credit=find(r'A Usage Credit of \$'+N+r'.{0,180}?above or equal to\s*([\d,]+)\s*kWh') or find(r'A bill credit of \$'+N+r'.{0,140}?usage is\s*([\d,]+)\s*kWh or more') or find(r'\$'+N+r' credit when usage is >=\s*([\d,]+)\s*kWh')
        if credit:component('credit',credit.group(1),credit.group(0),low=credit.group(2).replace(',',''))
    # These recognized templates explicitly enumerate all recurring components; no base charge is included.
    if not base and not usage:
        exhaustive=find(r'The price you pay each month includes the Energy Charge, Usage Credit and TDU Delivery Charges in effect for your monthly billing cycle\.')
        if exhaustive:
            component('base','0',exhaustive.group(0));notes.append('Zero base derived from explicit exhaustive recurring-charge list')
        elif provider == 'Frontier Utilities' and 'The above price disclosure is based on the following prices:' in text:
            quote='The above price disclosure is based on the following prices:'
            component('base','0',quote);notes.append('Zero base derived from recognized Frontier exhaustive price table')
    for pattern,label in [(r'Energy Charge:\s*\(', 'Tiered energy rates require a tiered calculator'),(r'Free Overnight|Free Nights|Free Days|Free Flex', 'Interval usage is required for free-time pricing'),(r'summer bill credit','Seasonal credit pricing is not supported'),(r'Type of Product:?\s*\|\s*Variable','Variable-rate pricing is not supported')]:
        if re.search(pattern,joined,re.I):unsupported.append(label)
    # If another credit/usage mechanism exists but wasn't understood, block calculation.
    if re.search(r'(?:Usage Credit|Bill Credit|\$[\d.]+ credit)',text,re.I) and not any(c['kind']=='credit' for c in components):
        unsupported.append('Credit condition could not be parsed')
    if 'Usage Charge:' in text and not usage:unsupported.append('Usage charge could not be parsed')
    examples=[]
    price=find(r'Average Price (?:per kWh|in ¢ per kWh)[: |]+'+N+r'\s*¢\s*\|?\s*'+N+r'\s*¢\s*\|?\s*'+N+r'\s*¢')
    if price:
        for page,content in normalized:
            if price.group(0) in content:
                end=content.index(price.group(0))+len(price.group(0));start=content.lower().rfind('average monthly',0,end)
                quote=content[start:end] if start>=0 else price.group(0)
                for kwh,amount in zip((500,1000,2000),price.groups()):examples.append({'kwh':kwh,'cents_per_kwh':amount,'evidence':proof(quote)})
                break
    return ExtractedPlan.model_validate(dict(name=fact(name),provider=fact(provider),service_area=fact(area),
        issue_date=fact(date.group(1),date.group(0)) if date else None,product_type=fact(product.group(1),product.group(0)) if product else None,
        contract_term=fact(term.group(1),term.group(0)) if term else None,
        termination_terms=fact(termination.group(1).strip(),termination.group(0)) if termination else None,
        components=components,examples=examples,unsupported_rules=unsupported,extraction_notes=notes+['Recognized deterministic EFL parser']))
