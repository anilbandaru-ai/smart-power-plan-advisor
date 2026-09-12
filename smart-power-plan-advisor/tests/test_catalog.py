import copy
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.catalog.api import create_router
from backend.catalog.models import ExtractedPlan
from backend.catalog.pricing import calculate, validate
from backend.catalog.store import CatalogStore
from backend.catalog.sync import sync
from backend.catalog.compare import compare_catalog
from backend.models import ComparisonRequest

TEXT = 'Example Power Saver Oncor Fixed 12 months 2026-09-11. Energy 10 cents per kWh. Base 0 dollars per month. Delivery 5 cents per kWh plus 5 dollars per month. Credit 40 dollars at usage >= 1000 kWh. Examples: 500 kWh 16 cents, 1000 kWh 11.5 cents, 2000 kWh 13.25 cents. Exit fee 150 dollars.'
PAGES = [{'page':1,'text':TEXT}]


def fixture():
    evidence = {'page':1,'quote':TEXT}
    def fact(value):return {'value':value,'evidence':evidence}
    def component(kind, amount, unit, minimum=None):
        return dict(kind=kind,amount=str(amount),unit=unit,minimum_kwh=minimum,minimum_inclusive=True,
                    maximum_kwh=None,maximum_inclusive=False,evidence=evidence)
    return ExtractedPlan.model_validate(dict(name=fact('Saver'),provider=fact('Example Power'),service_area=fact('Oncor'),
        issue_date=fact('2026-09-11'),product_type=fact('Fixed'),contract_term=fact('12'),termination_terms=fact('Exit fee 150 dollars'),
        components=[component('energy',10,'cents_per_kwh'),component('base',0,'usd_per_month'),
                    component('delivery_energy',5,'cents_per_kwh'),component('delivery_fixed',5,'usd_per_month'),
                    component('credit',40,'usd_per_month','1000')],
        examples=[dict(kwh=k,cents_per_kwh=v,evidence=evidence) for k,v in [(500,'16'),(1000,'11.5'),(2000,'13.25')]],
        unsupported_rules=[],extraction_notes=[]))


