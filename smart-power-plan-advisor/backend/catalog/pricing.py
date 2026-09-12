"""Deterministic rules. Unsupported or incomplete tariffs never enter ranking."""
import re
from hashlib import sha256
from decimal import Decimal
from backend.models import MonthlyCost
from backend.services import money


def applies(component, usage):
    low, high = component.minimum_kwh, component.maximum_kwh
    return ((low is None or (usage >= low if component.minimum_inclusive else usage > low))
            and (high is None or (usage <= high if component.maximum_inclusive else usage < high)))


def calculate(plan, usage, month):
    totals = {key: Decimal('0') for key in ('energy', 'base_fee', 'delivery', 'credit')}
    for component in plan.components:
        if not applies(component, usage):
            continue
        value = component.amount * usage / 100 if component.unit == 'cents_per_kwh' else component.amount
        group = {'energy': 'energy', 'base': 'base_fee', 'usage_charge': 'base_fee',
                 'delivery_fixed': 'delivery', 'delivery_energy': 'delivery', 'credit': 'credit'}[component.kind]
        totals[group] += value
    totals = {key: money(value) for key, value in totals.items()}
    return MonthlyCost(month=month, kwh=usage, **totals,
        total=money(totals['energy'] + totals['base_fee'] + totals['delivery'] - totals['credit']))


def numbers(text):
    return {Decimal(value.replace(',', '')) for value in re.findall(r'\d[\d,]*(?:\.\d+)?', text)}


def validate(plan, pages):
    issues = list(plan.unsupported_rules)
    if plan.tdu_lookup and plan.tdu_lookup.status != 'resolved':
        issues.append(plan.tdu_lookup.detail)
    texts = {page['page']: ' '.join(page['text'].split()) for page in pages}
    def evidence_ok(evidence):
        return evidence.url is None and evidence.page is not None and ' '.join(evidence.quote.split()) in texts.get(evidence.page, '')
    for key in ('name', 'provider', 'service_area', 'issue_date', 'product_type', 'contract_term', 'termination_terms'):
        fact = getattr(plan, key)
        if fact and (not evidence_ok(fact.evidence) or fact.value.casefold() not in fact.evidence.quote.casefold()):
            issues.append(f'{key}: value/quote does not match source')
    for key in ('name', 'provider', 'service_area', 'issue_date', 'product_type', 'contract_term'):
        if getattr(plan, key) is None:
            issues.append(f'Missing {key}')
    if plan.service_area and plan.service_area.value not in ('Oncor', 'CenterPoint'):
        issues.append('Unmapped service area')
    if plan.product_type and not plan.product_type.value.lower().startswith('fixed'):
        issues.append('Only fixed-rate products supported')
    term = int(plan.contract_term.value) if plan.contract_term and plan.contract_term.value.isdigit() else 0
    if term < 12:
        issues.append('Contract does not cover the 12-month comparison horizon')
    raw = ' '.join(texts.values()).lower()
    for phrase in ('free nights', 'free overnight', 'free days', 'free flex', 'summer bill credit', 'energy charge: (>'):
        if phrase in raw:
            issues.append(f'Unsupported pricing rule: {phrase}')
    by_kind = {}
    for component in plan.components:
        by_kind.setdefault(component.kind, []).append(component)
        if component.evidence.url:
            from backend.catalog.tdu import APPROVED_URLS, parse_date
            source = plan.tdu_lookup.source if plan.tdu_lookup and plan.tdu_lookup.status == 'resolved' else None
            valid = (source is not None and source.url in APPROVED_URLS and component.evidence.url == source.url
                and component.evidence.page is None and plan.service_area is not None
                and source.service_area == plan.service_area.value
                and sha256(source.snapshot.encode()).hexdigest() == source.sha256
                and component.evidence.quote in source.snapshot
                and component.kind in ('delivery_fixed', 'delivery_energy')
                and component.amount == (source.monthly_usd if component.kind == 'delivery_fixed' else source.cents_per_kwh))
            if valid:
                try: valid = plan.issue_date is not None and parse_date(source.published_on) <= parse_date(plan.issue_date.value)
                except ValueError: valid = False
            if not valid: issues.append(f'{component.kind}: invalid external TDU provenance')
        elif not evidence_ok(component.evidence):
            issues.append(f'{component.kind}: invalid source excerpt')
        quoted = numbers(component.evidence.quote)
        derived_zero = component.kind == 'base' and component.amount == 0 and component.evidence.quote in (
            'The price you pay each month includes the Energy Charge, Usage Credit and TDU Delivery Charges in effect for your monthly billing cycle.',
            'The above price disclosure is based on the following prices:')
        if component.amount not in quoted and not derived_zero:
            issues.append(f'{component.kind}: amount not present in source excerpt')
        expected = 'cents_per_kwh' if component.kind in ('energy', 'delivery_energy') else 'usd_per_month'
        if component.unit != expected:
            issues.append(f'{component.kind}: incompatible unit')
        if any(v is not None and (v < 0 or v not in quoted) for v in (component.minimum_kwh, component.maximum_kwh)):
            issues.append(f'{component.kind}: invalid or unquoted usage boundary')
        if component.minimum_kwh is not None and component.maximum_kwh is not None and component.minimum_kwh > component.maximum_kwh:
            issues.append(f'{component.kind}: reversed usage range')
        if component.kind in ('energy', 'delivery_energy', 'delivery_fixed', 'base') and (component.minimum_kwh is not None or component.maximum_kwh is not None):
            issues.append(f'{component.kind}: tiered/conditional rate not supported')
    for key in ('energy', 'delivery_energy', 'delivery_fixed'):
        if len(by_kind.get(key, [])) != 1:
            issues.append(f'Exactly one stated {key} charge required')
    if len(by_kind.get('base', [])) > 1:
        issues.append('Multiple base charges unsupported')
    if 'base' not in by_kind and 'usage_charge' not in by_kind:
        issues.append('No stated base or usage charge; review needed')
    if any(component.minimum_kwh is None and component.maximum_kwh is None for component in by_kind.get('usage_charge', [])):
        issues.append('Usage charge needs an explicit applicability range')
    checks = []
    complete_rates = all(len(by_kind.get(key, [])) == 1 for key in ('energy', 'delivery_energy', 'delivery_fixed'))
    for example in plan.examples:
        if not evidence_ok(example.evidence) or not {Decimal(example.kwh), example.cents_per_kwh} <= numbers(example.evidence.quote):
            issues.append('Invalid average-price example evidence')
            continue
        if not complete_rates:
            checks.append({'kwh': example.kwh, 'stated_cents_per_kwh': str(example.cents_per_kwh), 'passed': None,
                'status': 'not_checked', 'reason': 'Required recurring rates are missing or unsupported'})
            continue
        actual = calculate(plan, Decimal(example.kwh), 1).total * 100 / example.kwh
        passed = abs(actual - example.cents_per_kwh) <= Decimal('0.15')
        checks.append({'kwh': example.kwh, 'stated_cents_per_kwh': str(example.cents_per_kwh),
                       'calculated_cents_per_kwh': str(actual), 'passed': passed})
        if not passed:
            issues.append(f'Price example mismatch at {example.kwh} kWh')
    if {c['kwh'] for c in checks} != {500, 1000, 2000}:
        issues.append('Missing standard 500/1000/2000 kWh price examples')
    return list(dict.fromkeys(issues)), checks
