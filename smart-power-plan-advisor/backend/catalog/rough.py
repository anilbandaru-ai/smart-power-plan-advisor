"""Provider-independent, explicitly hypothetical pricing. Never used by ranking."""
import json
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from backend.services import money

VERSION = 'rough-v1'
PARAMETERS = {
    'free_usage_percent': ('Usage during free periods (%)', 0, 100),
    'delivery_waiver_percent': ('Per-kWh delivery waived during free periods (%)', 0, 100),
    'season_start': ('First seasonal month (1–12)', 1, 12),
    'season_end': ('Last seasonal month (1–12)', 1, 12),
    'season_discount_percent': ('Seasonal energy discount (%)', 0, 100),
    'season_extra_credit': ('Extra seasonal monthly credit ($)', 0, 1000),
    'export_kwh': ('Solar exports each month (kWh)', 0, 100000),
    'buyback_cents': ('Assumed solar buyback rate (¢/kWh)', 0, 100),
    'reward_realization_percent': ('Reward value actually redeemed (%)', 0, 100),
    'price_change_percent': ('Price change after term / first cycle (%)', -100, 500),
    'benchmark_adjustment_percent': ('Adjustment to benchmark estimate (%)', -100, 500),
}
FORMULAS = {
    'benchmark': 'Interpolate total bills at 500/1000/2000 kWh, preserving any known credit thresholds; multiply by (1 + benchmark adjustment / 100).',
    'flat': 'Usage × (energy rate + variable delivery rate) / 100 + base + fixed delivery + applicable usage charge − applicable credit.',
    'free_usage': 'Energy = usage × energy rate × (1 − free share); variable delivery = usage × delivery rate × (1 − free share × delivery waiver). Convert cents to dollars and add fixed charges.',
    'free_season': 'Apply the free-usage formula, then reduce remaining daytime energy charges by the seasonal discount in the selected months.',
    'seasonal': 'Reduce energy charges by the seasonal discount in the selected months; add unchanged delivery and fixed charges.',
    'seasonal_credit': 'Regular charges − threshold credit − extra seasonal credit when the same threshold qualifies in the selected months.',
    'solar': 'Grid-import charges + fixed charges − assumed export kWh × assumed buyback cents / 100; floor at zero with no rollover.',
    'reward': 'Regular bill − energy charges × reward percentage × realized fraction. This is equivalent economic value, not a bill credit.',
    'tiered': 'First usage block × first energy rate + excess usage × second energy rate; add delivery and fixed charges.',
}
COMMON_NOTES = [
    'Rough estimate, not a verified bill or available-plan recommendation. Monthly totals cannot establish interval usage.',
    'January–December usage is treated as twelve billing cycles. Taxes and nonrecurring fees are excluded; recorded rates are held constant except for the displayed price-change assumption.',
]


def fingerprint(record):
    source = record['source_details'] if record['source_type'] == 'txu' else [record['source_details'], sorted({d['sha256'] for d in record['source_documents']})]
    return sha256(json.dumps(source, sort_keys=True, default=str).encode()).hexdigest()


@lru_cache(maxsize=1)
def registry():
    return json.loads(Path(__file__).with_name('plan_reviews.json').read_text())['plans']


def examples(record):
    """Validate benchmarks independently; ambiguous component rates do not poison them."""
    if record['source_type'] == 'txu':
        mapping = {'FiveHundredKwh': 500, 'OneThousandKwh': 1000, 'TwoThousandKwh': 2000}
        raw = record['source_details'].get('rates')
        if not isinstance(raw, list):
            return None
        rows = [(mapping[r['type']], r.get('price'), 100) for r in raw
                if isinstance(r, dict) and r.get('type') in mapping]
    else:
        if any('invalid' in issue.lower() or 'does not match source' in issue.lower()
               for issue in record['calculation_issues']):
            return None
        rows = [(r.get('kwh'), r.get('cents_per_kwh'), 1) for r in record.get('examples', [])]
    result = {}
    try:
        for usage, price, factor in rows:
            value = Decimal(str(price)) * factor
            if usage not in (500, 1000, 2000) or usage in result or not value.is_finite() or not 0 < value <= 1000:
                return None
            result[usage] = value
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if set(result) == {500, 1000, 2000} else None