class Extractor:
    model='test-model'
    def __init__(self):self.calls=0
    def extract(self,pages):self.calls+=1;return fixture()


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'data';self.root.mkdir()
        self.store=CatalogStore(Path(self.tmp.name)/'plans.sqlite3')
        self.extractor=Extractor()
        self.page_patch=patch('backend.catalog.sync.read_pages',return_value=(PAGES,[]));self.page_patch.start();self.addCleanup(self.page_patch.stop)

    def write(self,name='plan.pdf',content=b'pdf-1'):
        path=self.root/name;path.write_bytes(content);return path

    def test_incremental_duplicate_changed_deleted_and_revision_history(self):
        a=self.write();b=self.write('other.PDF')
        summary=sync(self.store,self.root,self.extractor)
        self.assertEqual(summary['extracted'],1);self.assertEqual(summary['reused'],1)
        records=self.store.all_plans();self.assertEqual(len(records),1);self.assertEqual(len(records[0]['sources']),2)
        old=records[0]['revision_id']
        self.assertEqual(sync(self.store,self.root,self.extractor)['extracted'],0)
        self.assertEqual(self.extractor.calls,1)
        a.write_bytes(b'pdf-2');b.unlink()
        self.assertEqual(sync(self.store,self.root,self.extractor)['removed'],1)
        records=self.store.all_plans();self.assertNotEqual(records[0]['revision_id'],old)
        with self.store.connection() as db:self.assertEqual(db.execute('select count(*) from revisions').fetchone()[0],2)
        a.unlink();sync(self.store,self.root,self.extractor);self.assertEqual(self.store.all_plans(),[])

    def test_failed_changed_source_does_not_serve_old_terms_and_retry_recovers(self):
        p=self.write();sync(self.store,self.root,self.extractor);p.write_bytes(b'changed')
        with patch.object(self.extractor,'extract',side_effect=RuntimeError('SECRET')):
            result=sync(self.store,self.root,self.extractor)
        self.assertEqual(result['failed'],1);self.assertEqual(self.store.all_plans(),[])
        self.assertNotIn('SECRET',json.dumps(self.store.status()))
        calls = self.extractor.calls
        sync(self.store,self.root,self.extractor)
        self.assertEqual(self.extractor.calls,calls)
        sync(self.store,self.root,self.extractor,retry=True)
        self.assertEqual(len(self.store.all_plans()),1)

    def test_missing_root_does_not_deactivate_and_path_escape_is_rejected(self):
        self.write();sync(self.store,self.root,self.extractor)
        with self.assertRaises(FileNotFoundError):sync(self.store,self.root/'missing',self.extractor)
        self.assertEqual(len(self.store.all_plans()),1)
        outside=Path(self.tmp.name)/'outside.pdf';outside.write_bytes(b'secret')
        (self.root/'escape.pdf').symlink_to(outside)
        result=sync(self.store,self.root,self.extractor)
        self.assertEqual(result['failed'],1)

    def test_api_filters_pagination_sources_and_hash_guard(self):
        p=self.write();sync(self.store,self.root,self.extractor)
        app=FastAPI();app.include_router(create_router(self.store,self.root))
        with TestClient(app) as client:
            data=client.get('/api/catalog/plans?calculable=true&provider=example&service_area=Oncor').json()
            self.assertEqual(data['total'],1);plan=data['plans'][0]
            self.assertEqual(client.get('/api/catalog/plans?offset=1').json()['plans'],[])
            self.assertEqual(client.get('/api/catalog/plans?limit=0').status_code,422)
            self.assertEqual(client.get('/api/catalog/plans/'+plan['id']).status_code,200)
            self.assertEqual(client.get(plan['document_url']).content,b'pdf-1')
            p.write_bytes(b'new');self.assertEqual(client.get(plan['document_url']).status_code,404)
            self.assertEqual(client.get('/api/catalog/plans/'+'f'*24).status_code,404)

    def test_pdf_api_comparison_snapshot_survives_catalog_removal(self):
        from backend.api.main import create_app
        path=self.write();sync(self.store,self.root,self.extractor)
        db=Path(self.tmp.name)/'comparisons.sqlite3'
        with TestClient(create_app(db,catalog_path=self.store.path)) as client:
            response=client.post('/api/comparisons',json={'zip_code':'75201','monthly_kwh':[1000]*12,'data_source':'pdf'})
            self.assertEqual(response.status_code,201,response.text)
            saved=response.json();self.assertEqual(saved['data_mode'],'pdf')
            self.assertEqual(saved['recommendations'][0]['annual_cost'],'1380.00')
        path.unlink();sync(self.store,self.root,self.extractor)
        with TestClient(create_app(db,catalog_path=self.store.path)) as client:
            self.assertEqual(client.get('/api/comparisons/'+saved['id']).json(),saved)
            self.assertEqual(client.post('/api/comparisons',json={'zip_code':'75201','monthly_kwh':[1000]*12,'data_source':'pdf'}).status_code,422)

    def test_pdf_comparison_exact_cost_and_exclusion(self):
        self.write();sync(self.store,self.root,self.extractor)
        request=ComparisonRequest(zip_code='75201',data_source='pdf',monthly_kwh=[1000]*12)
        result=compare_catalog(request,self.store)
        self.assertEqual(result.data_mode,'pdf');self.assertEqual(result.recommendations[0].annual_cost,Decimal('1380'))
        self.assertTrue(result.recommendations[0].source_revision)
        request.zip_code='77002'
        with self.assertRaises(ValueError):compare_catalog(request,self.store)


class PricingValidationTests(unittest.TestCase):
    def test_credit_boundaries_and_examples(self):
        plan=fixture();self.assertEqual(validate(plan,PAGES)[0],[])
        self.assertEqual(calculate(plan,Decimal('999'),1).total,Decimal('154.85'))
        self.assertEqual(calculate(plan,Decimal('1000'),1).total,Decimal('115.00'))
        plan.components[-1].minimum_inclusive=False
        self.assertEqual(calculate(plan,Decimal('1000'),1).credit,Decimal('0'))
        self.assertEqual(calculate(plan,Decimal('1000.0001'),1).credit,Decimal('40'))

    def test_missing_rates_unsupported_rules_quote_and_mismatch(self):
        plan=fixture();plan.components=[c for c in plan.components if c.kind!='delivery_energy']
        self.assertTrue(any('delivery_energy' in s for s in validate(plan,PAGES)[0]))
        plan=fixture();plan.unsupported_rules=['Free nights requires interval usage']
        self.assertIn(plan.unsupported_rules[0],validate(plan,PAGES)[0])
        plan=fixture();plan.components[0].amount=Decimal('20')
        issues=validate(plan,PAGES)[0]
        self.assertTrue(any('amount not present' in s for s in issues));self.assertTrue(any('mismatch' in s for s in issues))
        plan=fixture();plan.name.evidence.quote='fabricated quote'
        self.assertTrue(validate(plan,PAGES)[0])


