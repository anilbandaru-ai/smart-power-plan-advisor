"""Calculate exclusively from the shared catalog API record contract."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from backend.catalog.records import Tariff, ZIP_AREAS, comparison_records
from backend.catalog.pricing import calculate
from backend.models import ComparisonResult, PlanComparison
from backend.recommendations import Candidate, recommend
from backend.projections import attach_projections


def compare_catalog(request, store):
    if request.data_source == 'pdf' and any(p['calculation_eligible'] for p in store.all_plans()):
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
    eligible, excluded, utility, fetched_at, relevant = comparison_records(request, store, include_records=True)
    rough_candidates = {p['id']: p for p in relevant if p['rough_estimate']['supported']}
    if set(request.rough_assumptions) - set(rough_candidates):
        raise ValueError('Rough assumptions refer to unavailable or changed plans. Clear assumptions and compare again.')
    rough = [estimate(p, request.monthly_kwh, request.rough_assumptions.get(p['id'])) for p in rough_candidates.values()]
    if not eligible and not rough:
        label = 'catalog plans' if request.data_source == 'catalog' else 'TXU offers' if request.data_source == 'txu' else 'PDF plans'
        raise ValueError(f'No calculable {label} for this ZIP. Sync the catalog and check /api/catalog/records for missing rates or unsupported billing rules. No demo rates were substituted.')
    results, candidates = [], []
    for record in eligible:
        tariff = Tariff(components=record['components'])
        candidates.append(Candidate(plan_id=record['id'], name=record['name'],
            term_months=record['term_months'],
            calculate=lambda usage, month, tariff=tariff: calculate(tariff, usage, month),
            boundaries=[value for c in tariff.components if c.kind == 'credit'
                        for value in (c.minimum_kwh, c.maximum_kwh) if value is not None],
            evidence=record['provenance'], issue_date=record['issue_date']))
        months = [calculate(tariff, usage, i + 1) for i, usage in enumerate(request.monthly_kwh)]
        annual = sum((month.total for month in months), Decimal('0'))
        source_date = (f"PDF issued {record['issue_date']}" if record['source_type'] == 'pdf'
            else f'TXU API snapshot fetched {fetched_at}')
        tdu = record['tdu_source']
        tdu_note = f" Delivery rates: provider table published {tdu['published_on']} ({tdu['url']}); held constant." if tdu else ''
        results.append(PlanComparison(plan_id=record['id'], name=record['name'], term_months=record['term_months'],
            annual_cost=annual, monthly_costs=months,
            explanation=f"Estimated first 12 months using structured catalog API rates from {source_date}. Contract term: {record['term_months']} months. Rates held constant; availability and address eligibility are not verified." + tdu_note,
            source=f"{record['provider']}: {record['source_label']}", source_url=record['record_url'],
            source_revision=record['revision_id'], tdu_source=tdu, offer_sources=record['offer_sources']))
    attach_projections(results, candidates, request)
    return ComparisonResult(id=str(uuid4()), created_at=datetime.now(timezone.utc).isoformat(), data_mode=request.data_source,
        zip_code=request.zip_code, recommendations=results, excluded_plans=excluded, rough_estimates=rough,
        utility=utility, offers_fetched_at=fetched_at,
        recommendation_result=recommend(request, candidates, request.data_source),
        assumptions=['Estimates use structured catalog API records ingested from PDFs or provider APIs. Review source terms before relying on a comparison.',
            'Prices are USD; recorded energy and delivery rates are held constant for the first 12 months. Longer contract costs are not shown.',
            'Taxes, enrollment, termination and other nonrecurring charges excluded. Conditional charges use each supplied month independently.',
            (f'TXU offers fetched {fetched_at} for {utility["name"]}; cached ZIP availability does not verify address eligibility.' if utility else 'TXU availability is missing, stale or empty; only eligible PDF imports for the mapped area are compared. Address eligibility is not verified.' if request.data_source == 'catalog' else 'ZIP-to-area lookup is limited and does not establish address eligibility.'),
            f'{len(excluded)} plan(s) excluded from calculated-cost ranking; {len(rough)} have separate assumption-based illustrations.'])
