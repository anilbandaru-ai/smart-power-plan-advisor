from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from backend.catalog.models import ExtractedPlan
from backend.catalog.pricing import calculate
from backend.models import ComparisonResult, PlanComparison
from backend.recommendations import Candidate, recommend

ZIP_AREAS = {'75201': 'Oncor', '75001': 'Oncor', '77002': 'CenterPoint', '77007': 'CenterPoint'}


def compare_catalog(request, store):
    area = ZIP_AREAS.get(request.zip_code)
    if area is None:
        raise ValueError('This ZIP is not mapped to a delivery area. Supported lookup ZIPs: 75201, 75001, 77002, 77007; address eligibility is not verified.')
    records = store.all_plans()
    relevant = [r for r in records if (r['plan'].get('service_area') or {}).get('value') == area]
    eligible = [r for r in relevant if r['calculation_eligible']]
    excluded = [{'plan_id': r['id'], 'name': (r['plan'].get('name') or {}).get('value', r['sources'][0]), 'reasons': r['calculation_issues']} for r in relevant if not r['calculation_eligible']]
    if not eligible:
        raise ValueError('No calculable PDF plans for this ZIP. Run catalog sync and check /api/catalog/status and /api/catalog/plans for missing rates or unsupported rules. No demo rates were substituted.')
    results, candidates = [], []
    for record in eligible:
        plan = ExtractedPlan.model_validate(record['plan'])
        evidence = [{"kind": "pdf", "url": record['document_url'],
            "revision_id": record['revision_id'], "filename": record['sources'][0],
            "page": component.evidence.page, "quote": component.evidence.quote}
            for component in plan.components if component.evidence.page is not None]
        for key in ('name', 'contract_term', 'issue_date', 'termination_terms'):
            fact = getattr(plan, key)
            if fact:
                evidence.append({"kind": "pdf", "url": record['document_url'],
                    "revision_id": record['revision_id'], "page": fact.evidence.page,
                    "quote": fact.evidence.quote, "field": key})
        if plan.tdu_lookup and plan.tdu_lookup.source:
            evidence.append({"kind": "delivery_source", **plan.tdu_lookup.source.model_dump(mode='json')})
        candidates.append(Candidate(plan_id=record['id'], name=plan.name.value,
            term_months=int(plan.contract_term.value),
            calculate=lambda usage, month, plan=plan: calculate(plan, usage, month),
            boundaries=[value for component in plan.components if component.kind == 'credit'
                        for value in (component.minimum_kwh, component.maximum_kwh) if value is not None],
            evidence=evidence, issue_date=plan.issue_date.value))
        months = [calculate(plan, usage, i + 1) for i, usage in enumerate(request.monthly_kwh)]
        annual = sum((month.total for month in months), Decimal('0'))
        tdu = plan.tdu_lookup.source if plan.tdu_lookup and plan.tdu_lookup.status == 'resolved' else None
        tdu_note = f' Delivery rates: provider table published {tdu.published_on} ({tdu.url}); held constant.' if tdu else ''
        results.append(PlanComparison(plan_id=record['id'], name=plan.name.value, term_months=int(plan.contract_term.value),
            annual_cost=annual, monthly_costs=months,
            explanation=f'Estimated first 12 months using rates in the PDF issued {plan.issue_date.value}. Document contract term: {plan.contract_term.value} months. Rates held constant; availability and address eligibility are not verified.' + tdu_note,
            source=f"{plan.provider.value}: {record['sources'][0]}", source_url=record['document_url'],
            source_revision=record['revision_id'], tdu_source=tdu.model_dump(mode='json') if tdu else None))
    results.sort(key=lambda p: (p.annual_cost, p.plan_id))
    return ComparisonResult(id=str(uuid4()), created_at=datetime.now(timezone.utc).isoformat(), data_mode='pdf',
        zip_code=request.zip_code, recommendations=results, excluded_plans=excluded,
        recommendation_result=recommend(request, candidates, "pdf"),
        assumptions=['PDF-derived estimates, not live offers or independently approved tariffs. Review source terms before relying on a comparison.',
            'Prices are USD; PDF energy rates and explicitly sourced delivery rates held constant for the first 12 months. Longer contract costs are not shown.',
            'Taxes, enrollment, termination and other nonrecurring charges excluded. Conditional charges use each supplied month independently.',
            'ZIP-to-area lookup is limited and does not establish address eligibility.',
            f'{len(excluded)} plan(s) excluded because rates or pricing rules cannot be calculated with monthly usage alone.'])
