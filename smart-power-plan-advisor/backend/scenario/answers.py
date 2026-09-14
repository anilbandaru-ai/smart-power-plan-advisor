"""Read-only answers derived from frozen terms and saved scenario calculations."""
import copy
import re
from decimal import Decimal

TOPICS = {
    'credits': r'\bcredits?\b|\bdiscount\b', 'delivery': r'\bdelivery\b',
    'fees': r'\bfees?\b|\bbase charge', 'energy': r'\benergy\b|\brates?\b|\befl\b',
    'monthly': r'\bhighest\b|\blowest month\b|\bmonthly\b',
    'contract': r'\bcontract\b|\btermination\b', 'savings': r'\bsavings?\b|\bsave\b',
    'regret': r'\bregret\b|\brisk\b', 'break_even': r'break.?even',
    'compare': r'\bversus\b|\bvs\b|\bwhy not\b|\bdifference between\b',
    'recommendation': r'\bwhy\b|\brecommend|\bcheapest\b',
}


def topic_for(text):
    if re.search(TOPICS['compare'], text, re.I): return 'compare'
    return next((key for key, pattern in TOPICS.items() if re.search(pattern, text, re.I)), 'unknown')


def plan_name(record):
    return record['plan']['name']['value'] if 'plan' in record else record['name']


def explicit_ids(text, records):
    exact = [r['id'] for r in records if text.strip() == r['id']]
    if exact: return exact
    matches = [r for r in records if re.search(r'(?<!\w)' + re.escape(plan_name(r)) + r'(?!\w)', text, re.I)]
    # A family-name substring must not override an explicitly named longer variant.
    return [r['id'] for r in matches if not any(plan_name(r).casefold() != plan_name(other).casefold()
        and plan_name(r).casefold() in plan_name(other).casefold() for other in matches)]


def local_question(text, records):
    """Recognize clear information requests; leave scenario edits to the interpreter."""
    pair=re.fullmatch(r'(?:please\s+|can you\s+)?compare\s+(?!over\b|across\b|for\b)(.+?)\s+(?:with|and|versus|vs\.?)\s+(.+?)[?.!]*',text.strip(),re.I)
    if pair:
        if all(name.strip().lower() in ('original','initial','current','original scenario','initial scenario','current scenario') for name in pair.groups()): return None
        targets=[]
        for name in pair.groups():
            matches=[r['id'] for r in records if plan_name(r).casefold()==name.strip().casefold()]
            targets.append(matches[0] if len(matches)==1 else 'unresolved:'+name.strip())
        return ('compare',targets)
    if re.search(r'\b(what if|set|change|increase|decrease|exclude|avoid|remove|use|assume|switch)\b', text, re.I):
        return None
    if not re.match(r'^(are|is|does|do|how|what|which|why|would|will|explain|tell|show)\b', text.strip(), re.I):
        return None
    if re.search(r'\bguarantee(?:d)?\b|\bactual bill\b',text,re.I): return ('recommendation', [])
    topic = topic_for(text)
    ids = explicit_ids(text, records)
    scope = re.search(r'\b(?:for|about)\s+(.+?)[?.!]*$', text.strip(), re.I)
    if scope:
        requested = scope.group(1).strip(' ?.!').casefold()
        known = [plan_name(r).casefold() for r in records]
        if requested not in known and requested not in ('it','this plan','that plan','the recommended plan','the recommendation','my plan'):
            return None
    # Unknown named plans require interpretation/clarification, not a winner fallback.
    if not ids and re.search(r'\b(for|about)\s+(?!it\b|this\b|that\b|the\b|my\b)', text, re.I):
        return None
    return (topic, ids) if topic != 'unknown' else None


def delta(before, after):
    a, b = before.recommendation_result, after.recommendation_result
    if not a or not b or not a.best_overall or not b.best_overall:
        return 'Ranked before/after comparison is unavailable.'
    text = f'Before: {a.best_overall.name}. Now: {b.best_overall.name}. '
    if a.comparison_horizon != b.comparison_horizon or a.policy_version != b.policy_version:
        return text + 'Periods or pricing methods differ; totals are not like-for-like savings.'
    change = cost_of(b.best_overall) - cost_of(a.best_overall)
    return text + f'Estimated cost change: ${change:+,.2f} over {b.comparison_horizon} months; this is a scenario difference, not guaranteed savings.'