def capability(record):
    if record['calculation_eligible']:
        return {'supported': False, 'reason': 'Already included in calculated-cost ranking'}
    issues = ' '.join(record['calculation_issues']).lower()
    if 'stale' in issues or 'provider or utility' in issues:
        return {'supported': False, 'reason': 'Source availability or identity is unverified'}
    points = examples(record)
    if points is None:
        return {'supported': False, 'reason': 'Missing or invalid published price examples'}
    key = record['offer_sources'][0]['external_id'] if record['source_type'] == 'txu' else record['id']
    entry = registry().get(f"{record['source_type']}:{key}")
    matched = entry is not None and entry['fingerprint'] == fingerprint(record)
    profile = entry['profile'] if matched else {'kind': 'benchmark', 'defaults': {'benchmark_adjustment_percent': '0'}, 'notes': ['Source is new or changed since review; only published benchmark estimates are used. Unknown thresholds and time/season patterns may not be represented by interpolation.']}
    if not matched and (record['term_months'] is None or record['term_months'] < 12):
        profile['price_change_after_month'] = record['term_months'] or 1
        profile['defaults']['price_change_percent'] = '0'
        profile['notes'].append('Contract/variable pricing does not cover twelve months. Assume unchanged benchmark prices after the term or first cycle; edit the price-change scenario.')
    if profile['kind'] not in {'benchmark', 'flat', 'free_usage', 'free_season', 'seasonal', 'seasonal_credit', 'solar', 'reward', 'tiered'}:
        raise ValueError('Unknown reviewed rough pricing method')
    parameters = {}
    for name, value in profile.get('defaults', {}).items():
        label, low, high = PARAMETERS[name]
        parameters[name] = {'label': label, 'default': str(value), 'minimum': low, 'maximum': high,
                            'integer': name in ('season_start', 'season_end')}
    return {'supported': True, 'method': f"{VERSION}:{profile['kind']}",
            'review_status': 'reviewed_snapshot' if matched else 'needs_review', 'formula': FORMULAS[profile['kind']],
            'parameters': parameters, 'notes': [*COMMON_NOTES, *profile.get('notes', [])],
            'profile': profile, 'benchmarks': {str(k): str(v) for k, v in points.items()},
            'source_fingerprint': fingerprint(record)}


def public_capability(record):
    value = capability(record)
    return {k: v for k, v in value.items() if k != 'profile'}


def credit_at(credits, usage, month=None):
    total = Decimal(0)
    for c in credits:
        low, high = c.get('minimum_kwh'), c.get('maximum_kwh')
        if low is not None and (usage < Decimal(str(low)) if c.get('minimum_inclusive', True) else usage <= Decimal(str(low))):
            continue
        if high is not None and (usage > Decimal(str(high)) if c.get('maximum_inclusive', False) else usage >= Decimal(str(high))):
            continue
        total += Decimal(str(c['amount']))
    return total


def benchmark_bill(points, credits, usage):
    # Add verified threshold credits back, interpolate pre-credit bills, then apply
    # the discrete credit at the requested usage; never smooth a known threshold.
    values = {k: Decimal(v) * int(k) / 100 + credit_at(credits, Decimal(k)) for k, v in points.items()}
    if usage < 500 or usage > 2000:
        k = '500' if usage < 500 else '2000'
        gross = values[k] * usage / Decimal(k)
    else:
        low, high = (500, 1000) if usage <= 1000 else (1000, 2000)
        gross = values[str(low)] + (values[str(high)] - values[str(low)]) * (usage - low) / (high - low)
    return max(Decimal(0), gross - credit_at(credits, usage))


