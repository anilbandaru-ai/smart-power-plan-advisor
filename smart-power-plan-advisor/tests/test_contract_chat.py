import copy
import unittest
from backend.models import ComparisonRequest
from backend.scenario.actions import preflight_action, interpret
from backend.scenario.engine import apply
from test_catalog_chat import change


class ContractChatTests(unittest.TestCase):
    def setUp(self):
        request=ComparisonRequest(zip_code='75201',monthly_kwh=[1000]*12,
            recommendation_options={'comparison_horizon':12,'usage_provenance':'bills',
                                    'renewal_escalation_pct':7})
        self.state={'request':request.model_dump(mode='json'),'overrides':[]}

    def test_maximum_replaces_saved_horizon_and_retains_other_inputs(self):
        for term in ('24','36',None):
            with self.subTest(term=term):
                before=copy.deepcopy(self.state)
                result=apply(self.state,self.state,change('max_contract_months',term).operations,[])
                options=result['request']['recommendation_options']
                self.assertEqual(options['comparison_horizon'],int(term) if term else None)
                self.assertEqual(options['max_contract_months'],int(term) if term else None)
                self.assertEqual(options['usage_provenance'],'bills')
                self.assertEqual(options['renewal_escalation_pct'],'7')
                self.assertEqual(self.state,before)

    def test_explicit_horizon_wins_in_either_operation_order(self):
        operations=change('max_contract_months','24').operations+change('comparison_horizon','36').operations
        for ops in (operations,list(reversed(operations))):
            result=apply(self.state,self.state,ops,[])
            self.assertEqual(result['request']['recommendation_options']['comparison_horizon'],36)
            self.assertEqual(result['request']['recommendation_options']['max_contract_months'],24)

    def test_maximum_and_period_clarification_replies_are_deterministic(self):
        context={'pending':{'request':'24 months','question':'Which period?'}}
        for prompt in ('maximum contract length 24 months','maximum 24 months','Set the maximum contract to 24 months'):
            action=preflight_action(prompt,context)
            self.assertEqual([(o.field,o.value) for o in action.operations],
                [('max_contract_months','24'),('comparison_horizon','24')])
        for prompt in ('comparison period 24 months','comparison horizon 24 months','Compare over 24 months'):
            action=preflight_action(prompt,context)
            self.assertEqual([(o.field,o.value) for o in action.operations],[('comparison_horizon','24')])
        self.assertEqual(preflight_action('24 months',{}).kind,'clarify')
        self.assertIsNone(preflight_action('Compare over 36 months with maximum 24 months',{}))
        action=interpret('contract term 24 months',{})
        self.assertEqual([o.field for o in action.operations],['exact_contract_months'])

    def test_exact_filter_conflicts_remain_atomic(self):
        self.state['request']['recommendation_options']['exact_contract_months']=36
        before=copy.deepcopy(self.state)
        with self.assertRaises(ValueError):
            apply(self.state,self.state,change('max_contract_months','24').operations,[])
        self.assertEqual(self.state,before)
