"""TXU contracts and independent bill expectations; no network/model calls."""
import copy
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from backend.catalog.models import ExtractedPlan
from backend.catalog.store import CatalogStore
from backend.catalog.sync import sync
from backend.catalog.txu import cached, public_cache, sync_txu
from backend.providers.txu import TxuClient, normalized_rates
from backend.catalog.records import txu_record

ONCOR = 'ea0ad3a5-3fc6-4d9f-894a-e21a751c33fe'
OTHER = '1c2c19b4-db14-4e24-ae7d-baf067ea4e7f'
OFFER = 'a8db4a91-3b48-4f63-a373-a831fd0e25c6'
URL = 'https://shopping.txu.com/PDFGenerator?formType=EnergyFactsLabel&comProdId=test'
TEXT = ('TXU Energy Simple Value 24 Oncor Fixed 24 months 2026-09-12. '
        'Energy 8.8 cents per kWh. Base 9.95 dollars per month. '
        'Delivery 6.03 cents per kWh plus 4.06 dollars per month. '
        'Examples: 500 kWh 17.6 cents, 1000 kWh 16.2 cents, 2000 kWh 15.5 cents.')
PAGES = [{'page': 1, 'text': TEXT}]


def plan():
    evidence = {'page': 1, 'quote': TEXT}
    def fact(value): return {'value': value, 'evidence': evidence}
    components = [dict(kind=kind, amount=amount, unit=unit, minimum_kwh=None,
                       maximum_kwh=None, minimum_inclusive=True, maximum_inclusive=False,
                       evidence=evidence) for kind, amount, unit in [
        ('energy', '8.8', 'cents_per_kwh'), ('base', '9.95', 'usd_per_month'),
        ('delivery_energy', '6.03', 'cents_per_kwh'), ('delivery_fixed', '4.06', 'usd_per_month')]]
    return ExtractedPlan(name=fact('Simple Value 24'), provider=fact('TXU Energy'),
        service_area=fact('Oncor'), issue_date=fact('2026-09-12'), product_type=fact('Fixed'),
        contract_term=fact('24'), termination_terms=None, components=components,
        examples=[dict(kwh=k, cents_per_kwh=v, evidence=evidence) for k, v in [(500, '17.6'), (1000, '16.2'), (2000, '15.5')]],
        unsupported_rules=[], extraction_notes=['Recognized deterministic EFL parser'])


def offer():
    return {'id': OFFER, 'name': 'Simple Value 24', 'utility': {'id': ONCOR},
        'supplier': {'name': 'TXU Energy'}, 'active': True, 'hideOnGrid': False,
        'type': 'Fixed', 'term': {'length': 24, 'type': 'FixedMonths'},
        'documents': [{'type': 'Efl', 'url': URL}], 'billCredits': [],
        'rates': [{'type': key, 'price': value} for key, value in [
            ('EnergyCharge', '0.088'), ('BaseCharge', '9.95'), ('DeliveryChargeKwh', '0.0603'),
            ('DeliveryChargeMonthly', '4.06'), ('FiveHundredKwh', '0.176'),
            ('OneThousandKwh', '0.162'), ('TwoThousandKwh', '0.155')]]}


class FakeClient:
    def __init__(self):
        self.utilities = [{'id': ONCOR, 'name': 'Oncor'}]
        self.offers = [offer()]
        self.content = b'%PDF-test'
        self.calls = []
    def get_utilities(self, zip_value):
        self.calls.append(('utilities', zip_value)); return copy.deepcopy(self.utilities)
    def get_plans(self, zip_value, utility):
        self.calls.append(('plans', zip_value, utility)); return copy.deepcopy(self.offers)
    def get_efl(self, url):
        self.calls.append(('efl', url)); return self.content


