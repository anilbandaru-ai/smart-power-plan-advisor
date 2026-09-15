"""Calculate exclusively from the shared catalog API record contract."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from types import SimpleNamespace
from backend.catalog.average import calculate_custom
from backend.catalog.records import Tariff, ZIP_AREAS, comparison_records
from backend.catalog.pricing import calculate
from backend.models import ComparisonResult, PlanComparison
from backend.recommendations import Candidate, recommend
from backend.projections import attach_projections


def compare_catalog(request, store, *, frozen_records=None, utility=None, fetched_at=None):
    if frozen_records is None and request.data_source == 'pdf' and any(p['calculation_eligible'] for p in store.all_plans()):
        from backend.catalog.pdf_custom import compare_pdf_custom
        result = compare_pdf_custom(request, store)
        if not any(not p['calculation_eligible'] for p in store.all_plans()):
            return result
        from backend.catalog.rough import estimate
        _, _, _, _, relevant = comparison_records(request, store, include_records=True)
        rough = [p for p in relevant if p['rough_estimate']['supported']]
        if set(request.rough_assumptions) - {p['id'] for p in rough}:
            raise ValueError('Rough assumptions refer to unavailable or changed plans.')
        result.rough_estimates = [estimate(p, request.monthly_kwh, request.rough_assumptions.get(p['id'])) for p in rough]
        return result
    from backend.catalog.rough import estimate
    if frozen_records is None:
        eligible, excluded, utility, fetched_at, relevant = comparison_records(request, store, include_records=True)
    else:
        relevant = frozen_records
        eligible = [p for p in relevant if p['calculation_eligible']]
        excluded = [{'plan_id': p['id'], 'name': p['name'], 'reasons': p['calculation_issues']} for p in relevant if not p['calculation_eligible']]
    rough_candidates = {p['id']: p for p in relevant if p['rough_estimate']['supported']}
    if set(request.rough_assumptions) - set(rough_candidates):
        raise ValueError('Rough assumptions refer to unavailable or changed plans. Clear assumptions and compare again.')
    rough = [estimate(p, request.monthly_kwh, request.rough_assumptions.get(p['id']), reviewed_capability=p.get('_scenario_rough_capability')) for p in rough_candidates.values()]
    if not eligible and not rough:
        label = 'catalog plans' if request.data_source == 'catalog' else 'TXU offers' if request.data_source == 'txu' else 'PDF plans'
        raise ValueError(f'No calculable {label} for this ZIP. Sync the catalog and check /api/catalog/records for missing rates or unsupported billing rules. No demo rates were substituted.')
    results, candidates = [], []
    for record in eligible:
        custom = record['source_type'] == 'pdf' and (frozen_records is None or record.get('_comparison_pricing_basis') == 'custom_efl')
        examples = record.get('examples', [])
        if custom and (not examples or len({e['kwh'] for e in examples}) != len(examples)):
            excluded.append({'plan_id': record['id'], 'name': record['name'],
                             'reasons': ['Unique published EFL examples are required for range-based Energy.']})
            continue
        basis = 'custom_efl' if custom else 'components'
        calculator = calculate_custom if custom else calculate
        tariff = SimpleNamespace(components=Tariff(components=record['components']).components,
            examples=[SimpleNamespace(kwh=Decimal(str(e['kwh'])), cents_per_kwh=Decimal(str(e['cents_per_kwh']))) for e in examples])
        renewal = SimpleNamespace(components=Tariff(components=record['_scenario_renewal_components']).components,
            examples=tariff.examples) if record.get('_scenario_renewal_components') else None
        candidates.append(Candidate(plan_id=record['id'], name=record['name'],
            term_months=record['term_months'],
            calculate=lambda usage, month, tariff=tariff, calculator=calculator: calculator(tariff, usage, month), pricing_basis=basis,
            boundaries=[value for c in tariff.components if c.kind == 'credit'
                        for value in (c.minimum_kwh, c.maximum_kwh) if value is not None],
            evidence=record['provenance'] + ([e['evidence'] for e in examples if e.get('evidence')] if custom else []), issue_date=record['issue_date'],
            renewal_calculate=(lambda usage, month, tariff=renewal, calculator=calculator: calculator(tariff, usage, month)) if renewal else None))
        months = [calculator(tariff, usage, i + 1) for i, usage in enumerate(request.monthly_kwh)]
        annual = sum((month.total for month in months), Decimal('0'))
        source_date = (f"PDF issued {record['issue_date']}" if record['source_type'] == 'pdf'
            else f'TXU API snapshot fetched {fetched_at}')
        tdu = record['tdu_source']
        tdu_note = f" Delivery rates: provider table published {tdu['published_on']} ({tdu['url']}); held constant." if tdu else ''
        results.append(PlanComparison(plan_id=record['id'], name=record['name'], term_months=record['term_months'],
            annual_cost=annual, monthly_costs=months, pricing_basis=basis,
            efl_price_examples=[dict(kwh=example['kwh'], cents_per_kwh=example['cents_per_kwh'],
                page=example['evidence']['page'], quote=example['evidence']['quote'])
                for example in record.get('examples', [])
                if record['source_type'] == 'pdf' and (example.get('evidence') or {}).get('page')],
            explanation=("Custom estimate: Energy uses range-mapped EFL averages; source fees and delivery are added and eligible credits subtracted. This repeats effects embedded in published averages and is not an actual tariff bill. " if custom else "") + f"Estimated first 12 months using {'mapped EFL references and source charges' if custom else 'structured catalog API rates'} from {source_date}. Contract term: {record['term_months']} months. Initial-contract rates held constant; later months use renewal assumptions; availability and address eligibility are not verified." + tdu_note,
            source=f"{record['provider']}: {record['source_label']}", source_url=record['record_url'],
            source_revision=record['revision_id'], tdu_source=tdu, offer_sources=record['offer_sources']))
    attach_projections(results, candidates, request)
    return ComparisonResult(id=str(uuid4()), created_at=datetime.now(timezone.utc).isoformat(), data_mode=request.data_source,
        zip_code=request.zip_code, recommendations=results, excluded_plans=excluded, rough_estimates=rough,
        utility=utility, offers_fetched_at=fetched_at,
        recommendation_result=recommend(request, candidates, request.data_source),
        assumptions=['PDF custom estimates use range-mapped EFL averages for Energy plus source fees/delivery minus credits. This repeats effects embedded in EFL averages. API offers retain their own component pricing. Review source terms.',
            'Prices are USD; recorded energy and delivery rates are held constant during the initial contract. Months after that term use the selected renewal assumptions.',
            'Taxes, enrollment, termination and other nonrecurring charges excluded. Conditional charges use each supplied month independently.',
            (f'TXU offers fetched {fetched_at} for {utility["name"]}; cached ZIP availability does not verify address eligibility.' if utility and fetched_at else f"Delivery utility: {utility['name']}, resolved independently of plan offers. Address eligibility remains unverified." if utility else 'TXU availability is missing, stale or empty; only eligible PDF imports for the mapped area are compared. Address eligibility is not verified.' if request.data_source == 'catalog' else 'ZIP-to-area lookup is limited and does not establish address eligibility.'),
            f'{len(excluded)} plan(s) excluded from calculated-cost ranking; {len(rough)} have separate assumption-based illustrations.'])
