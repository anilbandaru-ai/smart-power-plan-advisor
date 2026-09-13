from contextlib import closing
import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api.main import create_app
from backend.catalog.store import CatalogStore
from backend.scenario.actions import Action,Operation
from backend.scenario.engine import apply,override_pdf
from test_catalog import fixture


def op(field,value,unit='months',**kwargs):
    return Operation(field=field,value=value,unit=unit,plan_id=None,months=[],basis='current',period='all',component_index=None,**kwargs)


def action(*ops):return Action(kind='change',question='',operations=list(ops))


class ScenarioChatTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'saved.sqlite3'
        self.next=Action(kind='explain',question='',operations=[])
        self.context=None
        def interpret(message,context):
            self.context=context
            if isinstance(self.next,Exception):raise self.next
            return self.next
        self.client=TestClient(create_app(db_path=self.path,catalog_path=Path(self.tmp.name)/'catalog.sqlite3',scenario_interpreter=interpret))
        self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)
        self.records=[]
        for id,term in [('a',12),('b',24),('c',36)]:
            plan=fixture();plan.name.value=id;plan.contract_term.value=str(term)
            self.records.append({'id':id,'revision_id':'rev-'+id,'sources':[id+'.pdf'],'document_url':'/'+id,'calculation_eligible':True,'calculation_issues':[],'plan':plan.model_dump(mode='json')})
        self.patch=patch.object(CatalogStore,'all_plans',side_effect=lambda:copy.deepcopy(self.records));self.patch.start();self.addCleanup(self.patch.stop)
        response=self.client.post('/api/comparisons',json={'zip_code':'75201','data_source':'pdf','monthly_kwh':[1800]*12})
        self.assertEqual(response.status_code,201,response.text)
        self.original=response.json()
        response=self.client.post('/api/comparison-chat',json={'comparison_id':self.original['id']})
        self.assertEqual(response.status_code,201,response.text)
        self.session=response.json()
        self.headers={'X-Scenario-Token':self.session['token']}
    def turn(self,chosen=None,message='test',body=None):
        if chosen is not None:self.next=chosen
        body=body or {'request_id':str(uuid4()),'version':self.session['version'],'message':message}
        response=self.client.post('/api/comparison-chat/'+self.session['session_id']+'/messages',headers=self.headers,json=body)
        if response.status_code==200:self.session={**response.json(),'token':self.session['token']}
        return response
    def test_contract_horizon_baseline_and_history(self):
        response=self.turn(action(op('comparison_horizon','36'),op('max_contract_months','24'),op('exact_contract_months','24'),op('baseline_plan_id','c','text')))
        self.assertEqual(response.status_code,200,response.text)
        result=self.session['result'];self.assertEqual([p['plan_id'] for p in result['recommendations']],['b'])
        self.assertEqual(result['recommendation_result']['comparison_horizon'],36)
        self.assertEqual(result['recommendation_result']['baseline']['plan_id'],'c')
        saved=self.client.get('/api/comparisons/'+result['id']).json();self.assertEqual(saved,result)
        self.turn(Action(kind='compare_original',question='',operations=[]))
        self.assertIn('not like-for-like',self.session['message'])
        self.turn(Action(kind='previous',question='',operations=[]));self.assertEqual(self.session['result']['id'],self.original['id'])
    def test_invalid_atomic_and_no_matches(self):
        self.turn(action(op('renewal_escalation_pct','8','percent'),op('max_contract_months','-1')))
        self.assertEqual(self.session['status'],'invalid');self.assertEqual(self.session['state']['request']['recommendation_options']['renewal_escalation_pct'],'5')
        self.turn(action(op('exclude_bill_credit_plans','true','boolean')))
        self.assertEqual(self.session['status'],'no_matches');self.assertEqual(self.session['result']['id'],self.original['id'])
        self.turn(action(op('exact_contract_months','24'),op('max_contract_months','12')))
        self.assertEqual(self.session['status'],'invalid')
        self.turn(action(op('exact_contract_months','12')))
        self.assertEqual(self.session['status'],'updated')
    def test_clarification_context_and_retry(self):
        self.turn(Action(kind='clarify',question='Which rate and units?',operations=[]),message='rate 8')
        self.assertEqual(self.session['result']['id'],self.original['id'])
        self.turn(Action(kind='explain',question='',operations=[]),message='explain')
        self.assertIn('rate 8',self.context['pending']['request'])
        body={'request_id':str(uuid4()),'version':self.session['version'],'message':'explain'}
        response=self.turn(RuntimeError('timeout'),body=body);self.assertEqual(response.status_code,503)
        response=self.turn(Action(kind='explain',question='',operations=[]),body=body);self.assertEqual(response.status_code,200)
        again=self.turn(body=body);self.assertEqual(again.json(),response.json())
        response=self.turn(body={**body,'message':'different'});self.assertEqual(response.status_code,409)
        response=self.turn(body={**body,'request_id':str(uuid4())});self.assertEqual(response.status_code,409)
    def test_usage_original_current_and_bounds(self):
        def usage(value,basis):return Operation(field='usage_percent',value=value,unit='percent',plan_id=None,months=[6,7,8],basis=basis,period='all',component_index=None)
        self.turn(action(usage('20','current')));self.assertEqual(self.session['state']['request']['monthly_kwh'][5],'2160.0000')
        self.turn(action(usage('10','original')));self.assertEqual(self.session['state']['request']['monthly_kwh'][5],'1980.0000')
        self.turn(action(usage('-101','current')));self.assertEqual(self.session['status'],'invalid')
    def test_overrides_do_not_modify_catalog_and_clear(self):
        operation=Operation(field='average_price',value='8',unit='cents_per_kwh',plan_id='a',months=[],basis='current',period='all',component_index=None)
        original=copy.deepcopy(self.records)
        self.turn(action(operation));self.assertEqual(self.session['status'],'updated',self.session['message'])
        a=next(p for p in self.session['result']['recommendations'] if p['plan_id']=='a')
        self.assertEqual(a['monthly_costs'][0]['energy'],'144.00');self.assertEqual(original,self.records)
        self.turn(action(operation.model_copy(update={'field':'clear_overrides','value':None})))
        self.assertEqual(self.session['state']['overrides'],[])
    def test_renewal_only_credit_override_and_frozen_sources(self):
        operation=Operation(field='credit',value='0',unit='usd',plan_id='a',months=[],basis='current',period='renewal',component_index=None)
        self.records[0]['plan']['examples'][1]['cents_per_kwh']='999'
        self.turn(action(op('comparison_horizon','24'),operation))
        a=next(p for p in self.session['result']['recommendations'] if p['plan_id']=='a')
        self.assertEqual(a['monthly_costs'][0]['credit'],'40.00')
        self.assertEqual(a['horizon_monthly_costs'][12]['credit'],'0.00')
        self.assertEqual(a['monthly_costs'][0]['energy'],'207.00')
    def test_expiry_auth_and_source_drift(self):
        response=self.client.get('/api/comparison-chat/'+self.session['session_id']);self.assertEqual(response.status_code,404)
        self.records[0]['revision_id']='new'
        response=self.client.post('/api/comparison-chat',json={'comparison_id':self.original['id']});self.assertEqual(response.status_code,409)
        with closing(sqlite3.connect(self.path)) as c,c:c.execute('UPDATE scenario_sessions SET expires=0')
        self.assertEqual(self.turn().status_code,410)
    def test_legacy_migration(self):
        legacy=copy.deepcopy(self.original)
        for p in legacy['recommendations']:p['pricing_basis']='efl_average'
        with closing(sqlite3.connect(self.path)) as c,c:c.execute('UPDATE comparisons SET payload=? WHERE id=?',(json.dumps(legacy),legacy['id']))
        response=self.client.post('/api/comparison-chat',json={'comparison_id':legacy['id']});self.session=response.json();self.headers={'X-Scenario-Token':self.session['token']}
        self.turn(action(op('comparison_horizon','24')));self.assertEqual(self.session['status'],'clarify')
        self.turn(Action(kind='migrate',question='',operations=[]));self.assertEqual(self.session['status'],'updated')
        self.assertFalse(self.session['needs_migration'])
    def test_component_overrides_and_unknown_targets(self):
        for field,unit,value in [('base','usd','10'),('delivery_fixed','usd','6'),('delivery_energy','cents_per_kwh','7'),('credit','usd','50'),('credit_minimum','kwh','1500'),('credit_maximum','kwh','2000'),('credit_minimum_inclusive','boolean','false')]:
            operation=Operation(field=field,value=value,unit=unit,plan_id='a',months=[],basis='current',period='all',component_index=None)
            self.turn(action(operation));self.assertEqual(self.session['status'],'updated',self.session['message'])
        self.turn(action(operation.model_copy(update={'plan_id':'unknown'})));self.assertEqual(self.session['status'],'invalid')

    def test_explicit_interpreter_commands_and_malformed_response(self):
        from backend.scenario.actions import interpret
        context={'plans':[{'id':'a','name':'SimpleSaver 24'}]}
        command=interpret('Set the mapped EFL reference price for SimpleSaver 24 to 8 cents per kWh',context)
        self.assertEqual(command.kind,'change');self.assertEqual(command.operations[0].plan_id,'a')
        self.assertEqual(interpret('Only 24-month contracts',context).operations[0].field,'exact_contract_months')
        self.next={'kind':'invented_action'}
        self.assertEqual(self.turn().status_code,503)
        response=self.client.get('/api/comparison-chat/'+self.session['session_id'],headers=self.headers)
        self.assertTrue(response.json()['failures'])
    def test_concurrent_requests_only_commit_once(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        barrier=threading.Barrier(2)
        class Racing:
            def __call__(self):
                barrier.wait(timeout=10)
                return Action(kind='explain',question='',operations=[])
        racing=Racing()
        class Response:
            pass
        # Swap the test interpreter's result with an Action whose validation waits.
        original=Action.model_validate
        def validate(value,*args,**kwargs):
            if value is self.next: barrier.wait(timeout=10)
            return original(value,*args,**kwargs)
        url='/api/comparison-chat/'+self.session['session_id']+'/messages'
        bodies=[{'request_id':str(uuid4()),'version':0,'message':'why'} for _ in range(2)]
        with patch.object(Action,'model_validate',side_effect=validate),ThreadPoolExecutor(2) as pool:
            responses=list(pool.map(lambda body:self.client.post(url,headers=self.headers,json=body),bodies))
        self.assertEqual(sorted(r.status_code for r in responses),[200,409])
    def test_calculation_failure_preserves_active_state(self):
        with patch('backend.scenario.api.calculate',side_effect=RuntimeError('failed')):
            self.assertEqual(self.turn(action(op('comparison_horizon','36'))).status_code,503)
        response=self.client.get('/api/comparison-chat/'+self.session['session_id'],headers=self.headers).json()
        self.assertEqual(response['version'],0);self.assertEqual(response['result']['id'],self.original['id'])

    def test_new_chat_from_scenario_preserves_hypothetical_inputs(self):
        operation=Operation(field='average_price',value='8',unit='cents_per_kwh',plan_id='a',months=[],basis='current',period='all',component_index=None)
        self.turn(action(operation))
        result=self.session['result']
        a=next(p for p in result['recommendations'] if p['plan_id']=='a')
        self.assertEqual(a['efl_price_examples'][1]['cents_per_kwh'],'11.5')
        self.records=[]
        response=self.client.post('/api/comparison-chat',json={'comparison_id':result['id']})
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(response.json()['state']['overrides'],self.session['state']['overrides'])

    def test_storage_failure_rolls_back_and_same_request_can_retry(self):
        original_connect=sqlite3.connect
        class BrokenSave(sqlite3.Connection):
            def execute(self,sql,*args,**kwargs):
                if sql.startswith('INSERT INTO comparisons'):
                    raise sqlite3.OperationalError('simulated save failure')
                return super().execute(sql,*args,**kwargs)
        body={'request_id':str(uuid4()),'version':0,'message':'36 months'}
        with patch('backend.scenario.api.sqlite3.connect',side_effect=lambda *a,**kw:original_connect(*a,**kw,factory=BrokenSave)):
            self.assertEqual(self.turn(action(op('comparison_horizon','36')),body=body).status_code,503)
        response=self.client.get('/api/comparison-chat/'+self.session['session_id'],headers=self.headers).json()
        self.assertEqual(response['version'],0)
        self.assertEqual(response['result']['id'],self.original['id'])
        self.assertEqual(self.turn(body=body).status_code,200)
        self.assertEqual(self.session['status'],'updated')

    def test_noncalculable_override_and_extreme_usage_are_rejected(self):
        operation=Operation(field='usage',value='1e100000',unit='kwh',plan_id=None,months=[1],basis='current',period='all',component_index=None)
        self.turn(action(operation));self.assertEqual(self.session['status'],'invalid')
        self.assertEqual(self.session['result']['id'],self.original['id'])
        from backend.scenario.engine import apply
        operation=operation.model_copy(update={'field':'average_price','value':'8','unit':'cents_per_kwh','plan_id':'unsupported','months':[]})
        with self.assertRaises(ValueError):apply(self.session['state'],self.session['state'],[operation],['a','b','c'])

    def test_explicit_term_request_explains_credit_filter_without_relaxing_it(self):
        from backend.scenario.actions import interpret
        chosen=interpret('contract term 24 months',{})
        self.assertEqual([(o.field,o.value) for o in chosen.operations],[('exact_contract_months','24')])
        # Begin with exact 12/no-credit criteria using a genuinely credit-free 12-month plan.
        with closing(sqlite3.connect(self.path)) as c,c:
            row=c.execute('SELECT payload FROM scenario_sessions WHERE id=?',(self.session['session_id'],)).fetchone()
            state=json.loads(row[0]);opts=state['history'][0]['state']['request']['recommendation_options']
            opts.update(comparison_horizon=24,max_contract_months=24,exact_contract_months=12,exclude_bill_credit_plans=True)
            c.execute('UPDATE scenario_sessions SET payload=? WHERE id=?',(json.dumps(state),self.session['session_id']))
        self.turn(chosen,message='contract term 24 months')
        self.assertEqual(self.session['status'],'no_matches')
        self.assertIn('1 calculable plan(s) match exactly 24 months',self.session['message'])
        self.assertIn('no-bill-credit filter',self.session['message'])
        self.assertTrue(self.session['state']['request']['recommendation_options']['exclude_bill_credit_plans'])
        self.assertEqual(self.session['result']['id'],self.original['id'])
        self.assertEqual(self.session['attempts'][-1]['changes'],['exact contract months: 24'])
        self.turn(action(*chosen.operations,op('exclude_bill_credit_plans','false','boolean')))
        self.assertEqual(self.session['status'],'updated')
        self.assertEqual([p['term_months'] for p in self.session['result']['recommendations']],[24])
        self.turn(action(op('max_contract_months',None),op('exact_contract_months','48')))
        self.assertEqual(self.session['status'],'no_matches')
        self.assertIn('No calculable plans match exactly 48 months',self.session['message'])
