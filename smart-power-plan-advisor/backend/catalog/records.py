"""Shared API view of SQLite snapshots. Neither reads nor pricing open source PDFs.

Adapters are the ingestion-format boundary. API routes and comparisons use these
same records; original extraction/offer fields remain available for audit.
"""
import json
import re
from decimal import Decimal
from hashlib import sha256
from typing import Literal
from pydantic import Field
from backend.catalog.models import Strict, DecimalValue
from backend.catalog.pricing import calculate
from backend.providers.txu import BASE, TxuError, normalized_rates

CONTRACT_VERSION = 'catalog-v1'
ZIP_AREAS = {'75201': 'Oncor', '75001': 'Oncor', '77002': 'CenterPoint', '77007': 'CenterPoint'}


class PricingComponent(Strict):
    kind: Literal['energy', 'energy_tier', 'base', 'delivery_fixed', 'delivery_energy', 'usage_charge', 'credit']
    amount: DecimalValue = Field(ge=0, max_digits=14, decimal_places=6)
    unit: Literal['cents_per_kwh', 'usd_per_month']
    minimum_kwh: DecimalValue | None = None
    minimum_inclusive: bool = True
    maximum_kwh: DecimalValue | None = None
    maximum_inclusive: bool = False


class Tariff(Strict):
    components: list[PricingComponent] = Field(max_length=30)


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def finish(record):
    record['schema_version'] = CONTRACT_VERSION
    record['record_url'] = f"/api/catalog/records/{record['id']}"
    record['calculation_issues'] = list(dict.fromkeys(record['calculation_issues']))
    record['calculation_eligible'] = not record['calculation_issues']
    from backend.catalog.rough import public_capability
    record['rough_estimate'] = public_capability(record)
    return record


def pdf_record(record):
    plan = record['plan']
    def value(key):
        return (plan.get(key) or {}).get('value')
    components = [{k: v for k, v in c.items() if k != 'evidence'} for c in plan['components']]
    evidence = []
    for key, item in list(plan.items()) + [('components', c) for c in plan['components']]:
        if isinstance(item, dict) and item.get('evidence'):
            evidence.append({'kind': 'pdf' if item['evidence'].get('page') else 'delivery_source',
                'url': item['evidence'].get('url') or record['document_url'],
                'revision_id': record['revision_id'], 'filename': record['sources'][0], 'field': key, **item['evidence']})
            # A PDF excerpt has no external URL; retain the locally verified document link.
            evidence[-1]['url'] = item['evidence'].get('url') or record['document_url']
    tdu = plan.get('tdu_lookup') or {}
    if tdu.get('source'):
        evidence.append({'kind': 'delivery_source', **tdu['source']})
    return finish(dict(id=record['id'], revision_id=record['revision_id'], source_type='pdf',
        name=value('name') or record['sources'][0], provider=value('provider'),
        service_area=value('service_area'), contract_term=value('contract_term'), term_months=int(value('contract_term')) if (value('contract_term') or '').isdigit() else None,
        issue_date=value('issue_date'), zip_code=None, utility_id=None,
        components=components, examples=plan['examples'],
        calculation_issues=record['calculation_issues'], price_checks=record['price_checks'],
        provenance=evidence, source_details=plan, source_documents=record['source_documents'],
        document_url=record['document_url'], source_label=record['sources'][0],
        tdu_source=tdu.get('source') if tdu.get('status') == 'resolved' else None,
        offer_sources=[]))


