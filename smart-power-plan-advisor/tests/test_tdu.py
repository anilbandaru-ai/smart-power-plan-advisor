import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from backend.catalog.extract import read_pages, Extractor
from backend.catalog.parser import parse_known
from backend.catalog.pricing import validate, calculate
from backend.catalog.store import CatalogStore
from backend.catalog.sync import sync
from backend.catalog.tdu import Resolver, FOUR_CHANGE_URL, fetch_html, parse_rates, candidate_url
from backend.knowledge.config import Settings

HTML = '''<html><table><tr><th>Updated September 1, 2026 - Residential</th></tr>
<tr><td></td><td>Oncor</td><td>CenterPoint</td></tr>
<tr><td>Monthly Charge Per Billing Cycle</td><td>$4.06</td><td>$4.90</td></tr>
<tr><td>Usage-based Charge Per kWh</td><td>6.02950¢</td><td>6.41300¢</td></tr>
</table></html>'''
PDF = Path(__file__).resolve().parents[1] / 'data' / '4change' / '4Change Energy max saver value 12.pdf'


class TduTests(unittest.TestCase):
    def setUp(self):
        self.pages,_=read_pages(PDF.read_bytes())
        self.plan=parse_known(self.pages)

    def test_area_units_provenance_and_example_reconciliation(self):
        resolved=Resolver(lambda _:HTML).enrich(self.plan,self.pages)
        self.assertEqual(resolved.tdu_lookup.status,'resolved')
        source=resolved.tdu_lookup.source
        self.assertEqual(source.monthly_usd,Decimal('4.06'))
        self.assertEqual(source.cents_per_kwh,Decimal('6.02950'))
        self.assertEqual(source.published_on,'2026-09-01')
        self.assertTrue(source.sha256)
        issues,checks=validate(resolved,self.pages)
        self.assertEqual(issues,[])
        self.assertTrue(all(c['passed'] for c in checks))
        self.assertEqual(calculate(resolved,Decimal('1000'),1).delivery,Decimal('64.36'))
        self.assertEqual(calculate(resolved,Decimal('1000'),1).total,Decimal('67.01'))
        for component in resolved.components:
            if component.kind.startswith('delivery'):
                self.assertIsNone(component.evidence.page)
                self.assertEqual(component.evidence.url,FOUR_CHANGE_URL)
        self.assertEqual(parse_rates(HTML,'CenterPoint').monthly_usd,Decimal('4.90'))

    def test_missing_rates_suppress_secondary_example_mismatches(self):
        issues,checks=validate(self.plan,self.pages)
        self.assertTrue(any('delivery_energy' in issue for issue in issues))
        self.assertFalse(any('mismatch' in issue for issue in issues))
        self.assertTrue(all(c['status']=='not_checked' for c in checks))

    def test_ambiguous_missing_dates_and_conflicting_rates_are_blocked(self):
        for html in [HTML+HTML,HTML.replace('Oncor','Unknown'),HTML.replace('Updated September 1, 2026 - Residential','Current prices'),HTML.replace('6.02950¢','$0.060295')]:
            self.assertNotEqual(Resolver(lambda _:html).enrich(self.plan,self.pages).tdu_lookup.status,'resolved')
        earlier=self.plan.model_copy(deep=True);earlier.issue_date.value='2026-08-15'
        self.assertEqual(Resolver(lambda _:HTML).enrich(earlier,self.pages).tdu_lookup.status,'date_mismatch')
        partial=Resolver(lambda _:HTML).enrich(self.plan,self.pages)
        partial.components=[c for c in partial.components if c.kind!='delivery_energy']
        fixed=next(c for c in partial.components if c.kind=='delivery_fixed')
        fixed.evidence.url=None;fixed.evidence.page=1;fixed.amount=Decimal('99')
        self.assertEqual(Resolver(lambda _:HTML).enrich(partial,self.pages).tdu_lookup.status,'rate_conflict')

    def test_unapproved_links_and_existing_complete_pdf_rates_do_not_fetch(self):
        with patch('httpx.Client',side_effect=AssertionError('Must not fetch')):
            for url in ['http://127.0.0.1/tdu-charges','https://www.4changeenergy.com/tdu-charges?x=1','https://evil.example/tdu-charges']:
                with self.assertRaises(ValueError):fetch_html(url)
        plan=self.plan.model_copy(deep=True);plan.provider.value='U.S. Retailers LLC dba Discount Power'
        pages=[{'page':1,'text':'TDU information: www.discountpowertx.com/TDSPcharges'}]
        resolver=Resolver(lambda _:self.fail('Unapproved provider must not fetch'))
        result=resolver.enrich(plan,pages)
        self.assertEqual(result.tdu_lookup.status,'unsupported_source')
        self.assertEqual(result.tdu_lookup.candidate_url,'https://www.discountpowertx.com/TDSPcharges')
        gexa_pages,_=read_pages((PDF.parents[1]/'choosetexaspower'/'EFL-6.pdf').read_bytes())
        gexa=parse_known(gexa_pages)
        self.assertIsNone(resolver.enrich(gexa,gexa_pages).tdu_lookup)

    def test_failure_is_cached_and_external_source_cannot_be_forged(self):
        calls=[]
        def fail(url):calls.append(url);raise RuntimeError('secret provider error')
        resolver=Resolver(fail)
        for _ in range(2):
            plan=resolver.enrich(self.plan,self.pages)
            self.assertEqual(plan.tdu_lookup.status,'unavailable')
            self.assertNotIn('secret',plan.model_dump_json())
        self.assertEqual(len(calls),1)
        resolved=Resolver(lambda _:HTML).enrich(self.plan,self.pages)
        resolved.tdu_lookup.source.sha256='wrong'
        self.assertTrue(any('external TDU provenance' in issue for issue in validate(resolved,self.pages)[0]))

    def test_refresh_replaces_previous_rates_and_unchanged_sync_skips_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'data';root.mkdir();(root/'plan.pdf').write_bytes(PDF.read_bytes())
            store=CatalogStore(Path(tmp)/'catalog.sqlite3');extractor=Extractor(Settings())
            sync(store,root,extractor,resolver=Resolver(lambda _:HTML))
            original=store.all_plans()[0]
            self.assertTrue(original['calculation_eligible'])
            result=sync(store,root,extractor,resolver=Resolver(lambda _:self.fail('Unchanged file should be reused')))
            self.assertEqual(result['reused'],1)
            sync(store,root,extractor,refresh_tdu=True,resolver=Resolver(lambda _:HTML))
            self.assertEqual(store.all_plans()[0]['id'],original['id'])
            sync(store,root,extractor,refresh_tdu=True,resolver=Resolver(lambda _: 'unparseable'))
            failed=store.all_plans()[0]
            self.assertFalse(failed['calculation_eligible'])
            self.assertFalse(any(c['evidence']['url'] for c in failed['plan']['components']))
            with store.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM revisions').fetchone()[0],3)

    def test_fetch_limits_redirects_and_content_type(self):
        import httpx
        for response in [httpx.Response(302,headers={'location':'http://127.0.0.1/'}),
                         httpx.Response(200,headers={'content-type':'application/json'},text='{}'),
                         httpx.Response(200,headers={'content-type':'text/html'},text='x'*(1024*1024+1))]:
            client=httpx.Client(transport=httpx.MockTransport(lambda _:response))
            with patch('httpx.Client',return_value=client):
                with self.assertRaises((ValueError,httpx.HTTPError)):fetch_html(FOUR_CHANGE_URL)
