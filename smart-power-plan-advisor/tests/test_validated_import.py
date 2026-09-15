import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.catalog.store import CatalogStore
from backend.catalog.validated import import_validated
from test_catalog import fixture,PAGES


class ValidatedImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'data';self.root.mkdir()
        self.store=CatalogStore(Path(self.tmp.name)/'catalog.sqlite3')
        self.pages=patch('backend.catalog.validated.read_pages',return_value=(PAGES,[]));self.pages.start();self.addCleanup(self.pages.stop)
        self.parser=patch('backend.catalog.validated.parse_known',side_effect=lambda _:fixture());self.parse=self.parser.start();self.addCleanup(self.parser.stop)
    def write(self,name):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(name.encode());return p
    def rows(self,table):
        with self.store.connection() as db:return db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
    def test_good_bad_good_publishes_only_valid_and_logs_every_file(self):
        for name in ('a.pdf','b.pdf','c.pdf'):self.write(name)
        bad=fixture();bad.components=[]
        self.parse.side_effect=[fixture(),bad,fixture()]
        seen=[]
        result=import_validated(self.store,self.root,progress=lambda e:seen.append(e['outcome']))
        self.assertEqual(seen,['imported','rejected','imported'])
        self.assertEqual(self.rows('sources'),2);self.assertEqual(self.rows('revisions'),2)
        events=[json.loads(line) for line in (Path(result['log_directory'])/'events.jsonl').read_text().splitlines()]
        self.assertTrue(events[1]['issues']);self.assertTrue(events[0]['price_checks'])
        self.assertTrue((Path(result['log_directory'])/'report.md').exists())
        self.assertEqual(json.loads((Path(result['log_directory'])/'summary.json').read_text())['rejected'],1)
    def test_scoped_idempotent_and_changed_invalid_source_is_withdrawn(self):
        self.write('a.pdf');self.write('b.pdf')
        import_validated(self.store,self.root,files=['a.pdf'])
        result=import_validated(self.store,self.root,files=['a.pdf'])
        self.assertEqual(result['reused'],1);self.assertEqual(self.rows('revisions'),1)
        self.assertEqual(self.rows('sources'),1)
        self.parse.side_effect=lambda _:None
        result=import_validated(self.store,self.root,files=['a.pdf'])
        self.assertEqual(result['rejected'],1);self.assertEqual(self.rows('sources'),0)
        self.assertEqual(self.rows('revisions'),1)
    def test_unknown_and_managed_sources_never_import_or_call_model(self):
        self.write('unknown.pdf');self.write('_txu/download.pdf')
        self.parse.side_effect=lambda _:None
        with patch('backend.catalog.tdu.fetch_html',side_effect=AssertionError('No network')),patch('backend.catalog.extract.Extractor',side_effect=AssertionError('No model')):
            result=import_validated(self.store,self.root)
        self.assertEqual(result['skipped'],0);self.assertEqual(result['rejected'],2)
        self.assertEqual(self.rows('sources'),0);self.assertEqual(self.rows('revisions'),0)
    def test_changed_bytes_fail_before_commit_and_continue(self):
        p=self.write('a.pdf');self.write('b.pdf')
        def mutate(_):
            p.write_bytes(b'changed');return fixture()
        self.parse.side_effect=mutate
        result=import_validated(self.store,self.root)
        self.assertEqual(result['rejected'],1);self.assertEqual(result['imported'],1)
        self.assertEqual(self.rows('sources'),1)
    def test_publication_transaction_rolls_back_on_database_failure(self):
        self.write('a.pdf');self.store.initialize()
        with self.store.connection() as db:db.execute("CREATE TRIGGER reject_source BEFORE INSERT ON sources BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):import_validated(self.store,self.root)
        self.assertEqual(self.rows('revisions'),0);self.assertEqual(self.rows('sources'),0)
    def test_file_selection_cannot_escape_root(self):
        with self.assertRaises(ValueError):import_validated(self.store,self.root,files=['../outside.pdf'])


class FlextraImportTests(unittest.TestCase):
    def test_reviewed_flextra_import_and_assumptions(self):
        from backend.catalog.extract import read_pages
        from backend.catalog.parser import parse_known
        from backend.catalog.pricing import validate
        from backend.catalog.validated import reviewed_estimate
        from backend.catalog.records import records
        from backend.catalog.rough import estimate
        from hashlib import sha256
        source=Path(__file__).resolve().parents[1]/'data/Reliant/EFL - Reliant Energy Retail Services-10.pdf'
        content=source.read_bytes();pages,_=read_pages(content);plan=parse_known(pages)
        fixed=[c for c in plan.components if c.kind=='delivery_fixed']
        self.assertEqual(len(fixed),1);self.assertEqual(str(fixed[0].amount),'4.06')
        issues,_=validate(plan,pages);digest=sha256(content).hexdigest()
        self.assertFalse(any('Exactly one' in i for i in issues))
        checked=reviewed_estimate(plan,digest,issues)
        self.assertTrue(all(c['passed'] for c in checked[0]))
        self.assertIsNone(reviewed_estimate(plan,'changed',issues))
        self.assertIsNone(reviewed_estimate(plan,digest,issues+['Missing provider']))
        missing=plan.model_copy(deep=True);missing.components=[c for c in missing.components if c.kind!='delivery_fixed']
        self.assertIsNone(reviewed_estimate(missing,digest,validate(missing,pages)[0]))
        bad=plan.model_copy(deep=True);bad.examples[0].cents_per_kwh=1
        self.assertIsNone(reviewed_estimate(bad,digest,validate(bad,pages)[0]))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'data';root.mkdir();(root/'flextra.pdf').write_bytes(content)
            store=CatalogStore(Path(tmp)/'catalog.sqlite3')
            strict=import_validated(store,root)
            self.assertEqual(strict['rejected'],1);self.assertEqual(store.all_plans(),[])
            result=import_validated(store,root,allow_reviewed_estimates=True)
            self.assertEqual(result['imported'],1);self.assertEqual(result['estimated'],1)
            record=records(store)[0]
            self.assertFalse(record['calculation_eligible'])
            self.assertEqual(record['rough_estimate']['method'],'rough-v1:free_usage')
            self.assertEqual(record['rough_estimate']['review_status'],'reviewed_snapshot')
            baseline=estimate(record,[1000]*12)
            self.assertEqual(baseline['monthly_costs'][0]['total'],'191.53')
            edited=estimate(record,[1000]*12,{'free_usage_percent':'40'})
            self.assertNotEqual(edited['annual_cost'],baseline['annual_cost'])
            again=import_validated(store,root,allow_reviewed_estimates=True)
            self.assertEqual(again['reused'],1)


class ShortTermImportTests(unittest.TestCase):
    def test_nine_month_tariff_and_post_term_scenario(self):
        from backend.catalog.records import records
        from backend.catalog.compare import compare_catalog
        from backend.models import ComparisonRequest
        from decimal import Decimal
        source=Path(__file__).resolve().parents[1]/'data/Reliant/EFL - Reliant Energy Retail Services-3.pdf'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'data';root.mkdir();(root/'nine.pdf').write_bytes(source.read_bytes())
            store=CatalogStore(Path(tmp)/'catalog.sqlite3')
            result=import_validated(store,root)
            self.assertEqual(result['imported'],1);self.assertEqual(result['estimated'],0)
            record=records(store)[0]
            self.assertEqual(record['term_months'],9)
            self.assertTrue(record['calculation_eligible'])
            self.assertTrue(all(c['passed'] for c in record['price_checks']))
            request=ComparisonRequest(zip_code='75201',data_source='catalog',monthly_kwh=[1000]*12,
                recommendation_options={'renewal_escalation_pct':20})
            result=compare_catalog(request,store)
            plan=result.recommendations[0]; months=plan.horizon_monthly_costs
            self.assertTrue(all(m['basis']=='document_terms' for m in months[:9]))
            self.assertTrue(all(m['basis']=='modeled_renewal' for m in months[9:]))
            self.assertEqual(months[9]['rate_multiplier'],Decimal('1.2'))
            self.assertEqual(plan.annual_cost,plan.horizon_cost)
            self.assertEqual(plan.annual_cost,sum(m.total for m in plan.monthly_costs))
            self.assertEqual(result.recommendation_result.best_overall.horizon_cost,plan.horizon_cost)


class OvernightImportTests(unittest.TestCase):
    def test_overnight_review_and_source_gate(self):
        from backend.catalog.extract import read_pages
        from backend.catalog.parser import parse_known
        from backend.catalog.pricing import validate
        from backend.catalog.validated import reviewed_estimate
        from backend.catalog.records import records
        from backend.catalog.rough import estimate
        from hashlib import sha256
        source=Path(__file__).resolve().parents[1]/'data/Reliant/EFL - Reliant Energy Retail Services-9.pdf'
        content=source.read_bytes();pages,_=read_pages(content);plan=parse_known(pages)
        rates={c.kind:str(c.amount) for c in plan.components}
        self.assertEqual(rates['delivery_energy'],'6.0295');self.assertEqual(rates['delivery_fixed'],'4.06')
        issues,_=validate(plan,pages);digest=sha256(content).hexdigest()
        self.assertFalse(any('Exactly one' in i for i in issues))
        self.assertIsNotNone(reviewed_estimate(plan,digest,issues))
        self.assertIsNone(reviewed_estimate(plan,'changed',issues))
        plan.components=[c for c in plan.components if c.kind!='delivery_energy']
        self.assertIsNone(reviewed_estimate(plan,digest,validate(plan,pages)[0]))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'data';root.mkdir();(root/'night.pdf').write_bytes(content)
            store=CatalogStore(Path(tmp)/'catalog.sqlite3')
            self.assertEqual(import_validated(store,root)['rejected'],1)
            result=import_validated(store,root,allow_reviewed_estimates=True)
            self.assertEqual(result['estimated'],1);self.assertEqual(result['imported'],1)
            record=records(store)[0];self.assertFalse(record['calculation_eligible'])
            self.assertTrue(all(c['passed'] for c in record['price_checks']))
            self.assertEqual(record['rough_estimate']['review_status'],'reviewed_snapshot')
            base=estimate(record,[1000]*12)
            self.assertEqual(base['monthly_costs'][0]['total'],'171.53')
            edited=estimate(record,[1000]*12,{'free_usage_percent':'40'})
            self.assertEqual(edited['monthly_costs'][0]['total'],'151.83')
            self.assertTrue(any('9 p.m.' in n for n in base['notes']))


class VariableImportTests(unittest.TestCase):
    def test_month_to_month_source_and_variable_scenario(self):
        from backend.catalog.extract import read_pages
        from backend.catalog.parser import parse_known
        from backend.catalog.pricing import validate
        from backend.catalog.validated import reviewed_estimate
        from backend.catalog.records import records
        from backend.catalog.rough import estimate
        from hashlib import sha256
        from decimal import Decimal
        source=Path(__file__).resolve().parents[1]/'data/Reliant/EFL - Reliant Energy Retail Services-8.pdf'
        content=source.read_bytes();pages,_=read_pages(content);plan=parse_known(pages)
        self.assertEqual(plan.contract_term.value,'Month to Month')
        issues,_=validate(plan,pages);self.assertNotIn('Missing contract_term',issues)
        self.assertIsNotNone(reviewed_estimate(plan,sha256(content).hexdigest(),issues))
        self.assertIsNone(reviewed_estimate(plan,'changed',issues))
        missing=plan.model_copy(deep=True);missing.contract_term=None
        self.assertIsNone(reviewed_estimate(missing,sha256(content).hexdigest(),validate(missing,pages)[0]))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'data';root.mkdir();(root/'variable.pdf').write_bytes(content)
            store=CatalogStore(Path(tmp)/'catalog.sqlite3')
            self.assertEqual(import_validated(store,root)['rejected'],1)
            result=import_validated(store,root,allow_reviewed_estimates=True)
            self.assertEqual(result['imported'],1);self.assertEqual(result['estimated'],1)
            record=records(store)[0]
            self.assertEqual(record['contract_term'],'Month to Month');self.assertIsNone(record['term_months'])
            self.assertFalse(record['calculation_eligible'])
            self.assertTrue(all(c['passed'] for c in record['price_checks']))
            base=estimate(record,[1000]*12)
            self.assertEqual(base['monthly_costs'][0]['total'],'187.53')
            edited=estimate(record,[1000]*12,{'price_change_percent':'20'})
            self.assertEqual(edited['monthly_costs'][0],base['monthly_costs'][0])
            self.assertTrue(all(c['total']=='225.03' for c in edited['monthly_costs'][1:]))
            boundary=estimate(record,[799,800]+[1000]*10)
            self.assertEqual(boundary['monthly_costs'][0]['total'],'160.60')
            self.assertEqual(boundary['monthly_costs'][1]['total'],'150.84')


class PdfBenchmarkTests(unittest.TestCase):
    def test_independent_txu_document_benchmark(self):
        from backend.catalog.records import records
        from backend.catalog.rough import estimate
        f='_txu/0160b2be9238adb9647f00d1028d84dc61a694b3c7a94328a5ca259b27e1ebb2.pdf'
        source=Path(__file__).resolve().parent/'fixtures/txu-free-pass-24.pdf'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'data';(root/'_txu').mkdir(parents=True);(root/f).write_bytes(source.read_bytes())
            store=CatalogStore(Path(tmp)/'catalog.sqlite3')
            with patch('backend.catalog.tdu.fetch_html',side_effect=AssertionError('No network')):
                self.assertEqual(import_validated(store,root)['rejected'],1)
                result=import_validated(store,root,allow_reviewed_estimates=True)
            self.assertEqual(result['imported'],1)
            p=records(store)[0];self.assertEqual(p['source_type'],'pdf');self.assertFalse(p['calculation_eligible'])
            self.assertEqual(p['rough_estimate']['review_status'],'reviewed_snapshot')
            self.assertTrue(all(c['basis']=='published_benchmark' for c in p['price_checks']))
            self.assertEqual(estimate(p,[1000]*12)['monthly_costs'][0]['total'],'171.00')
            self.assertFalse(any(c['kind'].startswith('delivery') for c in p['components']))
            (root/f).write_bytes(source.read_bytes()+b'\n')
            self.assertEqual(import_validated(store,root,allow_reviewed_estimates=True)['rejected'],1)