class RealPdfParserTests(unittest.TestCase):
    def test_all_repository_pdfs_parse_and_supported_prices_reconcile(self):
        try:
            from backend.catalog.extract import read_pages
            from backend.catalog.parser import parse_known
        except ImportError as error:
            self.skipTest(str(error))
        root=Path(__file__).resolve().parents[1]/'data'
        files=list(root.rglob('*.pdf'));self.assertGreaterEqual(len(files),22)
        results={}
        for path in files:
            pages,warnings=read_pages(path.read_bytes())
            plan=parse_known(pages)
            self.assertIsNotNone(plan,str(path))
            issues,checks=validate(plan,pages)
            results[plan.name.value]=(plan,issues)
            if not issues:self.assertTrue(all(c['passed'] for c in checks))
            if path.name in ('EFL-5.pdf','EFL-9.pdf') and path.parent.name=='choosetexaspower':
                self.assertIn('Blank page 2 skipped',warnings)
        self.assertEqual(results['Gexa Saver Plus 12'][1],[])
        self.assertEqual(results['Reliant Secure Advantage® 12 plan'][1],[])
        self.assertTrue(results['4Change Energy Maxx Saver Value 12SM'][1])
        self.assertTrue(results['Reliant Free Overnight 12 plan'][1])
        self.assertTrue(results['SimpleSaver 11'][1])
        four=results['4Change Energy Maxx Saver Value 12SM'][0]
        credit=next(c for c in four.components if c.kind=='credit')
        self.assertEqual(credit.minimum_kwh,Decimal('999'));self.assertFalse(credit.minimum_inclusive)
        secure=results['Reliant Secure Advantage® 12 plan'][0]
        self.assertEqual(calculate(secure,Decimal('799'),1).base_fee,Decimal('9.95'))
        self.assertEqual(calculate(secure,Decimal('800'),1).base_fee,Decimal('0'))

    def test_blank_and_scanned_pages_are_distinguished(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from backend.catalog.extract import read_pages
        blank=SimpleNamespace(chars=[],images=[],curves=[],lines=[],rects=[])
        scanned=SimpleNamespace(chars=[],images=[{}],curves=[],lines=[],rects=[])
        text=SimpleNamespace(chars=[{}],images=[],curves=[],lines=[],rects=[])
        document=MagicMock();document.__enter__.return_value.pages=[text,blank]
        with patch('pdfplumber.open',return_value=document),patch('backend.knowledge.documents.extract_page',side_effect=[TEXT,'']):
            pages,warnings=read_pages(b'fixture')
            self.assertEqual(len(pages),1);self.assertEqual(warnings,['Blank page 2 skipped'])
        document.__enter__.return_value.pages=[scanned]
        with patch('pdfplumber.open',return_value=document),patch('backend.knowledge.documents.extract_page',return_value=''):
            with self.assertRaisesRegex(ValueError,'OCR/review'):read_pages(b'fixture')

    def test_known_parser_does_not_require_api_key(self):
        from backend.catalog.extract import Extractor,read_pages
        from backend.knowledge.config import Settings
        root=Path(__file__).resolve().parents[1]/'data'
        pages,_=read_pages((root/'choosetexaspower'/'EFL-6.pdf').read_bytes())
        extractor=Extractor(Settings())
        with patch('openai.OpenAI',side_effect=AssertionError('No API call for known layouts')):
            self.assertEqual(extractor.extract(pages).name.value,'Gexa Saver Plus 12')
        extractor.close()

    def test_changed_pricing_language_requires_review_but_numeric_updates_parse(self):
        from backend.catalog.extract import read_pages
        from backend.catalog.parser import parse_known
        root=Path(__file__).resolve().parents[1]/'data'
        pages,_=read_pages((root/'choosetexaspower'/'EFL-6.pdf').read_bytes())
        changed=copy.deepcopy(pages)
        changed[0]['text']=changed[0]['text'].replace('12.7600','13.7600')
        plan=parse_known(changed)
        self.assertIsNotNone(plan)
        self.assertTrue(any('mismatch' in issue for issue in validate(plan,changed)[0]))
        changed=copy.deepcopy(pages)
        changed[0]['text']+='\nAdditional recurring membership fee: $25.00 per month.'
        self.assertIsNone(parse_known(changed))
