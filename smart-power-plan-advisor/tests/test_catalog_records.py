"""API contract integration tests, independent of source document access."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api.main import create_app
from backend.catalog.records import records, txu_record
from backend.catalog.store import CatalogStore
from backend.catalog.sync import sync
from backend.catalog.txu import sync_txu, cached, public_cache
from test_catalog import Extractor, PAGES, fixture
from test_txu import FakeClient, ONCOR, OFFER, offer


class CatalogRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.data = self.root / 'data'; self.data.mkdir()
        self.store = CatalogStore(self.root / 'catalog.sqlite3'); self.store.initialize()
        self.client = FakeClient()

    def app(self):
        return TestClient(create_app(self.root / 'comparisons.sqlite3', catalog_path=self.store.path))

    def sync_txu(self):
        return sync_txu(self.store, self.data, ['78681'], self.client)

    def test_pdf_api_terms_and_comparison_survive_missing_pdf(self):
        path = self.data / 'plan.pdf'; path.write_bytes(b'pdf')
        with patch('backend.catalog.sync.read_pages', return_value=(PAGES, [])):
            sync(self.store, self.data, Extractor())
        path.unlink()
        with self.app() as client, patch('backend.catalog.extract.read_pages', side_effect=AssertionError('No PDFs')):
            record = client.get('/api/catalog/records?source_type=pdf&zip_code=75201').json()['records'][0]
            self.assertEqual(record['source_details'], fixture().model_dump(mode='json'))
            self.assertEqual(record['schema_version'], 'catalog-v1')
            self.assertEqual(client.get(record['record_url']).json(), record)
            self.assertEqual(client.get('/api/catalog/records?source_type=pdf&zip_code=77002').json()['total'], 0)
            response = client.post('/api/comparisons', json={'zip_code': '75201', 'data_source': 'catalog', 'monthly_kwh': [1000]*12})
            self.assertEqual(response.status_code, 201, response.text)
            result = response.json()['recommendations'][0]
            self.assertEqual(result['annual_cost'], '2100.00')
            self.assertEqual(result['pricing_basis'], 'custom_efl')
            self.assertEqual(result['source_revision'], record['revision_id'])
            self.assertEqual(result['source_url'], record['record_url'])
            expected = [dict(kwh=str(e['kwh']), cents_per_kwh=e['cents_per_kwh'],
                             page=e['evidence']['page'], quote=e['evidence']['quote']) for e in record['examples']]
            self.assertEqual(result['efl_price_examples'], expected)
            saved = client.get('/api/comparisons/' + response.json()['id']).json()
            self.assertEqual(saved['recommendations'][0]['efl_price_examples'], expected)
            from backend.catalog.compare import compare_catalog
            from backend.models import ComparisonRequest
            frozen = compare_catalog(ComparisonRequest(zip_code='75201', data_source='catalog',
                monthly_kwh=[1000]*12), self.store, frozen_records=[record])
            self.assertEqual(frozen.recommendations[0].model_dump(mode='json')['efl_price_examples'], expected)
            self.assertEqual(str(frozen.recommendations[0].annual_cost), '1380.00')
            self.assertTrue(any(e.get('page') == 1 for e in record['provenance']))
        sync(self.store, self.data, Extractor())
        self.assertEqual(records(self.store, 'pdf'), [])

    def test_catalog_efl_ranges_and_projection_consistency(self):
        from decimal import Decimal as D
        from backend.catalog.compare import compare_catalog
        from backend.models import ComparisonRequest
        path = self.data / 'plan.pdf'; path.write_bytes(b'pdf')
        with patch('backend.catalog.sync.read_pages', return_value=(PAGES, [])):
            sync(self.store, self.data, Extractor())
        record = records(self.store, 'pdf')[0]
        record['_comparison_pricing_basis'] = 'custom_efl'
        for example, price in zip(record['examples'], ('19.7', '6.8', '12.8')):
            example['cents_per_kwh'] = price
        usage = [0, 500, 500.1, 800, 1000, 1000.1, 1800, 2000, 2000.1, 2100, 800, 1000]
        request = ComparisonRequest(zip_code='75201', data_source='catalog', monthly_kwh=usage,
            recommendation_options={'max_contract_months': 24})
        result = compare_catalog(request, None, frozen_records=[record])
        plan = result.recommendations[0]
        self.assertEqual([m.average_price_cents for m in plan.monthly_costs],
            list(map(D, ['19.7']*5 + ['6.8']*3 + ['12.8']*2 + ['19.7']*2)))
        self.assertEqual(plan.monthly_costs[3].energy, D('157.60'))
        for month in plan.horizon_monthly_costs:
            self.assertEqual(month['energy'], (month['kwh'] * month['average_price_cents'] / 100).quantize(D('.01'), rounding='ROUND_HALF_UP'))
            self.assertEqual(month['total'], month['energy'] + month['base_fee'] + month['delivery'] - month['credit'])
        self.assertEqual(plan.horizon_cost, result.recommendation_result.best_overall.horizon_cost)
        other = copy.deepcopy(record); other['id'] += '-other'
        other['examples'][0]['cents_per_kwh'] = '18'
        mixed = compare_catalog(request, None, frozen_records=[record, other])
        energies = {p.plan_id: p.monthly_costs[3].energy for p in mixed.recommendations}
        self.assertEqual(energies, {record['id']: D('157.60'), other['id']: D('144.00')})
        for examples in ([], [record['examples'][0]]*2):
            bad = copy.deepcopy(record); bad['examples'] = examples
            excluded = compare_catalog(request, None, frozen_records=[bad])
            self.assertFalse(excluded.recommendations)
            self.assertTrue(excluded.excluded_plans)

    def test_txu_api_and_comparison_share_terms_without_documents(self):
        self.client.offers[0]['documents'] = []
        self.assertEqual(self.sync_txu()['blocked'], 0)
        with self.app() as client, patch('backend.providers.txu.TxuClient', side_effect=AssertionError('No provider fetch')):
            record = client.get('/api/catalog/records?source_type=txu&zip_code=78681&calculable=true').json()['records'][0]
            self.assertEqual(record['source_details'], self.client.offers[0])
            self.assertIsNone(record['issue_date']); self.assertIsNone(record['document_url'])
            self.assertEqual(record['provenance'][0]['kind'], 'provider_api')
            self.assertNotIn('page', record['provenance'][0])
            response = client.post('/api/comparisons', json={'zip_code': '78681', 'data_source': 'txu', 'monthly_kwh': [1000]*12})
            self.assertEqual(response.status_code, 201, response.text)
            result = response.json()['recommendations'][0]
            self.assertEqual(result['annual_cost'], '1947.72')
            self.assertEqual(result['monthly_costs'][0]['total'], '162.31')
            self.assertEqual(result['efl_price_examples'], [])
            self.assertEqual(result['source_revision'], record['revision_id'])
            self.assertEqual(client.get(result['source_url']).json(), record)
            self.assertEqual(client.get('/api/catalog/records?source_type=txu&zip_code=79756').json()['total'], 0)
            self.assertEqual(client.get('/api/catalog/records?source_type=invalid').status_code, 422)
            self.assertEqual(client.get('/api/catalog/records?limit=0').status_code, 422)
            self.assertEqual(client.get('/api/catalog/records/bad').status_code, 404)

    def test_legacy_pdf_errors_do_not_gate_api_or_change_freshness(self):
        self.sync_txu(); old = cached(self.store, '78681')['fetched_at']
        with self.store.connection() as db:
            row = db.execute('SELECT id,payload FROM txu_refreshes').fetchone()
            payload = json.loads(row['payload']); payload['offers'][0]['issues'] = ['EFL response is not a PDF']
            payload['offers'][0].pop('document_issues')
            db.execute('UPDATE txu_refreshes SET payload=? WHERE id=?', (json.dumps(payload), row['id']))
        result = public_cache(self.store, '78681')
        self.assertTrue(result['offers'][0]['calculation_eligible'])
        self.assertEqual(result['fetched_at'], old)
        self.assertTrue(records(self.store, 'txu')[0]['calculation_eligible'])
        with self.store.connection() as db:
            db.execute("UPDATE txu_refreshes SET fetched_at='2000-01-01T00:00:00+00:00'")
        self.assertFalse(records(self.store, 'txu')[0]['calculation_eligible'])

    def test_incomplete_or_unsupported_api_terms_are_excluded(self):
        cases = []
        raw = offer(); raw['rates'] = raw['rates'][1:]; cases.append(raw)
        raw = offer(); raw['rates'].append(copy.deepcopy(raw['rates'][0])); cases.append(raw)
        raw = offer(); raw['rates'][0]['price'] = 'NaN'; cases.append(raw)
        raw = offer(); raw['rates'].append({'type': 'UsageCharge', 'price': '5'}); cases.append(raw)
        raw = offer(); raw['rates'][0]['minimumKwh'] = 1000; cases.append(raw)
        raw = offer(); raw['fees'] = [{'type': 'MonthlyFee', 'amount': 5, 'monthly': True}]; cases.append(raw)
        raw = offer(); raw['description'] = 'Get $35 bill credit at 500 kWh'; cases.append(raw)
        raw = offer(); raw['description'] = 'Free weekends'; cases.append(raw)
        raw = offer(); raw['term']['length'] = 6; cases.append(raw)
        raw = offer(); raw['hideOnGrid'] = True; cases.append(raw)
        raw = offer(); raw['rates'][4]['price'] = '0.12'; cases.append(raw)
        raw = offer(); raw['rates'] = None; cases.append(raw)
        raw = offer(); raw['term'] = 'unknown'; cases.append(raw)
        raw = offer(); raw.pop('billCredits'); cases.append(raw)
        for raw in cases:
            with self.subTest(raw=raw):
                result = txu_record({'raw': raw, 'external_id': OFFER, 'name': raw['name']}, {'id': ONCOR, 'name': 'Oncor'}, '78681', None)
                self.assertFalse(result['calculation_eligible'])
                self.assertTrue(result['calculation_issues'])
                self.assertEqual(result['source_details'], raw)

    def test_rate_changes_version_records_and_withdrawals_remove_current_records(self):
        self.sync_txu(); before = records(self.store, 'txu')[0]
        self.client.offers[0]['rates'][0]['price'] = '0.089'
        self.sync_txu(); after = records(self.store, 'txu')[0]
        self.assertEqual(before['id'], after['id'])
        self.assertNotEqual(before['revision_id'], after['revision_id'])
        self.client.offers = []; self.sync_txu()
        self.assertEqual(records(self.store, 'txu'), [])
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM txu_refreshes').fetchone()[0], 3)

    def test_unsupported_pdf_terms_remain_visible_and_excluded(self):
        (self.data / 'plan.pdf').write_bytes(b'pdf')
        unsupported = fixture(); unsupported.unsupported_rules = ['Interval billing required']
        with patch('backend.catalog.sync.read_pages', return_value=(PAGES, [])), patch.object(Extractor, 'extract', return_value=unsupported):
            sync(self.store, self.data, Extractor())
        record = records(self.store, 'pdf')[0]
        self.assertFalse(record['calculation_eligible'])
        self.assertIn('Interval billing required', record['source_details']['unsupported_rules'])
        with self.app() as client:
            response = client.post('/api/comparisons', json={'zip_code': '75201', 'data_source': 'catalog', 'monthly_kwh': [1000]*12})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()['recommendations'], [])
            self.assertEqual(len(response.json()['rough_estimates']), 1)

    def import_pdf(self):
        (self.data / 'plan.pdf').write_bytes(b'pdf')
        with patch('backend.catalog.sync.read_pages', return_value=(PAGES, [])):
            sync(self.store, self.data, Extractor())

    def test_combined_sources_use_fresh_utility_to_resolve_unmapped_zip(self):
        self.import_pdf(); self.sync_txu()
        with self.app() as client:
            body = {'zip_code': '78681', 'data_source': 'catalog', 'monthly_kwh': [1000]*12}
            response = client.post('/api/comparisons', json=body)
            self.assertEqual(response.status_code, 201, response.text)
            result = response.json()
            self.assertEqual(result['data_mode'], 'catalog')
            self.assertEqual({p['name'] for p in result['recommendations']}, {'Saver', 'Simple Value 24'})
            self.assertEqual([p['annual_cost'] for p in result['recommendations']], ['1947.72', '2100.00'])
            self.assertEqual(result['utility']['id'], ONCOR)
            # A different delivery area must not bring Oncor PDFs into ranking.
            self.client.utilities[0]['name'] = 'CenterPoint'; self.sync_txu()
            result = client.post('/api/comparisons', json=body).json()
            self.assertEqual([p['name'] for p in result['recommendations']], ['Simple Value 24'])

    def test_combined_pdf_only_with_missing_or_stale_txu(self):
        self.import_pdf()
        with self.app() as client:
            body = {'zip_code': '75201', 'data_source': 'catalog', 'monthly_kwh': [1000]*12}
            result = client.post('/api/comparisons', json=body)
            self.assertEqual(result.status_code, 201, result.text)
            self.assertEqual([p['name'] for p in result.json()['recommendations']], ['Saver'])
            sync_txu(self.store, self.data, ['75201'], self.client)
            with self.store.connection() as db:
                db.execute("UPDATE txu_refreshes SET fetched_at='2000-01-01T00:00:00+00:00'")
            result = client.post('/api/comparisons', json=body).json()
            self.assertEqual([p['name'] for p in result['recommendations']], ['Saver'])
            self.assertTrue(any('stale' in reason for p in result['excluded_plans'] for reason in p['reasons']))
            self.assertTrue(any('only eligible PDF' in a for a in result['assumptions']))
            self.assertEqual(client.post('/api/comparisons', json={**body, 'zip_code': '99999'}).status_code, 422)

    def test_combined_txu_only_and_multiple_utilities_require_selection(self):
        from test_txu import OTHER
        self.sync_txu()
        with self.app() as client:
            body = {'zip_code': '78681', 'data_source': 'catalog', 'monthly_kwh': [1000]*12}
            response = client.post('/api/comparisons', json=body)
            self.assertEqual(response.status_code, 201)
            self.assertEqual(len(response.json()['recommendations']), 1)
            self.client.utilities.append({'id': OTHER, 'name': 'CenterPoint'})
            with patch.object(self.client, 'get_plans', side_effect=lambda z, u: [offer()] if u == ONCOR else []):
                self.sync_txu()
            self.assertEqual(client.post('/api/comparisons', json=body).status_code, 422)
            self.assertEqual(client.post('/api/comparisons', json={**body, 'utility_id': ONCOR}).status_code, 201)
            self.assertEqual(client.post('/api/comparisons', json={**body, 'utility_id': OTHER}).status_code, 422)

    def test_duplicate_energy_preserves_examples_and_independent_components(self):
        raw = offer(); raw['rates'].append({'type':'EnergyCharge','price':'0.12'})
        self.client.offers = [raw]; self.sync_txu()
        with self.app() as client:
            p = client.get('/api/catalog/records?source_type=txu&zip_code=78681').json()['records'][0]
        self.assertEqual(p['source_details'], raw)
        self.assertEqual({c['kind'] for c in p['components']}, {'base','delivery_energy','delivery_fixed'})
        self.assertEqual([e['kwh'] for e in p['examples']], [500,1000,2000])
        self.assertEqual(p['examples'][1]['cents_per_kwh'], '16.200')
        self.assertTrue(any('EnergyCharge has duplicate' in s for s in p['calculation_issues']))
        self.assertFalse(any('missing' in s for s in p['calculation_issues']))
        self.assertFalse(p['calculation_eligible'])
        self.assertEqual(len(p['price_checks']),3)
        self.assertTrue(all(c['status']=='not_checked' and c['passed'] is None for c in p['price_checks']))
        self.assertTrue(p['rough_estimate']['supported'])

    def test_invalid_example_and_component_only_remove_their_own_fields(self):
        for kind in ('duplicate','invalid','absent'):
            raw = offer()
            if kind == 'duplicate':raw['rates'].append(copy.deepcopy(raw['rates'][4]))
            if kind == 'invalid':raw['rates'][4]['price']='NaN'
            if kind == 'absent':raw['rates'].pop(4)
            p=txu_record({'raw':raw,'external_id':OFFER,'name':raw['name']},{'id':ONCOR,'name':'Oncor'},'78681',None)
            self.assertEqual(len(p['components']),4)
            self.assertEqual([e['kwh'] for e in p['examples']],[1000,2000])
            self.assertFalse(p['calculation_eligible'])
            self.assertEqual(any('missing the 500' in i for i in p['calculation_issues']),kind=='absent')
        raw=offer();raw['rates'][0]['minimumKwh']=1000
        raw['rates'].append({'type':'UnknownFee','price':'3'})
        p=txu_record({'raw':raw,'external_id':OFFER,'name':raw['name']},{'id':ONCOR,'name':'Oncor'},'78681',None)
        self.assertEqual(len(p['components']),3)
        self.assertEqual(len(p['examples']),3)
        self.assertFalse(p['calculation_eligible'])
        self.assertTrue(any('EnergyCharge has unsupported' in i for i in p['calculation_issues']))
