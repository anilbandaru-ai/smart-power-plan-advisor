from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from backend.catalog.models import ExtractedPlan
from backend.catalog.average import calculate_custom
from backend.models import ComparisonResult, PlanComparison
from backend.projections import attach_projections
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
    usable = []
    for record in eligible:
        examples = record['plan'].get('examples', [])
        if not examples or len({e['kwh'] for e in examples}) != len(examples):
            excluded.append({'plan_id': record['id'], 'name': record['plan']['name']['value'],
                'reasons': ['Unique published EFL average-price examples are required']})
        else:
            usable.append(record)
    eligible = usable
    if not eligible:
        raise ValueError('No calculable PDF plans with unique published EFL average-price examples for this ZIP.')
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
        evidence.extend({"kind": "pdf", "url": record['document_url'], "revision_id": record['revision_id'],
            "page": example.evidence.page, "quote": example.evidence.quote, "field": "average_price"}
            for example in plan.examples)
        if plan.tdu_lookup and plan.tdu_lookup.source:
            evidence.append({"kind": "delivery_source", **plan.tdu_lookup.source.model_dump(mode='json')})
        renewal_plan = ExtractedPlan.model_validate(record['renewal_plan']) if record.get('renewal_plan') else None
        candidates.append(Candidate(plan_id=record['id'], name=plan.name.value,
            term_months=int(plan.contract_term.value),
            calculate=lambda usage, month, plan=plan: calculate_custom(plan, usage, month),
            boundaries=[value for component in plan.components if component.kind == "credit"
                for value in (component.minimum_kwh, component.maximum_kwh) if value is not None], pricing_basis="custom_efl",
            evidence=evidence, issue_date=plan.issue_date.value,
            renewal_calculate=(lambda usage, month, plan=renewal_plan: calculate_custom(plan, usage, month)) if renewal_plan else None))
        months = [calculate_custom(plan, usage, i + 1) for i, usage in enumerate(request.monthly_kwh)]
        annual = sum((month.total for month in months), Decimal('0'))
        tdu = plan.tdu_lookup.source if plan.tdu_lookup and plan.tdu_lookup.status == 'resolved' else None
        results.append(PlanComparison(plan_id=record['id'], name=plan.name.value, term_months=int(plan.contract_term.value),
            annual_cost=annual, monthly_costs=months, pricing_basis="custom_efl",
            efl_price_examples=[{"kwh": example.kwh, "cents_per_kwh": example.cents_per_kwh,
                "page": example.evidence.page, "quote": example.evidence.quote} for example in plan.examples],
            explanation=f'Estimated first 12 months using mapped EFL average prices from the PDF issued {plan.issue_date.value}. Document contract term: {plan.contract_term.value} months. Custom estimate: mapped average replaces the energy rate; PDF fees and delivery are added and eligible credits subtracted. This repeats effects embedded in EFL averages and is not a tariff-derived bill.',
            source=f"{plan.provider.value}: {record['sources'][0]}", source_url=record['document_url'],
            source_revision=record['revision_id'], tdu_source=tdu.model_dump(mode='json') if tdu else None))
    attach_projections(results, candidates, request)
    return ComparisonResult(id=str(uuid4()), created_at=datetime.now(timezone.utc).isoformat(), data_mode='pdf',
        zip_code=request.zip_code, recommendations=results, excluded_plans=excluded,
        recommendation_result=recommend(request, candidates, "pdf"),
        assumptions=['PDF-derived estimates, not live offers or independently approved tariffs. Review source terms before relying on a comparison.',
            'Custom estimate = kWh times mapped EFL average / 100 + PDF base/usage fees + delivery - eligible credits. This repeats effects already embedded in the published average; it is not an actual tariff bill.',
            'Published averages describe example usage points. Applying them across the requested ranges is an approximation; taxes and nonrecurring charges are not added. Renewal escalation applies to the mapped energy rate, base and delivery. Renewal credit retention/drop applies to separately calculated credits.',
            'ZIP-to-area lookup is limited and does not establish address eligibility.',
            f'{len(excluded)} plan(s) excluded because rates or pricing rules cannot be calculated with monthly usage alone.'])
