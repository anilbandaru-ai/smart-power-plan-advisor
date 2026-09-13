"""Catalog chat never uses demo prices, provider requests or mutable source rows."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api.main import create_app
from backend.catalog.store import CatalogStore
from backend.catalog.sync import sync
from backend.catalog.txu import sync_txu
from backend.catalog.validated import import_validated
from backend.scenario.actions import Action,Operation
from test_catalog import Extractor,PAGES
from test_txu import FakeClient


def change(field,value,unit='months',plan_id=None,period='all',months=None):
    return Action(kind='change',question='',operations=[Operation(field=field,value=value,unit=unit,plan_id=plan_id,period=period,months=months or [],basis='current',component_index=None)])


class CatalogChatTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.data=root/'data';self.data.mkdir()
        self.store=CatalogStore(root/'catalog.sqlite3');self.store.initialize()
        (self.data/'flat.pdf').write_bytes(b'pdf')
        with patch('backend.catalog.sync.read_pages',return_value=(PAGES,[])):
            sync(self.store,self.data,Extractor())
        sync_txu(self.store,self.data,['75201'],FakeClient())
        source=Path(__file__).resolve().parents[1]/'data/Reliant/EFL - Reliant Energy Retail Services-9.pdf'
        (self.data/'night.pdf').write_bytes(source.read_bytes())
        import_validated(self.store,self.data,files=['night.pdf'],allow_reviewed_estimates=True)
        self.action=Action(kind='explain',question='',operations=[])
        self.client=TestClient(create_app(db_path=root/'comparisons.sqlite3',catalog_path=self.store.path,scenario_interpreter=lambda *args:self.action))
        self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)
        self.request={'zip_code':'75201','data_source':'catalog','monthly_kwh':[1000]*12}
        self.original=self.client.post('/api/comparisons',json=self.request).json()
        self.before=self.client.get('/api/catalog/records').json()
        self.pdf=next(p for p in self.before['records'] if p['source_type']=='pdf' and p['calculation_eligible'])
        self.rough=next(p for p in self.before['records'] if not p['calculation_eligible'])

    def start(self,result=None):
        r=self.client.post('/api/comparison-chat',json={'comparison_id':(result or self.original)['id']})
        self.assertEqual(r.status_code,201,r.text);self.session=r.json()

    def turn(self,action):
        self.action=action
        r=self.client.post('/api/comparison-chat/'+self.session['session_id']+'/messages',headers={'X-Scenario-Token':self.session['token']},json={'request_id':str(uuid4()),'version':self.session['version'],'message':'test'})
        self.assertEqual(r.status_code,200,r.text)
        self.session={**r.json(),'token':self.session['token']};return r.json()

    def test_mixed_usage_overrides_and_history_preserve_sources(self):
        self.start()
        r=self.turn(change('usage','1200','kwh',months=list(range(1,13))))
        self.assertEqual(r['status'],'updated')
        direct=self.client.post('/api/comparisons',json={**self.request,'monthly_kwh':[1200]*12}).json()
        self.assertEqual([(p['plan_id'],p['annual_cost']) for p in r['result']['recommendations']],[(p['plan_id'],p['annual_cost']) for p in direct['recommendations']])
        self.assertEqual(r['result']['rough_estimates'][0]['annual_cost'],direct['rough_estimates'][0]['annual_cost'])
        with patch('backend.catalog.records.comparison_records',side_effect=AssertionError('No lookup')),patch('backend.catalog.rough.registry',side_effect=AssertionError('Use frozen review')):
            r=self.turn(change('energy','5','cents_per_kwh',self.pdf['id']))
        self.assertEqual(r['status'],'updated')
        self.assertEqual(self.client.get('/api/catalog/records').json(),self.before)
        self.assertEqual(self.turn(change('average_price','5','cents_per_kwh',self.pdf['id']))['status'],'invalid')
        self.assertEqual(self.turn(change('energy','5','cents_per_kwh',self.rough['id']))['status'],'invalid')
        r=self.turn(Action(kind='reset',question='',operations=[]))
        self.assertEqual(r['result']['id'],self.original['id'])
        r=self.turn(change('comparison_horizon','36'))
        self.assertEqual(r['result']['recommendations'][0]['comparison_horizon'],36)
        self.assertEqual(len(r['result']['rough_estimates'][0]['monthly_costs']),12)
        self.assertEqual(self.turn(Action(kind='previous',question='',operations=[]))['result']['id'],self.original['id'])

    def test_renewal_override_is_separate_and_no_match_is_atomic(self):
        self.start();r=self.turn(change('comparison_horizon','36'))
        baseline=next(p for p in r['result']['recommendations'] if p['plan_id']==self.pdf['id'])
        r=self.turn(change('delivery_fixed','99','usd',self.pdf['id'],period='renewal'))
        edited=next(p for p in r['result']['recommendations'] if p['plan_id']==self.pdf['id'])
        self.assertEqual(edited['monthly_costs'],baseline['monthly_costs'])
        self.assertNotEqual(edited['horizon_cost'],baseline['horizon_cost'])
        previous=r['result']['id'];r=self.turn(change('exact_contract_months','48'))
        self.assertEqual(r['status'],'no_matches');self.assertEqual(r['result']['id'],previous)

    def test_drift_rejects_start_but_existing_session_is_frozen(self):
        self.start()
        with self.store.connection() as db:db.execute('UPDATE revisions SET issues=? WHERE id=?',(json.dumps(['Changed source']),self.pdf['revision_id']))
        self.assertEqual(self.client.post('/api/comparison-chat',json={'comparison_id':self.original['id']}).status_code,409)
        r=self.turn(change('usage','1100','kwh',months=list(range(1,13))))
        self.assertEqual(r['status'],'updated');self.assertIn(self.pdf['id'],[p['plan_id'] for p in r['result']['recommendations']])

    def test_rough_only_and_api_only_can_start(self):
        api=self.client.post('/api/comparisons',json={**self.request,'data_source':'txu'}).json()
        self.start(api);self.assertEqual(self.turn(change('usage','900','kwh',months=list(range(1,13))))['result']['data_mode'],'txu')
        with self.store.connection() as db:
            db.execute("DELETE FROM sources WHERE path='flat.pdf'");db.execute('DELETE FROM txu_refreshes')
        self.original=self.client.post('/api/comparisons',json=self.request).json()
        self.assertEqual(self.original['recommendations'],[])
        self.start();r=self.turn(change('usage','1200','kwh',months=list(range(1,13))))
        self.assertEqual(r['status'],'updated');self.assertEqual(r['result']['recommendations'],[])
        self.assertTrue(r['result']['rough_estimates'])
