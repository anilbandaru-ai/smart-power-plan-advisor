import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from fastapi.testclient import TestClient
from backend.api.main import create_app
from backend.catalog.store import CatalogStore
from backend.catalog.utilities import resolve_utilities,area_name
from backend.catalog.records import comparison_records
from backend.models import ComparisonRequest

U={'id':'ea0ad3a5-3fc6-4d9f-894a-e21a751c33fe','name':'Oncor Electric Delivery'}

class UtilityTests(unittest.TestCase):
    def test_discovery_cache_and_filter_without_offers(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=CatalogStore(Path(tmp)/'catalog.sqlite3');store.initialize()
            client=Mock();client.get_utilities.return_value=[U]
            resolve_utilities(store,'79756',client)
            resolve_utilities(store,'79756',client)
            client.get_utilities.assert_called_once_with('79756');client.get_plans.assert_not_called()
            req=ComparisonRequest(zip_code='79756',data_source='catalog',monthly_kwh=[1000]*12)
            plans=[dict(id='a',name='Any provider',service_area='Oncor',calculation_eligible=True),dict(id='b',name='Elsewhere',service_area='CenterPoint',calculation_eligible=True)]
            with patch('backend.catalog.records.records',side_effect=lambda store,source,*args,**kwargs:plans if source=='pdf' else []):
                eligible,_,utility,_=comparison_records(req,store)
                self.assertEqual([p['id'] for p in eligible],['a']);self.assertEqual(utility,U)
            with store.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM txu_refreshes').fetchone()[0],0)
            client.get_utilities.return_value=[U,dict(id='other',name='CenterPoint')]
            with store.connection() as db:db.execute("UPDATE delivery_utilities SET fetched_at='2000-01-01T00:00:00+00:00'")
            resolve_utilities(store,'79756',client)
            with self.assertRaisesRegex(ValueError,'Multiple utilities'):comparison_records(req,store)
            client.get_utilities.side_effect=RuntimeError('secret response')
            with store.connection() as db:db.execute("UPDATE delivery_utilities SET fetched_at='2000-01-01T00:00:00+00:00'")
            result=resolve_utilities(store,'79756',client);self.assertNotIn('secret',result['error'])
            with self.assertRaisesRegex(ValueError,'unavailable'):comparison_records(req,store)

    def test_endpoint_and_empty_utility(self):
        with tempfile.TemporaryDirectory() as tmp:
            with TestClient(create_app(db_path=Path(tmp)/'a.sqlite3',catalog_path=Path(tmp)/'c.sqlite3')) as c,patch('backend.catalog.utilities.TxuClient') as factory:
                factory.return_value.get_utilities.return_value=[]
                r=c.get('/api/catalog/utilities?zip_code=79756');self.assertEqual(r.status_code,200);self.assertEqual(r.json()['utilities'],[])
                self.assertEqual(c.get('/api/catalog/utilities?zip_code=abc').status_code,422)
                factory.return_value.get_plans.assert_not_called()
        self.assertEqual(area_name('Oncor Electric Delivery'),'Oncor')

    def test_invalid_78641_data_has_actionable_message_and_no_partial_selection(self):
        import httpx
        from backend.providers.txu import TxuClient
        malformed = [
            {'data': {'utilities': [{'id':'002be614-111a-46fc-9f2f-717cd76297f0','name':''}, {'id':'09f43c73-45ea-433e-a9fc-5a5d6ae2cd80','name':'AEP North'}]}},
            {'data': {'utilities': [{'id':'1174','name':'Some utility'}]}},
            {'data': {'utilities': [{'id':U['id'],'name':'   '}]}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with TestClient(create_app(db_path=Path(tmp)/'a.sqlite3',catalog_path=Path(tmp)/'c.sqlite3')) as api:
                for payload in malformed:
                    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200,json=payload))) as http:
                        with patch('backend.catalog.utilities.TxuClient',return_value=TxuClient(http)):
                            result=api.get('/api/catalog/utilities?zip_code=78641')
                    self.assertEqual(result.status_code,503)
                    detail=result.json()['detail']
                    self.assertIn("couldn't verify the delivery utility for ZIP 78641",detail)
                    self.assertIn('electricity bill',detail);self.assertIn('exact address',detail)
                    self.assertNotIn('AEP North',detail)
                store=CatalogStore(Path(tmp)/'c.sqlite3')
                from backend.catalog.utilities import cached_utilities
                self.assertEqual(cached_utilities(store,'78641')['utilities'],[])
                self.assertTrue(cached_utilities(store,'78641')['stale'])
                with patch('backend.catalog.utilities.TxuClient') as factory:
                    factory.return_value.get_utilities.side_effect=httpx.ReadTimeout('private details')
                    detail=api.get('/api/catalog/utilities?zip_code=78641').json()['detail']
                    self.assertEqual(detail,'Delivery utility lookup failed. Please try again.')

    def test_malformed_json_is_classified_as_invalid_utility_data(self):
        import httpx
        from backend.providers.txu import TxuClient,InvalidUtilities
        with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,text='invalid json'))) as http:
            with self.assertRaises(InvalidUtilities):TxuClient(http).get_utilities('78641')