def estimate(record, usage_values, overrides=None):
    cap = capability(record)
    if not cap['supported']:
        if overrides:
            raise ValueError(f"Rough assumptions are not supported for {record['name']}; refresh the comparison.")
        return None
    overrides = overrides or {}
    if set(overrides) - set(cap['parameters']):
        raise ValueError(f"Unknown rough-estimate parameter for {record['name']}.")
    params = {}
    for name, definition in cap['parameters'].items():
        try:
            raw = overrides.get(name, definition['default'])
            if isinstance(raw, bool):
                raise ValueError()
            value = Decimal(str(raw))
            if not value.is_finite() or not definition['minimum'] <= value <= definition['maximum'] or (definition['integer'] and value != int(value)):
                raise ValueError()
        except (ValueError, TypeError, InvalidOperation):
            raise ValueError(f"Invalid {definition['label']} for {record['name']}.") from None
        params[name] = value
    p = cap['profile']; kind = p['kind']; credits = p.get('credits', [])
    monthly = []
    for month, usage in enumerate(usage_values, 1):
        usage = Decimal(usage)
        if kind == 'benchmark':
            total = benchmark_bill(cap['benchmarks'], credits, usage) * (1 + params.get('benchmark_adjustment_percent', 0) / 100)
        else:
            rates = {k: Decimal(str(v)) for k, v in p['rates'].items()}
            energy = usage * rates['energy'] / 100
            delivery = usage * rates['delivery_energy'] / 100
            if kind == 'tiered':
                boundary = Decimal(str(p['tier_boundary']))
                energy = (min(usage, boundary) * rates['energy'] + max(usage-boundary, 0) * Decimal(str(p['upper_energy']))) / 100
            if kind in ('free_usage', 'free_season'):
                share = params['free_usage_percent'] / 100
                energy *= 1-share
                delivery *= 1-share * params['delivery_waiver_percent'] / 100
            start, end = params.get('season_start', 1), params.get('season_end', 12)
            in_season = start <= month <= end if start <= end else month >= start or month <= end
            if kind in ('seasonal', 'free_season') and in_season:
                energy *= 1-params['season_discount_percent']/100
            total = energy + delivery + rates['base'] + rates['delivery_fixed'] - credit_at(credits, usage) + credit_at(p.get('usage_charges', []), usage)
            if kind == 'seasonal_credit' and in_season and credit_at(credits, usage):
                total -= params['season_extra_credit']
            if kind == 'solar':
                total -= params['export_kwh'] * params['buyback_cents'] / 100
            if kind == 'reward':
                total -= energy * Decimal(str(p['reward_percent']))/100 * params['reward_realization_percent']/100
        if month > p.get('price_change_after_month', 12):
            total *= 1+params.get('price_change_percent', 0)/100
        monthly.append({'month': month, 'kwh': str(usage), 'total': str(money(max(Decimal(0), total)))})
    notes = list(cap['notes'])
    if kind == 'benchmark' and any(Decimal(v) < 500 or Decimal(v) > 2000 for v in usage_values):
        notes.append('Extrapolation: usage outside 500–2000 kWh uses the nearest benchmark average rate; fixed charges and thresholds may make this inaccurate.')
    hidden = record['source_type'] == 'txu' and (record['source_details'].get('hideOnGrid') or not record['source_details'].get('active'))
    return {'plan_id': record['id'], 'name': record['name'], 'term_months': record['term_months'],
        'annual_cost': str(sum((Decimal(m['total']) for m in monthly), Decimal(0))),
        'monthly_costs': monthly, 'method': cap['method'], 'formula': cap['formula'], 'notes': notes,
        'availability': 'Hypothetical — provider marks this offer hidden or inactive' if hidden else 'Availability and address eligibility not verified',
        'parameters': cap['parameters'], 'assumptions_used': {k: str(v) for k, v in params.items()},
        'source_url': record['record_url'], 'source_revision': record['revision_id'],
        'source_fingerprint': cap['source_fingerprint'], 'pricing_issues': record['calculation_issues']}