def txu_record(offer, utility, zip_value, fetched_at):
    raw = offer.get('raw') or {}
    issues, components, checks = [], [], []
    url = f'{BASE}/plans/?utilityId={utility["id"]}&zipCode={zip_value}'
    identity = digest(['txu', zip_value, utility['id'], offer['external_id']])[:24]
    revision = digest([CONTRACT_VERSION, raw])
    if raw.get('active') is not True or raw.get('hideOnGrid') is not False:
        issues.append('Offer is inactive or hidden by TXU')
    if (raw.get('utility') or {}).get('id') != utility['id'] or (raw.get('supplier') or {}).get('name') != 'TXU Energy':
        issues.append('API provider or utility does not match the listing')
    term = raw.get('term') if isinstance(raw.get('term'), dict) else {}
    length = term.get('length')
    if raw.get('type') != 'Fixed' or term.get('type') != 'FixedMonths' or type(length) is not int or length < 12:
        issues.append('API tariff must be fixed and cover at least 12 months')
    marketing = ' '.join(str(raw.get(k) or '') for k in
        ('name', 'description', 'secondaryDescription', 'features', 'badges', 'incentivesFull')).casefold()
    if raw.get('billCredits') or re.search(r'credit|cash\s*back', marketing):
        issues.append('API bill credit or cashback rules are not fully modeled')
    if re.search(r'solar|buyback|free|season|summer|winter|time.of.use|weekend|night|tier|usage.charge|minimum.usage|discount', marketing):
        issues.append('API tariff may require unsupported conditional, interval, seasonal or solar rules')
    fees = raw.get('fees', [])
    if not isinstance(fees, list):
        issues.append('API fee list is invalid')
        fees = []
    if not isinstance(raw.get('billCredits'), list):
        issues.append('API bill credit list is missing or invalid')
    for fee in fees:
        if not isinstance(fee, dict) or fee.get('monthly') is not False or fee.get('type') != 'EarlyTerminationFee':
            issues.append('API contains an unmodeled fee')
    mapping = {'EnergyCharge': 'energy', 'BaseCharge': 'base',
        'DeliveryChargeKwh': 'delivery_energy', 'DeliveryChargeMonthly': 'delivery_fixed'}
    known = {*mapping, 'FiveHundredKwh', 'OneThousandKwh', 'TwoThousandKwh'}
    rates, grouped = {}, {}
    raw_rates = raw.get('rates')
    if not isinstance(raw_rates, list):
        issues.append('API rate list is missing or invalid')
        raw_rates = []
    for rate in raw_rates:
        if not isinstance(rate, dict) or not isinstance(rate.get('type'), str) or rate['type'] not in known:
            issues.append('API contains an unsupported or malformed rate type')
            continue
        grouped.setdefault(rate['type'], []).append(rate)
    for rate_type, entries in grouped.items():
        if len(entries) != 1:
            issues.append(f'API {rate_type} has duplicate entries; applicability is ambiguous')
            continue
        rate = entries[0]
        if set(rate) - {'type', 'price'}:
            issues.append(f'API {rate_type} has unsupported applicability fields')
            continue
        try:
            rates.update(normalized_rates({'rates': [rate]}))
        except (ValueError, TypeError):
            issues.append(f'API {rate_type} amount is invalid')
    for rate_type, kind in mapping.items():
        if kind not in rates:
            if rate_type not in grouped:
                issues.append(f'API is missing the explicit {kind} charge')
            continue
        try:
            component = PricingComponent(kind=kind, amount=rates[kind],
                unit='cents_per_kwh' if kind in ('energy', 'delivery_energy') else 'usd_per_month')
            components.append(component.model_dump(mode='json'))
        except ValueError:
            issues.append(f'API {rate_type} amount exceeds supported precision or range')
    tariff = Tariff(components=components)
    for usage, rate_type in ((500, 'FiveHundredKwh'), (1000, 'OneThousandKwh'), (2000, 'TwoThousandKwh')):
        if str(usage) not in rates:
            if rate_type not in grouped:
                issues.append(f'API is missing the {usage} kWh price example')
        elif len(components) == 4:
            actual = calculate(tariff, Decimal(usage), 1).total * 100 / usage
            passed = abs(actual - rates[str(usage)]) <= Decimal('0.15')
            checks.append({'kwh': usage, 'stated_cents_per_kwh': str(rates[str(usage)]),
                'calculated_cents_per_kwh': str(actual), 'passed': passed})
            if not passed:
                issues.append(f'API price example mismatch at {usage} kWh')
        else:
            checks.append({'kwh': usage, 'stated_cents_per_kwh': str(rates[str(usage)]),
                'passed': None, 'status': 'not_checked',
                'reason': 'Recurring charges are missing, invalid or ambiguous'})
    source = {'provider': 'TXU Energy', 'external_id': offer['external_id'], 'zip_code': zip_value,
        'utility_id': utility['id'], 'fetched_at': fetched_at, 'revision_id': revision,
        'efl_url': offer.get('efl_url'), 'api_url': url, 'sha256': digest(raw)}
    return finish(dict(id=identity, revision_id=revision, source_type='txu',
        name=offer['name'], provider='TXU Energy', service_area=utility['name'],
        term_months=length if type(length) is int else None, issue_date=None,
        zip_code=zip_value, utility_id=utility['id'], components=components,
        examples=[{'kwh': k, 'cents_per_kwh': str(rates[str(k)])} for k in (500, 1000, 2000) if str(k) in rates],
        calculation_issues=issues, price_checks=checks,
        provenance=[{'kind': 'provider_api', 'url': url, 'fields': ['/rates', '/term', '/fees', '/billCredits'], **source}],
        source_details=raw, source_documents=[], document_url=None,
        source_label=url, tdu_source=None, offer_sources=[source]))


