import json
import sqlite3
import tempfile
import unittest
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from backend.api.main import create_app, ROOT
from backend.integrations import JsonPlanSource
from backend.models import ComparisonRequest, Plan
from backend.recommendations import Candidate, recommend
from backend.services import calculate_month, compare
from backend.catalog.pricing import calculate
from backend.catalog.compare import compare_catalog
from test_catalog import fixture


def request(usage=None, **options):
    return ComparisonRequest(zip_code="75201", monthly_kwh=usage if usage is not None else [1000] * 12,
        recommendation_options=options)


def candidate(plan, issue=None):
    return Candidate(plan.id, plan.name, plan.term_months,
        lambda usage, month: calculate_month(plan, usage, month),
        [plan.credit_threshold] if plan.credit_threshold is not None else [],
        [{"kind": "test_source", "description": plan.source}], issue)


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.source = JsonPlanSource(ROOT / "data" / "plans.json")
        self.plans = [p for p in self.source.list_plans() if 'oncor' in p.id]

    def test_independent_costs_regret_reversal_and_credit_cliff(self):
        result = compare(request(), self.source).recommendation_result
        best = result.best_overall
        self.assertEqual(best.plan_id, 'demo-oncor-credit')
        self.assertEqual(best.estimated_annual_cost, D('1800.00'))
        self.assertEqual(best.max_scenario_regret, D('330.00'))
        self.assertEqual(result.category_winners['lowest_scenario_regret'], 'demo-oncor-simple')
        alternative = next(p for p in result.plan_analyses if p.plan_id == 'demo-oncor-simple')
        self.assertEqual(alternative.max_scenario_regret, D('120.00'))
        self.assertEqual(alternative.additional_cost_at_supplied_usage, D('120.00'))
        self.assertEqual(best.bill_credit_analysis['annual_credits'], D('480.00'))
        probes = best.bill_credit_analysis['threshold_exposure'][0]['probes']
        self.assertEqual([p['bill'] for p in probes], [D('190.00'), D('150.00'), D('150.00')])
        self.assertEqual(result.confidence, 'low')
        self.assertTrue(any(c['kind'] == 'sampled_usage_bracket' and c['exact'] is False for c in result.break_even_conditions))
        self.assertTrue(all(min(p.scenario_results[i].regret for p in result.plan_analyses) == 0 for i in range(5)))

    def test_seasonal_usage_is_preserved_and_default_baseline_unknown(self):
        result = compare(request([500,1500]*6), self.source).recommendation_result
        self.assertEqual(result.best_overall.plan_id, 'demo-oncor-simple')
        self.assertEqual(result.best_overall.estimated_annual_cost, D('1920.00'))
        self.assertEqual(result.scenarios[0]['monthly_kwh'], [D('400'),D('1200')]*6)
        self.assertIsNone(result.baseline)
        self.assertIsNone(result.expected_savings)

    def test_strict_lower_and_exclusive_upper_pdf_credit_boundaries(self):
        plan = fixture()
        credit = plan.components[-1]
        credit.minimum_kwh = D('999'); credit.minimum_inclusive = False
        credit.maximum_kwh = D('2000'); credit.maximum_inclusive = False
        c = Candidate('pdf', 'PDF', 12, lambda u,m: calculate(plan,u,m), [D('999'),D('2000')], [])
        result = recommend(request(), [c], 'pdf')
        lower, upper = result.best_overall.bill_credit_analysis['threshold_exposure']
        self.assertEqual([p['credit'] for p in lower['probes']], [D('0'),D('0'),D('40')])
        self.assertEqual([p['credit'] for p in upper['probes']], [D('40'),D('0'),D('0')])

    def test_baseline_savings_switching_recovery_and_negative_net(self):
        result = compare(request(baseline_plan_id='demo-oncor-simple', switching_cost='60'),self.source).recommendation_result
        self.assertEqual(result.expected_savings['gross_annual_savings'], D('120.00'))
        self.assertEqual(result.expected_savings['net_annual_savings'], D('60.00'))
        self.assertEqual(result.expected_savings['sustained_payback_month'], 6)
        unknown = compare(request(baseline_plan_id='demo-oncor-simple'),self.source).recommendation_result
        self.assertIsNone(unknown.expected_savings['net_annual_savings'])
        costly = compare(request(baseline_plan_id='demo-oncor-simple',switching_cost='200'),self.source).recommendation_result
        self.assertEqual(costly.expected_savings['net_annual_savings'], D('-80.00'))
        self.assertIsNone(costly.expected_savings['sustained_payback_month'])
        same = compare(request(baseline_plan_id='demo-oncor-credit',switching_cost='200'),self.source).recommendation_result
        self.assertEqual(same.expected_savings['net_annual_savings'], 0)
        self.assertEqual(same.expected_savings['switching_cost'], 0)
        with self.assertRaisesRegex(ValueError, 'Current plan'):
            compare(request(baseline_plan_id='unavailable'),self.source)

    def test_preferences_empty_single_and_baseline_outside_filter(self):
        a,b = self.plans
        a = a.model_copy(update={'term_months':24})
        candidates = [candidate(a),candidate(b)]
        one = recommend(request(max_contract_months=12,baseline_plan_id=a.id),candidates,'demo')
        self.assertEqual(len(one.top_3),1)
        self.assertEqual(one.baseline['plan_id'],a.id)
        self.assertTrue(any('Only one' in w for w in one.warnings))
        none = recommend(request(max_contract_months=12),[candidate(a)],'demo')
        self.assertEqual(none.status,'no_eligible_plans')
        self.assertIsNone(none.best_overall)
        self.assertEqual(none.top_3,[])
        self.assertEqual(recommend(request(),[],'demo').status,'no_eligible_plans')

    def test_ties_zero_usage_and_confidence_components(self):
        a = self.plans[0]
        b = a.model_copy(update={'id':'another', 'name':'Equal'})
        result = recommend(request([0]*12,usage_provenance='meter'),
            [candidate(a,'2026-09-01'),candidate(b,'2026-09-01')],'pdf',today=date(2026,9,12))
        self.assertEqual(result.best_overall.plan_id, 'another')
        self.assertTrue(all(r.rank == 1 and r.regret == 0 for p in result.plan_analyses for r in p.scenario_results))
        self.assertEqual(result.confidence,'moderate')
        self.assertEqual(result.confidence_components['availability'],'unverified')
        stale = recommend(request(usage_provenance='meter'),[candidate(a,'2020-01-01'),candidate(b,'unknown')],'pdf',today=date(2026,9,12))
        self.assertEqual(stale.confidence,'low')
        estimated = recommend(request(usage_provenance='estimated'),[candidate(a,'2026-09-01'),candidate(b,'2026-09-01')],'pdf',today=date(2026,9,12))
        self.assertEqual(estimated.confidence,'low')

    def test_pdf_adapter_produces_page_evidence_and_matching_cost(self):
        plan = fixture()
        row = {'id':'pdf','revision_id':'rev','sources':['plan.pdf'],'document_url':'/api/catalog/plans/pdf/document',
            'calculation_eligible':True,'calculation_issues':[],'plan':plan.model_dump(mode='json')}
        result = compare_catalog(request(), SimpleNamespace(all_plans=lambda:[row]))
        self.assertEqual(result.recommendations[0].annual_cost,result.recommendation_result.best_overall.estimated_annual_cost)
        self.assertTrue(any(ref.get('page') == 1 and ref.get('quote') for ref in result.recommendation_result.evidence_refs))
        ids = {ref['id'] for ref in result.recommendation_result.evidence_refs}
        self.assertTrue(set(result.recommendation_result.best_overall.evidence_refs) <= ids)

    def test_api_persistence_options_and_legacy_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory)/'saved.sqlite3'
            with TestClient(create_app(db,catalog_path=Path(directory)/'catalog.sqlite3')) as client:
                response=client.post('/api/comparisons',json=request(usage_provenance='bills',switching_cost='0',baseline_plan_id='demo-oncor-simple').model_dump(mode='json'))
                self.assertEqual(response.status_code,201,response.text)
                data=response.json()
                self.assertEqual(data['recommendation_result']['expected_savings']['net_annual_savings'],'120.00')
                self.assertEqual(client.get('/api/comparisons/'+data['id']).json(),data)
                for options in [{'max_contract_months':3},{'switching_cost':'-1'},{'switching_cost':'NaN'},{'usage_provenance':'invented'}]:
                    self.assertEqual(client.post('/api/comparisons',json={'zip_code':'75201','monthly_kwh':[1000]*12,'recommendation_options':options}).status_code,422)
                data.pop('recommendation_result')
                connection=sqlite3.connect(db)
                try:
                    with connection: connection.execute('UPDATE comparisons SET payload=? WHERE id=?',(json.dumps(data),data['id']))
                finally: connection.close()
                legacy=client.get('/api/comparisons/'+data['id']).json()
                self.assertIsNone(legacy['recommendation_result'])
