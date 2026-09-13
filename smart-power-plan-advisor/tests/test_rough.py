import copy
import json
import unittest
from decimal import Decimal
from unittest.mock import patch
from backend.catalog.rough import estimate, examples, fingerprint, capability, registry, benchmark_bill
from backend.catalog.records import txu_record
from test_txu import offer, ONCOR, OFFER
import test_catalog_records as catalog_tests


def record():
    raw = offer(); raw['hideOnGrid'] = True
    return txu_record({'raw': raw, 'name': raw['name'], 'external_id': OFFER}, {'id': ONCOR, 'name': 'Oncor'}, '78681', '2026-09-12')


def bound(record, profile):
    return patch('backend.catalog.rough.registry', return_value={f'txu:{OFFER}': {'fingerprint': fingerprint(record), 'profile': profile}})


RATES = {'energy':'13.9','base':'9.95','delivery_energy':'3.5778','delivery_fixed':'3.42'}


class RoughMathTests(unittest.TestCase):
    def test_free_days_independent_bill_and_override(self):
        r = record()
        p = {'kind':'free_usage','rates':RATES,'defaults':{'free_usage_percent':str(Decimal(700)/30),'delivery_waiver_percent':'0'}}
        with bound(r,p):
            result=estimate(r,[Decimal(1000)]*12)
            self.assertEqual(result['monthly_costs'][0]['total'],'155.71')
            self.assertEqual(result['annual_cost'],'1868.52')
            edited=estimate(r,[Decimal(1000)]*12,{'free_usage_percent':'50','delivery_waiver_percent':'100'})
            self.assertEqual(edited['monthly_costs'][0]['total'],'100.76')
            self.assertIn('hidden',result['availability'])
            for values in ({'free_usage_percent':101},{'free_usage_percent':'NaN'},{'free_usage_percent':True},{'unknown':1}):
                with self.assertRaises(ValueError):estimate(r,[1000]*12,values)

    def test_benchmark_interpolates_bills_not_rates_and_marks_extrapolation(self):
        points={'500':'20','1000':'10','2000':'15'}
        self.assertEqual(benchmark_bill(points,[],Decimal(750)),Decimal(100))
        self.assertEqual(benchmark_bill(points,[],Decimal(1500)),Decimal(200))
        self.assertEqual(benchmark_bill(points,[],Decimal(2500)),Decimal(375))
        r=record()
        with patch('backend.catalog.rough.registry',return_value={}):
            result=estimate(r,[Decimal(2500)]*12,{'benchmark_adjustment_percent':10})
            self.assertTrue(any('Extrapolation' in n for n in result['notes']))
            self.assertEqual(result['monthly_costs'][0]['total'],'426.25')

    def test_known_credit_is_not_smoothed_across_threshold(self):
        points={'500':'20','1000':'10','2000':'15'}
        credits=[{'amount':'100','minimum_kwh':'1000'}]
        self.assertEqual(benchmark_bill(points,credits,Decimal(999)),Decimal('199.8'))
        self.assertEqual(benchmark_bill(points,credits,Decimal(1000)),Decimal('100'))

    def test_seasonal_credit_boundary_and_wraparound_discount(self):
        r=record();rates={'energy':'10','base':'5','delivery_energy':'5','delivery_fixed':'5'}
        p={'kind':'seasonal_credit','rates':rates,'credits':[{'amount':'35','minimum_kwh':'1000'}], 'defaults':{'season_start':'7','season_end':'9','season_extra_credit':'25'}}
        with bound(r,p):
            result=estimate(r,[1000]*12)
            self.assertEqual(result['monthly_costs'][0]['total'],'125.00')
            self.assertEqual(result['monthly_costs'][6]['total'],'100.00')
            self.assertEqual(estimate(r,[999]*12)['monthly_costs'][6]['total'],'159.85')
            with self.assertRaises(ValueError):estimate(r,[1000]*12,{'season_start':'6.5'})
        p={'kind':'seasonal','rates':rates,'defaults':{'season_start':'12','season_end':'2','season_discount_percent':'50'}}
        with bound(r,p):
            result=estimate(r,[1000]*12)
            self.assertEqual(result['monthly_costs'][0]['total'],'110.00')
            self.assertEqual(result['monthly_costs'][5]['total'],'160.00')
            self.assertEqual(result['monthly_costs'][11]['total'],'110.00')

    def test_solar_reward_tiered_and_short_term_scenarios(self):
        r=record();rates={'energy':'10','base':'5','delivery_energy':'5','delivery_fixed':'5'}
        p={'kind':'solar','rates':rates,'defaults':{'export_kwh':'0','buyback_cents':'0'}}
        with bound(r,p):
            self.assertEqual(estimate(r,[1000]*12)['monthly_costs'][0]['total'],'160.00')
            self.assertEqual(estimate(r,[1000]*12,{'export_kwh':'500','buyback_cents':'10'})['monthly_costs'][0]['total'],'110.00')
            self.assertEqual(estimate(r,[1000]*12,{'export_kwh':'10000','buyback_cents':'10'})['monthly_costs'][0]['total'],'0.00')
        p={'kind':'reward','rates':rates,'reward_percent':'3','defaults':{'reward_realization_percent':'0'}}
        with bound(r,p):
            self.assertEqual(estimate(r,[1000]*12)['monthly_costs'][0]['total'],'160.00')
            self.assertEqual(estimate(r,[1000]*12,{'reward_realization_percent':100})['monthly_costs'][0]['total'],'157.00')
        p={'kind':'tiered','rates':rates,'tier_boundary':'1000','upper_energy':'5','defaults':{'price_change_percent':'20'},'price_change_after_month':9}
        with bound(r,p):
            result=estimate(r,[2000]*12)
            self.assertEqual(result['monthly_costs'][0]['total'],'260.00')
            self.assertEqual(result['monthly_costs'][9]['total'],'312.00')

    def test_source_change_requires_review_and_future_provider_uses_same_engine(self):
        r=record();p={'kind':'flat','rates':RATES,'defaults':{}}
        with bound(r,p):
            self.assertEqual(capability(r)['review_status'],'reviewed_snapshot')
            r['source_details']['description']='Changed terms'
            self.assertEqual(capability(r)['method'],'rough-v1:benchmark')
        r['provider']='Future Provider'
        with bound(r,p):
            self.assertEqual(capability(r)['method'],'rough-v1:flat')
            self.assertEqual(estimate(r,[1000]*12)['monthly_costs'][0]['total'],'188.15')

    def test_bad_examples_rejected_independent_of_duplicate_components(self):
        for value in ('NaN','-1','0','Infinity',None):
            r=record();r['source_details']['rates'][4]['price']=value
            self.assertIsNone(examples(r));self.assertFalse(capability(r)['supported'])
        r=record();r['source_details']['rates'].append(copy.deepcopy(r['source_details']['rates'][4]))
        self.assertIsNone(examples(r))
        r=record();r['source_details']['rates'].append(copy.deepcopy(r['source_details']['rates'][0]))
        self.assertIsNotNone(examples(r))
        r['calculation_issues'].append('TXU availability is stale')
        self.assertFalse(capability(r)['supported'])

    def test_all_review_entries_have_distinct_versioned_profiles(self):
        entries=registry()
        self.assertEqual(len(entries),64)
        self.assertEqual(sum(p['source_type']=='txu' for p in entries.values()),43)
        self.assertTrue(all(len(e['fingerprint'])==64 for e in entries.values()))
        self.assertTrue({'tiered','solar','seasonal_credit','free_usage','benchmark'} <= {p['profile']['kind'] for p in entries.values()})