def records(store, source_type=None, zip_value=None, *, txu_snapshot=None):
    """Public contract, including dynamic availability gates from SQLite snapshots."""
    result = []
    if source_type in (None, 'pdf'):
        result.extend(pdf_record(p) for p in store.all_plans())
        if zip_value:
            from backend.catalog.utilities import cached_utilities, area_name
            discovery = cached_utilities(store, zip_value)
            areas = {area_name(u['name']) for u in discovery['utilities']} if discovery and not discovery['stale'] else set() if discovery else {ZIP_AREAS.get(zip_value)}
            result = [p for p in result if area_name(p['service_area'] or '') in areas]
    if source_type in (None, 'txu'):
        from backend.catalog.txu import cached
        if zip_value:
            zips = [zip_value]
        else:
            with store.connection() as db:
                zips = [r[0] for r in db.execute('SELECT DISTINCT zip_code FROM txu_refreshes')]
        for z in zips:
            if zip_value and z != zip_value:
                continue
            data = txu_snapshot if txu_snapshot is not None else cached(store, z)
            utilities = {u['id']: u for u in data['utilities']}
            for offer in data['offers']:
                utility = utilities.get(offer['utility_id'])
                if not utility:
                    continue
                record = txu_record(offer, utility, z, data['fetched_at'])
                if data['stale']:
                    record['calculation_issues'].append('TXU availability is stale; run sync-txu for this ZIP')
                    finish(record)
                result.append(record)
    return sorted(result, key=lambda p: (p['name'], p['id']))


def comparison_records(request, store, *, include_records=False):
    utility, fetched_at, data = None, None, None
    if request.data_source == 'catalog':
        from backend.catalog.txu import cached
        data = cached(store, request.zip_code)
        from backend.catalog.utilities import cached_utilities, area_name
        discovery = cached_utilities(store, request.zip_code)
        if discovery is not None and (discovery['stale'] or not discovery['utilities']):
            raise ValueError('Delivery utility lookup is unavailable or empty for this ZIP. Look up the ZIP again.')
        utilities = discovery['utilities'] if discovery else [] if data['stale'] else data['utilities']
        selected = str(request.utility_id) if request.utility_id else None
        if utilities:
            if not selected and len(utilities) > 1:
                raise ValueError('Multiple utilities serve this ZIP. Select your electric utility before comparing.')
            selected = selected or utilities[0]['id']
            utility = next((u for u in utilities if u['id'] == selected), None)
            if utility is None:
                raise ValueError('Selected utility is not available for this ZIP.')
            fetched_at = data['fetched_at']
        elif selected:
            raise ValueError('Selected utility cannot be verified. Clear the utility selection and try again.')
        area = area_name(utility['name']) if utility else ZIP_AREAS.get(request.zip_code)
        if area is None:
            raise ValueError('No verified delivery-area mapping for this ZIP. Refresh the TXU cache for this ZIP and try again.')
        relevant = [p for p in records(store, 'pdf') if area_name(p['service_area'] or '').casefold() == area.casefold()]
        txu = records(store, 'txu', request.zip_code, txu_snapshot=data)
        relevant.extend(p for p in txu if not utility or p['utility_id'] == utility['id'])
        eligible = [p for p in relevant if p['calculation_eligible']]
        excluded = [{'plan_id': p['id'], 'name': p['name'], 'reasons': p['calculation_issues']}
                    for p in relevant if not p['calculation_eligible']]
        return (eligible, excluded, utility, fetched_at, relevant) if include_records else (eligible, excluded, utility, fetched_at)
    if request.data_source == 'txu':
        from backend.catalog.txu import cached
        data = cached(store, request.zip_code)
        if data['stale']:
            raise ValueError('TXU availability is missing or stale. Run sync-txu for this ZIP, then try again.')
        utilities = data['utilities']
        if not utilities:
            raise ValueError('TXU returned no utilities for this ZIP.')
        selected = str(request.utility_id) if request.utility_id else None
        if not selected and len(utilities) > 1:
            raise ValueError('Multiple utilities serve this ZIP. Select a TXU utility before comparing.')
        selected = selected or utilities[0]['id']
        utility = next((u for u in utilities if u['id'] == selected), None)
        if utility is None:
            raise ValueError('Selected utility is not available for this ZIP.')
        fetched_at = data['fetched_at']
    elif request.zip_code not in ZIP_AREAS:
        raise ValueError('This ZIP is not mapped to a delivery area. Supported lookup ZIPs: 75201, 75001, 77002, 77007; address eligibility is not verified.')
    relevant = records(store, request.data_source, request.zip_code, txu_snapshot=data)
    if utility:
        relevant = [p for p in relevant if p['utility_id'] == utility['id']]
    eligible = [p for p in relevant if p['calculation_eligible']]
    excluded = [{'plan_id': p['id'], 'name': p['name'], 'reasons': p['calculation_issues']}
        for p in relevant if not p['calculation_eligible']]
    return (eligible, excluded, utility, fetched_at, relevant) if include_records else (eligible, excluded, utility, fetched_at)
