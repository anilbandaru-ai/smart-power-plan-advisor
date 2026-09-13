import unittest
from decimal import Decimal as D
from types import SimpleNamespace
from test_catalog import fixture
from backend.catalog.average import calculate_average
from backend.catalog.compare import compare_catalog
from backend.models import ComparisonRequest, ComparisonResult, MonthlyCost
from backend.projections import project
from backend.recommendations import Candidate


class AveragePricingTests(unittest.TestCase):
    def plan(self):
        plan = fixture()
        for example, price in zip(plan.examples, ('19.7', '6.8', '12.8')):
            example.cents_per_kwh = D(price)
        return plan

    def test_reference_boundaries_and_no_double_counting(self):
        plan = self.plan()
        plan.examples.reverse()
        for usage, price, total in [('0','19.7','0'), ('500','19.7','98.50'),
                ('500.1','19.7','98.52'), ('1000','19.7','197'),
                ('1000.0001','6.8','68'), ('1800','6.8','122.40'),
                ('2000','6.8','136'), ('2000.0001','12.8','256')]:
            with self.subTest(usage=usage):
                month = calculate_average(plan, D(usage), 1)
                self.assertEqual(month.average_price_cents, D(price))
                self.assertEqual(month.energy, D(total))
                self.assertEqual(month.total, D(total))
                self.assertEqual((month.base_fee, month.delivery, month.credit), (0, 0, 0))
        plan.examples[1].cents_per_kwh = D('11.5')
        self.assertEqual(calculate_average(plan,D(1800),1).total,D('207'))

    def test_missing_and_duplicate_examples_rejected(self):
        for examples in ([], [self.plan().examples[0]] * 2):
            plan = self.plan()
            plan.examples = examples
            with self.assertRaises(ValueError): calculate_average(plan,D(1800),1)

    def test_renewal_rate_matches_total_and_credit_policy_is_not_applied_twice(self):
        candidate = Candidate('p','Plan',12,lambda u,m:calculate_average(self.plan(),u,m),[],[],pricing_basis='efl_average')
        keep, details = project(candidate,[D(1800)]*12,36,D(5),'retain')
        drop, _ = project(candidate,[D(1800)]*12,36,D(5),'drop')
        self.assertEqual(keep,drop)
        self.assertEqual([keep[i].total for i in (0,12,24)],[D('122.40'),D('128.52'),D('134.95')])
        self.assertEqual([keep[i].average_price_cents for i in (0,12,24)],[D('6.8'),D('7.14'),D('7.497')])
        self.assertEqual(details[12]['basis'],'modeled_renewal')
        self.assertEqual(sum(m.total for m in keep),D('4630.44'))

    def test_comparison_ranking_baseline_and_serialization_share_estimates(self):
        a, b = self.plan(), self.plan()
        b.examples[1].cents_per_kwh=D('8')
        def record(id,plan):
            return {'id':id,'revision_id':id,'sources':[id+'.pdf'],'document_url':'/'+id,
                'calculation_eligible':True,'calculation_issues':[],'plan':plan.model_dump(mode='json')}
        request=ComparisonRequest(zip_code='75201',data_source='pdf',monthly_kwh=[1800]*12,
            recommendation_options={'max_contract_months':24,'baseline_plan_id':'b','switching_cost':'10'})
        result=compare_catalog(request,SimpleNamespace(all_plans=lambda:[record('a',a),record('b',b)]))
        rec=result.recommendation_result
        self.assertEqual(rec.best_overall.plan_id,'a')
        self.assertEqual(rec.best_overall.horizon_cost,D('4388.04'))
        self.assertEqual(rec.baseline['horizon_cost'],D('4919.40'))
        self.assertEqual(rec.expected_savings['net_horizon_savings'],D('521.36'))
        self.assertEqual(rec.policy_version,'custom-efl-v4')
        self.assertEqual(rec.confidence,'low')
        self.assertEqual(rec.best_overall.bill_credit_analysis['annual_credits'],D('480'))
        for analysis in rec.plan_analyses:
            raw=next(p for p in result.recommendations if p.plan_id==analysis.plan_id)
            self.assertEqual(raw.horizon_cost,analysis.horizon_cost)
            self.assertTrue(any(e.get('field')=='average_price' for e in rec.evidence_refs))
        restored=ComparisonResult.model_validate_json(result.model_dump_json())
        self.assertEqual(restored.model_dump(mode="json"),result.model_dump(mode="json"))
        self.assertEqual(restored.recommendations[0].pricing_basis,'custom_efl')
        legacy=MonthlyCost(month=1,kwh=1800,energy=100,base_fee=5,delivery=20,credit=0,total=125)
        self.assertEqual(legacy.pricing_basis,'components')
        self.assertIsNone(legacy.average_price_cents)


    def test_custom_formula_and_renewal_credit_policy(self):
        from backend.catalog.average import calculate_custom
        plan=self.plan()
        for component in plan.components:
            if component.kind=='delivery_energy': component.amount=D('6.0295')
            if component.kind=='delivery_fixed': component.amount=D('4.06')
            if component.kind=='credit': component.amount=D('125')
        month=calculate_custom(plan,D(1800),1)
        self.assertEqual((month.energy,month.base_fee,month.delivery,month.credit,month.total),
            (D('122.40'),D(0),D('112.59'),D(125),D('109.99')))
        self.assertEqual(calculate_custom(plan,D('999.9999'),1).credit,0)
        self.assertEqual(calculate_custom(plan,D('1000'),1).credit,125)
        candidate=Candidate('p','Plan',12,lambda u,m:calculate_custom(plan,u,m),[D(1000)],[],pricing_basis='custom_efl')
        keep,_=project(candidate,[D(1800)]*12,24,D(5),'retain')
        drop,_=project(candidate,[D(1800)]*12,24,D(5),'drop')
        self.assertEqual(keep[12].energy,D('128.52'))
        self.assertEqual(keep[12].average_price_cents,D('7.14'))
        self.assertEqual(keep[12].delivery,D('118.22'))
        self.assertEqual(keep[12].total,D('121.74'))
        self.assertEqual(drop[12].total,D('246.74'))
        self.assertEqual(drop[11],keep[11])
