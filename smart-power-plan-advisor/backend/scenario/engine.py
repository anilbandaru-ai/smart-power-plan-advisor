"""Apply validated hypothetical actions to copies of frozen input records."""
import copy
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from backend.models import ComparisonRequest, Plan, EflPriceExample
from backend.recommendation_models import RecommendationOptions
from backend.catalog.models import ExtractedPlan
from backend.catalog.compare import compare_catalog
from backend.services import compare

OPTIONS = set(RecommendationOptions.model_fields)
OVERRIDES = {"average_price", "base", "usage_charge", "delivery_fixed", "delivery_energy", "credit",
    "credit_minimum", "credit_maximum", "credit_minimum_inclusive", "credit_maximum_inclusive"}


def number(value):
    try:
        result = Decimal(value)
        if not result.is_finite(): raise ValueError()
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Enter a finite numeric value") from None


def apply(state, original, operations, plan_ids):
    state = copy.deepcopy(state)
    for op in operations:
        key, value = op.field, op.value
        if key in OPTIONS:
            expected = 'months' if key in ('comparison_horizon','max_contract_months','exact_contract_months') else 'percent' if key=='renewal_escalation_pct' else 'usd' if key=='switching_cost' else 'boolean' if key=='exclude_bill_credit_plans' else 'text'
            if op.unit != expected: raise ValueError(f"{key} requires {expected} units")
            if key=='exclude_bill_credit_plans':
                if value not in ('true','false'): raise ValueError('Use true or false for credit exclusion')
                value = value=='true'
            state['request']['recommendation_options'][key] = value
        elif key in ('usage', 'usage_percent'):
            if op.unit != ('kwh' if key=='usage' else 'percent'): raise ValueError('Usage units do not match the requested operation')
            if not op.months or len(set(op.months))!=len(op.months) or any(m<1 or m>12 for m in op.months):
                raise ValueError('Specify distinct usage months from 1 through 12')
            amount=number(value)
            if key=='usage' and not 0<=amount<=Decimal('99999999.9999'): raise ValueError('Usage must be between 0 and 99999999.9999 kWh')
            if key=='usage_percent' and not -100<=amount<=1000: raise ValueError('Usage percentage must be between -100 and 1000')
            base=original if op.basis=='original' else state
            for m in op.months:
                usage=amount if key=='usage' else number(base['request']['monthly_kwh'][m-1])*(1+amount/100)
                state['request']['monthly_kwh'][m-1]=str(usage.quantize(Decimal('.0001')))
        elif key=='clear_overrides':
            if op.plan_id not in plan_ids and op.plan_id!='all': raise ValueError('Choose a known plan or explicitly all plans')
            state['overrides']=[o for o in state['overrides'] if op.plan_id!='all' and o['plan_id']!=op.plan_id]
        else:
            if op.plan_id not in plan_ids and op.plan_id!='all': raise ValueError('Choose a known plan for the hypothetical override')
            expected='cents_per_kwh' if key in ('average_price','delivery_energy') else 'boolean' if key.endswith('inclusive') else 'kwh' if key.startswith('credit_') else 'usd'
            if op.unit!=expected: raise ValueError(f'{key} requires {expected} units')
            if expected=='boolean':
                if value not in ('true','false'): raise ValueError('Credit boundary inclusion must be true or false')
            elif value is not None:
                n=number(value)
                if not 0<=n<=Decimal('99999999.9999') or n.as_tuple().exponent < -4: raise ValueError('Override must be nonnegative with at most four decimals, within 99999999.9999')
            elif key not in ('credit_minimum','credit_maximum'): raise ValueError('This override needs a value')
            for plan_id in (plan_ids if op.plan_id=='all' else [op.plan_id]):
                override={**op.model_dump(), 'plan_id':plan_id}
                state['overrides']=[o for o in state['overrides'] if (o['plan_id'],o['field'],o['period'],o['component_index'])!=(plan_id,key,op.period,op.component_index)]
                state['overrides'].append(override)
    state['request']=ComparisonRequest.model_validate(state['request']).model_dump(mode='json')
    return state


def override_pdf(plan, ops):
    plan=copy.deepcopy(plan)
    for op in ops:
        field,value=op['field'],op['value']
        if field=='average_price':
            for example in plan['examples']: example['cents_per_kwh']=value
            continue
        kind='credit' if field.startswith('credit_') else field
        matches=[(i,c) for i,c in enumerate(plan['components']) if c['kind']==kind]
        if op['component_index'] is not None: matches=[(i,c) for i,c in matches if i==op['component_index']]
        if len(matches)!=1: raise ValueError(f"{field}: choose one existing PDF component index; found {len(matches)} matches")
        component=matches[0][1]
        key={'credit_minimum':'minimum_kwh','credit_maximum':'maximum_kwh','credit_minimum_inclusive':'minimum_inclusive','credit_maximum_inclusive':'maximum_inclusive'}.get(field,'amount')
        component[key]=(value=='true') if key.endswith('inclusive') else value
    for component in plan['components']:
        low,high=component.get('minimum_kwh'),component.get('maximum_kwh')
        if low is not None and high is not None and number(low)>number(high): raise ValueError('Credit minimum exceeds maximum')
    return ExtractedPlan.model_validate(plan).model_dump(mode='json')


