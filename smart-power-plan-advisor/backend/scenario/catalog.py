"""Scenario adapters for independent, frozen PDF/API catalog records."""
import copy
from decimal import Decimal
from backend.catalog.records import comparison_records, Tariff
from backend.catalog.rough import capability
from backend.catalog.pricing import energy_structure
from backend.catalog.compare import compare_catalog


def freeze(request, result, store):
    _, _, utility, fetched_at, records = comparison_records(request, store, include_records=True)
    by_id = {r['id']: r for r in records}
    for plan in result.recommendations:
        current = by_id.get(plan.plan_id)
        if not current or not current['calculation_eligible'] or current['revision_id'] != plan.source_revision:
            raise ValueError('The source catalog changed. Compare plans again before starting chat.')
    for plan in result.rough_estimates:
        current = by_id.get(plan['plan_id'])
        if not current or current['revision_id'] != plan['source_revision'] or capability(current).get('source_fingerprint') != plan['source_fingerprint']:
            raise ValueError('A reviewed source changed. Compare plans again before starting chat.')
    # Do not introduce records that were not part of the saved comparison.
    known = {p.plan_id for p in result.recommendations} | {p['plan_id'] for p in result.rough_estimates} | {p['plan_id'] for p in result.excluded_plans}
    frozen = copy.deepcopy([r for r in records if r['id'] in known])
    for record in frozen:
        record['_scenario_utility'] = utility
        record['_scenario_fetched_at'] = fetched_at
        record['_scenario_rough_capability'] = capability(record)
    return frozen


def override_components(components, operations):
    components = copy.deepcopy(components)
    for op in operations:
        field = op['field']
        if field == 'average_price':
            raise ValueError('Catalog component pricing requires an energy rate override, not a mapped EFL average.')
        kind = 'credit' if field.startswith('credit_') else field
        matches = [c for i,c in enumerate(components) if c['kind']==kind and (op['component_index'] is None or op['component_index']==i)]
        if len(matches)!=1:
            raise ValueError(f'{field}: choose one existing catalog component index; found {len(matches)} matches')
        key = {'credit_minimum':'minimum_kwh','credit_maximum':'maximum_kwh','credit_minimum_inclusive':'minimum_inclusive','credit_maximum_inclusive':'maximum_inclusive'}.get(field,'amount')
        matches[0][key] = op['value']=='true' if key.endswith('inclusive') else op['value']
    tariff = Tariff(components=components)
    if energy_structure(tariff.components):
        raise ValueError('Invalid energy tier structure')
    for c in tariff.components:
        if any(v is not None and v < 0 for v in (c.minimum_kwh,c.maximum_kwh)):
            raise ValueError('Usage boundaries must be nonnegative')
        if c.minimum_kwh is not None and c.maximum_kwh is not None and c.minimum_kwh>c.maximum_kwh:
            raise ValueError('Credit minimum exceeds maximum')
    return tariff.model_dump(mode='json')['components']


def calculate_catalog(state, frozen, request):
    records = copy.deepcopy(frozen)
    for record in records:
        ops = [o for o in state['overrides'] if o['plan_id']==record['id']]
        if ops and not record['calculation_eligible']:
            raise ValueError('Component overrides require an exact-calculation plan; rough estimates retain their reviewed assumptions.')
        if ops:
            record['components'] = override_components(record['components'],[o for o in ops if o['period']=='all'])
            renewal = [o for o in ops if o['period']=='renewal']
            if renewal:
                record['_scenario_renewal_components'] = override_components(record['components'],renewal)
    first = records[0] if records else {}
    result = compare_catalog(request, None, frozen_records=records,
                             utility=first.get('_scenario_utility'), fetched_at=first.get('_scenario_fetched_at'))
    for plan in result.recommendations:
        if any(o['plan_id']==plan.plan_id for o in state['overrides']):
            plan.explanation += ' Hypothetical scenario component overrides applied; original source evidence remains unchanged.'
    # Contract/credit filters apply to rough illustrations too, without ranking them.
    options = request.recommendation_options
    by_id = {r['id']:r for r in records}
    def matches(plan):
        term = plan.get('term_months')
        if options.exact_contract_months and term != options.exact_contract_months: return False
        if options.max_contract_months and (term is None or term > options.max_contract_months): return False
        if options.exclude_bill_credit_plans and any(c['kind']=='credit' and Decimal(c['amount'])>0 for c in by_id[plan['plan_id']]['components']): return False
        return True
    result.rough_estimates = [p for p in result.rough_estimates if matches(p)]
    result.assumptions.append('Chat preserves independent frozen PDF/API sources. Rough estimates remain separate 12-month illustrations, even when calculated plans use a longer comparison period.')
    return result