class TxuClientTests(unittest.TestCase):
    def make(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        return TxuClient(client)

    def test_response_shapes_and_same_zip(self):
        calls = []
        def handler(request):
            calls.append(request)
            if request.url.path.endswith('/utilities/'):
                return httpx.Response(200, json={'data': {'utilities': [{'id': ONCOR, 'name': 'Oncor'}], 'gridFeaturedConfigs': []}})
            return httpx.Response(200, json=[offer()])
        client = self.make(handler)
        utilities = client.get_utilities('79756')
        self.assertEqual(client.get_plans('79756', utilities[0]['id'])[0]['id'], OFFER)
        self.assertTrue(all(r.url.params['zipCode'] == '79756' for r in calls))
        self.assertEqual(calls[1].url.params['utilityId'], ONCOR)
        with self.assertRaises(ValueError): client.get_utilities('1234x')

    def test_malformed_mismatched_duplicate_and_empty_listings(self):
        bad = offer(); bad['utility']['id'] = OTHER
        wrong = offer(); wrong['supplier']['name'] = 'Other provider'
        for response in ({'data': []}, [bad], [wrong], [offer(), offer()]):
            client = self.make(lambda r: httpx.Response(200, json=response))
            with self.assertRaises(ValueError): client.get_plans('78681', ONCOR)
        client = self.make(lambda r: httpx.Response(200, json=[]))
        self.assertEqual(client.get_plans('78681', ONCOR), [])
        with self.assertRaises(ValueError): client.get_utilities('78681')

    def test_download_redirect_guards_and_non_pdf(self):
        calls = []
        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(302, headers={'location': 'http://127.0.0.1/secret'})
        client = self.make(handler)
        with self.assertRaises(ValueError): client.get_efl(URL)
        self.assertEqual(len(calls), 1)
        for url in ['http://shopping.txu.com/a', 'https://shopping.txu.com.evil/a', 'https://user@shopping.txu.com/a']:
            with self.assertRaises(ValueError): client.get_efl(url)
        client = self.make(lambda r: httpx.Response(200, content=b'<html>blocked</html>'))
        with self.assertRaisesRegex(ValueError, 'not a PDF'): client.get_efl(URL)
        client = self.make(lambda r: httpx.Response(403))
        with self.assertRaises(httpx.HTTPStatusError): client.get_efl(URL)

    def test_transient_retry_redirect_and_size_limits(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, content=b'%PDF-ok')
        with patch('backend.providers.txu.time.sleep'):
            self.assertEqual(self.make(handler).get_efl(URL), b'%PDF-ok')
        self.assertEqual(len(calls), 2)
        client = self.make(lambda r: httpx.Response(302, headers={'location': 'https://residential.txu.com/next'}) if r.url.path != '/next' else httpx.Response(200, content=b'%PDF-next'))
        self.assertEqual(client.get_efl(URL), b'%PDF-next')
        client = self.make(lambda r: httpx.Response(200, content=b'x' * (2 * 1024 * 1024 + 1)))
        with self.assertRaisesRegex(ValueError, 'size limit'): client.get_utilities('78681')
        client = self.make(lambda r: httpx.Response(200, content=b'%PDF-' + b'x' * (20 * 1024 * 1024)))
        with self.assertRaisesRegex(ValueError, 'size limit'): client.get_efl(URL)
        attempts = []
        def timeout(request):
            attempts.append(request)
            raise httpx.ReadTimeout('private upstream detail')
        with patch('backend.providers.txu.time.sleep'):
            with self.assertRaises(httpx.ReadTimeout): self.make(timeout).get_utilities('78681')
        self.assertEqual(len(attempts), 3)

    def test_rate_units_and_missing_credit_safeguard(self):
        rates = normalized_rates(offer())
        self.assertEqual(rates['energy'], Decimal('8.8'))
        self.assertEqual(rates['delivery_energy'], Decimal('6.03'))
        self.assertEqual(rates['delivery_fixed'], Decimal('4.06'))
        self.assertEqual(txu_record({'raw': offer(), 'external_id': OFFER, 'name': 'Simple Value 24'}, {'id': ONCOR, 'name': 'Oncor'}, '78681', None)['calculation_issues'], [])
        credited = offer(); credited['description'] = 'Get a $35 bill credit at 500 kWh.'
        self.assertTrue(any('credit' in e for e in txu_record({'raw': credited, 'external_id': OFFER, 'name': credited['name']}, {'id': ONCOR, 'name': 'Oncor'}, '78681', None)['calculation_issues']))
        altered = offer(); altered['rates'][0]['price'] = '0.128'
        self.assertTrue(any('mismatch' in e for e in txu_record({'raw': altered, 'external_id': OFFER, 'name': altered['name']}, {'id': ONCOR, 'name': 'Oncor'}, '78681', None)['calculation_issues']))
        for value in ['NaN', '-1', 'Infinity']:
            altered['rates'][0]['price'] = value
            with self.assertRaises(ValueError): normalized_rates(altered)


class TxuSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'data'; self.root.mkdir()
        self.store = CatalogStore(Path(self.tmp.name) / 'catalog.sqlite3')
        self.client = FakeClient()
        pages = patch('backend.catalog.txu.read_pages', return_value=(PAGES, [])); pages.start(); self.addCleanup(pages.stop)
        parser = patch('backend.catalog.txu.parse_known', side_effect=lambda pages: plan())
        self.parse_mock = parser.start(); self.addCleanup(parser.stop)

    def sync(self, *zips, download_efls=False): return sync_txu(self.store, self.root, zips or ['78681'], self.client, download_efls=download_efls)

    def test_identical_efls_deduplicate_and_changed_bytes_get_revision(self):
        self.assertEqual(self.sync('78681', '79756', download_efls=True)['offers'], 2)
        self.assertEqual(self.parse_mock.call_count, 1)
        self.assertEqual(len([c for c in self.client.calls if c[0] == 'efl']), 1)
        first = cached(self.store, '78681')['offers'][0]
        self.assertEqual(self.sync(download_efls=True)['blocked'], 0)
        self.assertEqual(self.parse_mock.call_count, 1)
        self.client.content = b'%PDF-changed'; self.sync(download_efls=True)
        second = cached(self.store, '78681')['offers'][0]
        self.assertNotEqual(first['revision_id'], second['revision_id'])
        self.assertTrue((self.root / first['source_path']).exists())
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM txu_refreshes').fetchone()[0], 4)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM revisions').fetchone()[0], 2)

    def test_failure_expiry_and_empty_refresh_are_zip_scoped(self):
        self.sync('78681', '79756')
        with patch.object(self.client, 'get_plans', side_effect=RuntimeError('SECRET')):
            self.assertEqual(self.sync()['failed'], 1)
        stale = public_cache(self.store, '78681')
        self.assertTrue(stale['stale']); self.assertFalse(stale['offers'][0]['calculation_eligible'])
        self.assertNotIn('SECRET', json.dumps(stale))
        self.assertFalse(cached(self.store, '79756')['stale'])
        self.client.offers = []; self.sync()
        self.assertEqual(cached(self.store, '78681')['offers'], [])
        self.assertEqual(len(cached(self.store, '79756')['offers']), 1)
        with self.store.connection() as db:
            db.execute("UPDATE txu_refreshes SET fetched_at='2000-01-01T00:00:00+00:00' WHERE zip_code='79756'")
        self.assertTrue(public_cache(self.store, '79756')['stale'])

    def test_partial_utility_listing_failure_does_not_publish(self):
        self.sync()
        self.client.utilities.append({'id': OTHER, 'name': 'CenterPoint'})
        def listings(zip_value, utility):
            if utility == OTHER: raise RuntimeError('second failed')
            return [offer()]
        with patch.object(self.client, 'get_plans', side_effect=listings): self.sync()
        data = cached(self.store, '78681')
        self.assertTrue(data['stale']); self.assertEqual(len(data['utilities']), 1)

    def test_api_prices_do_not_require_efl_download_or_recognized_layout(self):
        with patch.object(self.client, 'get_efl', side_effect=AssertionError('No PDF fetch')):
            self.assertEqual(self.sync()['blocked'], 0)
        self.assertEqual(self.parse_mock.call_count, 0)
        self.client.offers[0]['documents'] = []
        self.assertEqual(self.sync()['blocked'], 0)
        self.assertTrue(public_cache(self.store, '78681')['offers'][0]['calculation_eligible'])
        self.client.offers = [offer()]
        with patch.object(self.client, 'get_efl', side_effect=RuntimeError('SECRET')):
            self.assertEqual(self.sync(download_efls=True)['blocked'], 0)
        result = public_cache(self.store, '78681')['offers'][0]
        self.assertTrue(result['document_issues']); self.assertTrue(result['calculation_eligible'])
        self.assertNotIn('SECRET', json.dumps(result))
        with patch('backend.catalog.txu.parse_known', return_value=None):
            self.assertEqual(self.sync(download_efls=True)['blocked'], 0)
        self.assertTrue(public_cache(self.store, '78681')['offers'][0]['document_issues'])

    def test_local_sync_preserves_managed_sources_and_refuses_symlinks(self):
        self.sync(download_efls=True)
        from test_catalog import Extractor
        extractor = Extractor()
        result = sync(self.store, self.root, extractor)
        self.assertEqual(result['files'], 0); self.assertEqual(result['removed'], 0)
        self.assertEqual(len(self.store.all_plans()), 1); self.assertEqual(extractor.calls, 0)
        other = self.root / 'other'; other.mkdir()
        (self.root / '_txu').rename(self.root / 'archive')
        try: (self.root / '_txu').symlink_to(other, target_is_directory=True)
        except OSError: self.skipTest('Symlinks unavailable')
        self.assertEqual(self.sync(download_efls=True)['blocked'], 0)
        self.assertTrue(public_cache(self.store, '78681')['offers'][0]['document_issues'])
        self.assertEqual(list(other.iterdir()), [])

    def test_api_costs_selection_isolation_and_persisted_snapshot(self):
        from backend.api.main import create_app
        self.sync()
        app = create_app(Path(self.tmp.name) / 'comparisons.sqlite3', catalog_path=self.store.path)
        body = {'zip_code': '78681', 'data_source': 'txu', 'monthly_kwh': [1000] * 12}
        with TestClient(app) as client:
            with patch('backend.providers.txu.TxuClient', side_effect=AssertionError('API must not fetch')):
                response = client.get('/api/catalog/txu?zip_code=78681')
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('raw', response.json()['offers'][0])
                response = client.post('/api/comparisons', json=body)
            self.assertEqual(response.status_code, 201, response.text)
            saved = response.json()
            self.assertEqual(saved['data_mode'], 'txu'); self.assertEqual(saved['utility']['id'], ONCOR)
            # 88.00 energy + 9.95 base + (60.30 + 4.06) delivery = 162.31.
            self.assertEqual(saved['recommendations'][0]['annual_cost'], '1947.72')
            self.assertEqual(saved['recommendations'][0]['offer_sources'][0]['external_id'], OFFER)
            self.assertEqual(client.post('/api/comparisons', json={**body, 'zip_code': '79756'}).status_code, 422)
            self.assertEqual(client.post('/api/comparisons', json={**body, 'utility_id': OTHER}).status_code, 422)
            self.assertEqual(client.get('/api/catalog/txu?zip_code=abc').status_code, 422)
            duplicate = offer(); duplicate['id'] = OTHER
            self.client.offers.append(duplicate); self.sync()
            ranked = client.post('/api/comparisons', json=body).json()['recommendations']
            self.assertEqual(len(ranked), 2); self.assertNotEqual(ranked[0]['plan_id'], ranked[1]['plan_id'])
            self.client.utilities.append({'id': OTHER, 'name': 'CenterPoint'})
            with patch.object(self.client, 'get_plans', side_effect=lambda z, u: [offer()] if u == ONCOR else []): self.sync()
            self.assertEqual(client.post('/api/comparisons', json=body).status_code, 422)
            self.assertEqual(client.post('/api/comparisons', json={**body, 'utility_id': ONCOR}).status_code, 201)
            self.client.utilities = []; self.sync()
            self.assertEqual(client.post('/api/comparisons', json=body).status_code, 422)
            self.assertEqual(client.get('/api/comparisons/' + saved['id']).json(), saved)

    def test_txu_sources_cannot_leak_into_local_pdf_mode(self):
        from backend.catalog.compare import compare_catalog
        from backend.models import ComparisonRequest
        self.sync('75201')
        with self.assertRaisesRegex(ValueError, 'No calculable PDF'):
            compare_catalog(ComparisonRequest(zip_code='75201', data_source='pdf', monthly_kwh=[1000]*12), self.store)

    def test_unknown_documents_keep_distinct_identity_and_source_links(self):
        with patch('backend.catalog.txu.parse_known', return_value=None):
            self.sync('78681', download_efls=True)
            self.client.content = b'%PDF-another-unknown'
            self.sync('79756', download_efls=True)
        plans = self.store.all_plans()
        self.assertEqual(len(plans), 2)
        self.assertTrue(all(p['extraction_method'] == 'review_required' and p['extraction_model'] is None for p in plans))
        first = public_cache(self.store, '78681')['offers'][0]['document_url']
        second = public_cache(self.store, '79756')['offers'][0]['document_url']
        self.assertTrue(first); self.assertNotEqual(first, second)

    def test_optional_real_efl_is_read_without_model_and_keeps_document_issues(self):
        from backend.catalog.extract import read_pages
        from backend.catalog.parser import parse_known
        self.client.content = (Path(__file__).resolve().parents[1] / 'data/choosetexaspower/EFL-9.pdf').read_bytes()
        with patch('backend.catalog.txu.read_pages', side_effect=read_pages), \
             patch('backend.catalog.txu.parse_known', side_effect=parse_known), \
             patch('openai.OpenAI', side_effect=AssertionError('TXU must not call a model')):
            self.assertEqual(self.sync(download_efls=True)['blocked'], 0)
        data = public_cache(self.store, '78681')
        self.assertTrue(data['offers'][0]['revision_id'])
        self.assertTrue(any('Seasonal' in reason or 'summer bill credit' in reason for reason in data['offers'][0]['document_issues']))