def calculate(state, frozen):
    request=ComparisonRequest.model_validate(state['request'])
    if request.data_source=='pdf':
        records=copy.deepcopy(frozen)
        for row in records:
            ops=[o for o in state['overrides'] if o['plan_id']==row['id']]
            row['plan']=override_pdf(row['plan'],[o for o in ops if o['period']=='all'])
            renewal=[o for o in ops if o['period']=='renewal']
            if renewal: row['renewal_plan']=override_pdf(row['plan'],renewal)
        result=compare_catalog(request,SimpleNamespace(all_plans=lambda:records))
    else:
        plans=[]
        mapping={'base':'base_fee','delivery_fixed':'delivery_fee','delivery_energy':'delivery_rate','credit':'credit_amount','credit_minimum':'credit_threshold'}
        for raw in frozen:
            plan=copy.deepcopy(raw)
            for op in [o for o in state['overrides'] if o['plan_id']==plan['id']]:
                if op['period']=='renewal' or op['field'] not in mapping: raise ValueError('This override requires a PDF plan with documented components; demo supports base, delivery and credit amount/minimum for all months')
                value=op['value']
                plan[mapping[op['field']]]=str(number(value)/100) if op['field']=='delivery_energy' else value
            plans.append(Plan.model_validate(plan))
        result=compare(request,SimpleNamespace(list_plans=lambda:plans))
    if request.data_source=='pdf':
        originals={r['id']:r for r in frozen}
        for plan in result.recommendations:
            # Published reference disclosure always remains faithful to the source PDF.
            plan.efl_price_examples=[EflPriceExample(kwh=e['kwh'],cents_per_kwh=e['cents_per_kwh'],page=e['evidence']['page'],quote=e['evidence']['quote']) for e in originals[plan.plan_id]['plan']['examples']]
            if any(o['plan_id']==plan.plan_id for o in state['overrides']):
                plan.explanation+=' Hypothetical overrides apply to this scenario; published EFL examples below retain the original document values.'
    rec=result.recommendation_result
    if rec.best_overall is None: return None
    ids={p.plan_id for p in rec.plan_analyses}
    for plan in result.recommendations:
        if plan.plan_id not in ids:
            result.excluded_plans.append({'plan_id':plan.plan_id,'name':plan.name,'reasons':['Outside active contract or credit criteria']})
    result.recommendations=[p for p in result.recommendations if p.plan_id in ids]
    result.assumptions.append('Scenario uses frozen source records. Hypothetical overrides: '+('; '.join(o['field'].replace('_',' ')+' = '+str(o['value'])+' '+o['unit'].replace('_',' ')+' ('+o['period']+')' for o in state['overrides']) or 'none'))
    if state['overrides']:
        rec.confidence='low'
        rec.confidence_reasons.append('User-specified hypothetical overrides are not documented offers.')
    if any(m.total<0 for p in result.recommendations for m in p.monthly_costs):
        rec.warnings.insert(0,'Negative custom totals reflect the custom formula, not a guaranteed negative bill.')
    result.scenario_context={"state":copy.deepcopy(state),"frozen":copy.deepcopy(frozen)}
    return result


def no_match_message(state, frozen):
    """Explain actual retained constraints instead of implying the term is absent."""
    from backend.catalog.compare import ZIP_AREAS
    from backend.integrations import DEMO_ZIP_PLAN_IDS
    options=state['request']['recommendation_options']
    exact,maximum=options.get('exact_contract_months'),options.get('max_contract_months')
    matches=[]
    for record in frozen:
        if 'plan' in record:
            if not record['calculation_eligible']: continue
            plan=record['plan']
            if (plan.get('service_area') or {}).get('value')!=ZIP_AREAS.get(state['request']['zip_code']): continue
            plan=override_pdf(plan,[o for o in state['overrides'] if o['plan_id']==record['id'] and o['period']=='all'])
            term=int(plan['contract_term']['value'])
            credit=any(c['kind']=='credit' and (c.get('minimum_kwh') is not None or c.get('maximum_kwh') is not None) for c in plan['components'])
        else:
            if record['id'] not in DEMO_ZIP_PLAN_IDS.get(state['request']['zip_code'],()):continue
            term=record['term_months'];credit=record.get('credit_threshold') is not None and number(record.get('credit_amount','0'))>0
        if (exact and term!=exact) or (maximum and term>maximum):continue
        matches.append(credit)
    criteria=f"exactly {exact} months" if exact else f"at most {maximum} months" if maximum else "any contract length"
    if exact and maximum:criteria+=f" (maximum {maximum})"
    if matches and options.get('exclude_bill_credit_plans') and all(matches):
        return (f"{len(matches)} calculable plan(s) match {criteria}, but all are excluded by your active no-bill-credit filter. "
            "Allow bill-credit plans to compare this term, or choose another contract term while keeping that filter. Previous results are unchanged.")
    return (f"No calculable plans match {criteria} in this scenario's source catalog. "
        f"Exclude bill-credit plans: {'yes' if options.get('exclude_bill_credit_plans') else 'no'}. "
        "Choose another term or explicitly change a filter. Previous results are unchanged.")
