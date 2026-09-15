import copy
import unittest
from decimal import Decimal as D
from pathlib import Path
from backend.catalog.extract import read_pages
from backend.catalog.parser import parse_known
from backend.catalog.pricing import validate,calculate
from backend.catalog.tdu import Resolver,DISCOUNT_URL,parse_rates,candidate_url
from backend.projections import project
from backend.recommendations import Candidate

ROOT=Path(__file__).resolve().parents[1]

class PdfRecoveryTests(unittest.TestCase):
    def test_real_short_fixed_pdfs_validate_and_renew_at_term_boundary(self):
        for path,term in [('choosetexaspower/EFL-8.pdf',11),('centerpoint/eflviewer2.pdf',11),
                          ('Reliant/EFL - Reliant Energy Retail Services-3.pdf',9)]:
            with self.subTest(path=path):
                pages,_=read_pages((ROOT/'data'/path).read_bytes());plan=parse_known(pages)
                self.assertEqual(validate(plan,pages)[0],[])
                candidate=Candidate('p','short',term,lambda u,m:calculate(plan,u,m),[],[])
                months,details=project(candidate,[D(1000)]*12,24,D(10),'drop')
                self.assertEqual(details[term-1]['basis'],'document_terms')
                self.assertEqual(details[term]['basis'],'modeled_renewal')
                self.assertEqual(details[term]['rate_multiplier'],D('1.1'))
                self.assertEqual(months[term].credit,0)
                self.assertEqual(months[term].energy,(months[term-1].energy*D('1.1')).quantize(D('.01')))
                altered=plan.model_copy(deep=True);altered.components=[c for c in altered.components if c.kind!='delivery_fixed']
                self.assertTrue(validate(altered,pages)[0])

    def test_discount_totals_units_alias_and_date_safeguards(self):
        html=(ROOT/'tests/fixtures/discount-delivery-totals.html').read_text(encoding='utf-8')
        source=parse_rates(html,'Oncor',DISCOUNT_URL)
        self.assertEqual(source.monthly_usd,D('4.06'))
        self.assertEqual(source.cents_per_kwh,D('6.0295'))
        self.assertEqual(source.published_on,'2026-09-13')
        pages,_=read_pages((ROOT/'data/choosetexaspower/EFL-1.pdf').read_bytes());plan=parse_known(pages)
        self.assertEqual(candidate_url(plan,pages),DISCOUNT_URL)
        self.assertEqual(Resolver(lambda _:html).enrich(plan,pages).tdu_lookup.status,'date_mismatch')
        # Synthetic older table verifies the success path without asserting a real historical source.
        old=html.replace('9/13/2026','9/1/2026')
        enriched=Resolver(lambda _:old).enrich(plan,pages)
        self.assertEqual(enriched.tdu_lookup.status,'resolved')
        self.assertEqual(validate(enriched,pages)[0],[])
        self.assertEqual(parse_rates(html,'CenterPoint',DISCOUNT_URL).monthly_usd,D('4.90'))
        for bad in (html+html,html.replace('$0.060295','6.0295 cents'),html.replace('Total Per Month Charges:','Unknown')):
            with self.assertRaises(ValueError):parse_rates(bad,'Oncor',DISCOUNT_URL)