# Reuse setup helpers without collecting inherited test methods a second time.
class RoughApiTests(unittest.TestCase):
    setUp=catalog_tests.CatalogRecordTests.setUp
    app=catalog_tests.CatalogRecordTests.app
    sync_txu=catalog_tests.CatalogRecordTests.sync_txu
    import_pdf=catalog_tests.CatalogRecordTests.import_pdf

    def test_mixed_and_rough_only_snapshots_never_rank_hidden_offer(self):
        self.import_pdf();self.client.offers[0]['hideOnGrid']=True;self.sync_txu()
        with self.app() as client:
            body={'zip_code':'78681','data_source':'catalog','monthly_kwh':[1000]*12}
            result=client.post('/api/comparisons',json=body)
            self.assertEqual(result.status_code,201,result.text)
            saved=result.json();self.assertEqual(len(saved['recommendations']),1)
            self.assertEqual(len(saved['rough_estimates']),1)
            rough=saved['rough_estimates'][0]
            self.assertNotEqual(saved['recommendation_result']['best_overall']['plan_id'],rough['plan_id'])
            self.assertEqual(client.get('/api/comparisons/'+saved['id']).json(),saved)
            changed=client.post('/api/comparisons',json={**body,'rough_assumptions':{rough['plan_id']:{'benchmark_adjustment_percent':'20'}}})
            self.assertEqual(changed.status_code,201,changed.text)
            self.assertEqual(changed.json()['rough_estimates'][0]['assumptions_used']['benchmark_adjustment_percent'],'20')
            rough_only=client.post('/api/comparisons',json={**body,'data_source':'txu'}).json()
            self.assertEqual(rough_only['recommendations'],[])
            self.assertEqual(rough_only['recommendation_result']['status'],'no_eligible_plans')
            for overrides in ({'unknown':{}},{rough['plan_id']:{'not_allowed':1}},{rough['plan_id']:{'benchmark_adjustment_percent':999}}):
                self.assertEqual(client.post('/api/comparisons',json={**body,'rough_assumptions':overrides}).status_code,422)
            with self.store.connection() as db:db.execute("UPDATE txu_refreshes SET fetched_at='2000-01-01T00:00:00+00:00'")
            after=client.post('/api/comparisons',json={**body,'zip_code':'75201'}).json()
            self.assertEqual(after['rough_estimates'],[])
