import unittest
from pathlib import Path
from decimal import Decimal
from backend.catalog.extract import read_pages
from backend.catalog.parser import parse_known
from backend.catalog.pricing import calculate, validate, energy_structure
from backend.catalog.records import Tariff


class EnergyTierTests(unittest.TestCase):
    def plan(self, number):
        p=Path(__file__).resolve().parents[1]/f'data/Reliant/EFL - Reliant Energy Retail Services-{number}.pdf'
        pages,_=read_pages(p.read_bytes())
        return parse_known(pages),pages

    def test_both_tier_sources_validate_and_shared_tariff_matches(self):
        for number in (4,5):
            plan,pages=self.plan(number)
            issues,checks=validate(plan,pages)
            self.assertEqual(issues,[])
            self.assertTrue(all(c['passed'] for c in checks))
            tariff=Tariff(components=[c.model_dump(exclude={'evidence'}) for c in plan.components])
            rates=[c.amount for c in plan.components if c.kind=='energy_tier']
            for usage in (0,999,1000,1001,2000):
                kwh=Decimal(usage)
                actual=calculate(plan,kwh,1)
                expected=(min(kwh,1000)*rates[0]+max(kwh-1000,0)*rates[1])/100
                self.assertEqual(actual.energy,expected.quantize(Decimal('.01')))
                self.assertEqual(actual,calculate(tariff,kwh,1))

    def test_invalid_and_mixed_tiers_reject(self):
        for change in ('gap','overlap','missing_end','mixed','zero_width'):
            plan,pages=self.plan(4)
            tiers=[c for c in plan.components if c.kind=='energy_tier']
            if change=='gap':tiers[1].minimum_kwh=Decimal(1001)
            if change=='overlap':tiers[1].minimum_kwh=Decimal(999)
            if change=='missing_end':tiers[1].maximum_kwh=Decimal(2000)
            if change=='mixed':plan.components.append(tiers[0].model_copy(update={'kind':'energy'}))
            if change=='zero_width':tiers[0].maximum_kwh=Decimal(0)
            self.assertTrue(energy_structure(plan.components),change)
            self.assertTrue(validate(plan,pages)[0],change)
            with self.assertRaises(ValueError):calculate(plan,Decimal(1000),1)

    def test_flat_rate_needs_no_tiers(self):
        plan,pages=self.plan(3)
        self.assertEqual(len([c for c in plan.components if c.kind=='energy']),1)
        self.assertEqual(energy_structure(plan.components),[])
        self.assertEqual(calculate(plan,Decimal(1000),1).total,Decimal('119.03'))