def answer(result, frozen, current, topic, targets, focus, question=''):
    by_id = {r['id']: r for r in frozen}
    rec = result.recommendation_result
    if re.search(r'\bguarantee(?:d)?\b|\bactual bill\b',question,re.I):
        return 'explained', 'No, this is not a guaranteed actual bill. These are estimates using saved rates, usage and scenario assumptions. Custom EFL calculations repeat embedded fee and credit effects; live availability, taxes and unmodeled charges may differ.', [], focus
    if topic == 'recommendation' and not result.recommendations and result.rough_estimates:
        return 'explained', 'This comparison has only rough estimates, not a ranked recommendation. Their assumptions are incomplete or unsupported for exact comparison, so I cannot identify a cheapest plan. Review the separate rough estimates and source limitations.', [], focus
    assumption = ''
    if not targets:
        targets = [i for i in focus if i in by_id]
        if not targets and rec and rec.best_overall:
            targets = [rec.best_overall.plan_id]
            assumption = 'Using the currently recommended plan. '
    if not targets or any(i not in by_id for i in targets) or (len(targets) > 1 and topic != 'compare'):
        return 'clarify', 'Which plan do you mean? Available plans: ' + ', '.join(plan_name(r) + ' [' + r['id'] + ']' for r in frozen), [], targets
    if topic == 'compare' and len(targets) == 1:
        others = [p.plan_id for p in result.recommendations if p.plan_id not in targets]
        if others:
            targets = targets + others[:1]
            assumption += 'Comparing with the next available alternative. '
    plans = {p.plan_id: p for p in result.recommendations}
    analyses = {p.plan_id: p for p in rec.plan_analyses} if rec else {}
    texts, sources = [], []
    if topic == 'compare' and len(targets)==2 and all(i in plans for i in targets):
        left,right=(plans[i] for i in targets)
        if left.comparison_horizon==right.comparison_horizon and left.pricing_basis==right.pricing_basis:
            a=left.horizon_cost if left.horizon_cost is not None else left.annual_cost
            b=right.horizon_cost if right.horizon_cost is not None else right.annual_cost
            texts.append(f'Comparing {left.name} with {right.name} over {left.comparison_horizon} months at your current usage. ' +
                ('Their estimated costs are equal.' if a==b else f'{left.name if a<b else right.name} costs ${abs(a-b):,.2f} less over this period.'))
        else:
            texts.append('These plans have different periods or pricing methods; their totals are not like-for-like savings.')
    for target in targets:
        record = by_id[target]
        plan = plans.get(target)
        raw = record.get('plan', record)
        components = copy.deepcopy(raw.get('components', []))
        overrides = [o for o in current['overrides'] if o['plan_id'] == target]
        if not components and 'credit_threshold' in record and record.get('credit_amount') is not None:
            components = [dict(kind='credit',amount=record['credit_amount'],unit='usd_per_month',minimum_kwh=record.get('credit_threshold'),minimum_inclusive=True,maximum_kwh=None,maximum_inclusive=False)]
        if overrides and components:
            from backend.scenario.catalog import override_components
            components = override_components([{k:v for k,v in c.items() if k != 'evidence'} for c in components], [o for o in overrides if o['period'] == 'all' and o['field'] != 'average_price'])
        kinds = {'credits': ['credit'], 'delivery': ['delivery_fixed', 'delivery_energy'],
                 'fees': ['base', 'usage_charge'], 'energy': ['energy', 'energy_tier']}.get(topic, [])
        selected = [c for c in components if c['kind'] in kinds]
        text = plan_name(record) + ': '
        if topic in ('credits', 'delivery', 'fees'):
            if not selected:
                text += f'No {topic} components are recorded. This does not establish that all possible charges or benefits are absent.'
            for c in selected:
                unit = 'cents/kWh' if c['unit'] == 'cents_per_kwh' else 'USD/month'
                bounds = []
                for key, inclusive, symbol in [('minimum_kwh', 'minimum_inclusive', '>'), ('maximum_kwh', 'maximum_inclusive', '<')]:
                    if c.get(key) is not None:
                        bounds.append(f"usage {symbol}{'=' if c.get(inclusive) else ''} {c[key]} kWh")
                text += f"{c['kind'].replace('_', ' ')} {c['amount']} {unit}" + (' when ' + ' and '.join(bounds) if bounds else ' with no recorded usage threshold') + '. '
            usage_query = re.search(r'\bat\s+(\d+(?:\.\d+)?)\s*kwh\b', question, re.I)
            if topic == 'credits' and usage_query and record.get('calculation_eligible', True):
                usage = Decimal(usage_query.group(1)); eligible = []
                for c in selected:
                    low,high = c.get('minimum_kwh'),c.get('maximum_kwh')
                    if low is not None and (usage < Decimal(str(low)) or (usage == Decimal(str(low)) and not c.get('minimum_inclusive',True))): continue
                    if high is not None and (usage > Decimal(str(high)) or (usage == Decimal(str(high)) and not c.get('maximum_inclusive',False))): continue
                    eligible.append(Decimal(str(c['amount'])))
                text += f'At {usage} kWh, modeled bill credit is ${sum(eligible, Decimal(0)):,.2f} under these recorded conditions; your usage inputs are unchanged. '
            if plan:
                field = {'credits': 'credit', 'delivery': 'delivery', 'fees': 'base_fee'}[topic]
                values = [(m.month, getattr(m, field)) for m in plan.monthly_costs]
                text += 'First-year modeled amounts: ' + '; '.join(f'month {m}: ${v:,.2f}' for m, v in values) + '. '
            else:
                text += 'No calculated monthly eligibility is available for this plan.'
        elif topic in ('energy', 'monthly') and plan:
            if topic == 'energy':
                text += ('Custom estimate: Energy = usage times the range-mapped EFL reference / 100; separate fees, delivery and credits repeat effects embedded in the EFL average. ' if plan.pricing_basis == 'custom_efl' else 'Energy uses the saved tariff component calculation. ')
                if plan.pricing_basis == 'custom_efl' and result.data_mode == 'catalog':
                    text += 'This catalog plan does not support energy-component or EFL-reference price overrides; no rate change is applied by this answer. '
                text += '; '.join(f'month {m.month}: {m.kwh} kWh, reference {m.average_price_cents if m.average_price_cents is not None else "not used"} cents/kWh, Energy ${m.energy:,.2f}' for m in plan.monthly_costs) + '.'
            else:
                maximum = max(m.total for m in plan.monthly_costs)
                minimum = min(m.total for m in plan.monthly_costs)
                text += f'First-year highest total ${maximum:,.2f} in months ' + ', '.join(str(m.month) for m in plan.monthly_costs if m.total == maximum)
                text += f'; lowest ${minimum:,.2f} in months ' + ', '.join(str(m.month) for m in plan.monthly_costs if m.total == minimum) + '.'
        elif topic == 'contract':
            term = record.get('term_months') or (raw.get('contract_term') or {}).get('value')
            text += f'Recorded contract: {term if term is not None else "unknown"} months. '
            termination = raw.get('termination_terms') or (record.get('source_details') or {}).get('termination_terms')
            text += 'Termination terms: ' + (termination['value'] if isinstance(termination, dict) else 'not available in the structured record') + '.'
        elif topic in ('recommendation', 'compare', 'regret') and target in analyses:
            analysis = analyses[target]
            text += f'Estimated ${cost_of(analysis):,.2f} over {rec.comparison_horizon} months; contract {plan.term_months} months. Maximum tested regret ${analysis.max_scenario_regret:,.2f}. '
            text += ' '.join(analysis.recommendation_reasons)
            text += f' Confidence: {rec.confidence}. ' + ' '.join(rec.confidence_reasons)
            if topic == 'compare' and plan:
                text += f' First-year modeled credits ${sum(m.credit for m in plan.monthly_costs):,.2f}.'
        elif topic == 'compare' and plan:
            text += f'Saved estimate ${plan.horizon_cost if plan.horizon_cost is not None else plan.annual_cost:,.2f} over {plan.comparison_horizon} months; contract {plan.term_months} months. This plan is outside the current ranked selection; preferences were not relaxed.'
        elif topic in ('savings', 'break_even') and rec:
            data = rec.expected_savings if topic == 'savings' else [c for c in rec.break_even_conditions if target in c.get('plan_ids',[]) or (not c.get('plan_ids') and rec.best_overall and target==rec.best_overall.plan_id)]
            if topic == 'savings' and rec.best_overall and target != rec.best_overall.plan_id:
                if rec.baseline and target in analyses:
                    gross = Decimal(str(rec.baseline['horizon_cost'])) - cost_of(analyses[target])
                    fee = Decimal(0) if rec.baseline['plan_id']==target else rec.options.switching_cost
                    data = {'gross_horizon_savings_USD':gross,'net_horizon_savings_USD':None if fee is None else gross-fee,'comparison_months':rec.comparison_horizon}
                else: data = None
            text += describe(data) if data else 'No supported ' + topic.replace('_', '-') + ' estimate is available. A modeled baseline is needed for savings; break-even findings cover tested scenarios only.'
        else:
            text += 'That detail is not available as a grounded scenario answer. Ask about bill credits, delivery, fees, energy, contract, monthly totals, savings, regret or two available plans. Use Plan Assistant for other document questions.'
        if plan and plan.pricing_basis == 'custom_efl' and topic != 'energy':
            text += ' Custom estimate: EFL averages supply Energy and source charges are applied separately; this repeats embedded effects and is not an actual tariff bill.'
        if overrides:
            text += ' Hypothetical overrides are active: ' + '; '.join(f"{o['field']}={o['value']} ({o['period']})" for o in overrides) + '. Sources describe original terms.'
        texts.append(text)
        source_raw = record.get('source_details', raw) if record.get('source_type') == 'pdf' else raw
        evidence = [c.get('evidence') for c in source_raw.get('components', []) if c['kind'] in kinds]
        if topic == 'energy':
            evidence += [e.get('evidence') for e in raw.get('examples', [])]
        if topic == 'contract':
            evidence += [(source_raw.get(k) or {}).get('evidence') for k in ('contract_term', 'termination_terms')]
        evidence = [e for e in evidence if e] or record.get('provenance', [])
        for e in evidence:
            ref = {'plan_id': target, 'label': plan_name(record), 'url': e.get('url') or record.get('document_url') or record.get('record_url'), 'page': e.get('page'), 'quote': e.get('quote', '')}
            if ref not in sources:
                sources.append(ref)
    if topic in ('compare', 'recommendation', 'regret', 'savings', 'break_even') and rec:
        if topic != 'compare': texts.append(' '.join(rec.key_tradeoffs))
        if topic != 'compare': texts.append('Category winners: ' + '; '.join(key.replace('_',' ') + ': ' + (plan_name(by_id[value]) if value in by_id else 'not available') for key,value in rec.category_winners.items()))
        texts.append(' '.join(rec.warnings))
    if not sources:
        texts.append('No source excerpt is attached to this structured answer; calculated figures come from the saved scenario.')
    return 'explained', assumption + '\n\n'.join(texts), sources, targets


def describe(value):
    if isinstance(value, dict):
        return '; '.join(key.replace('_', ' ') + ': ' + describe(item) for key, item in value.items())
    if isinstance(value, list): return '. '.join(describe(item) for item in value)
    if value is None: return 'unknown'
    if isinstance(value, Decimal): return f'{value:,.2f}'
    return str(value)


def cost_of(plan):
    return plan.horizon_cost if plan.horizon_cost is not None else plan.estimated_annual_cost
