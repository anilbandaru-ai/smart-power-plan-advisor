# Monthly calculation audit (historical component pricing)

Verified the nine currently calculable PDF plans using independent tariff amounts transcribed from the catalog source excerpts. No application behavior changed.

- Checked 12-, 24-, and 36-month horizons at 5% hypothetical annual renewal escalation, with both retain and drop renewal-credit policies.
- Checked 1,296 monthly rows and 11,664 rendered cells in headless Edge: month, usage, energy, EFL reference, base/usage fee, delivery, credit, total, and original/renewal basis.
- Usage samples: 0, 500, 500.1, 799.9999, 800, 999, 999.0001, 999.9999, 1000, 1000.0001, 2000, 2000.0001 kWh. These exercise strict versus inclusive credit thresholds and the 800-kWh usage-fee boundary.
- Independently checked energy and delivery rates, conditional charges, cent rounding, renewal-only escalation, retained/dropped credits, annual and horizon sums, and agreement between comparison and recommendation costs.
- All 24 UI tests passed. Python suite: 77 of 78 passed; the catalog path-escape test failed while creating a symlink fixture because Windows denied that privilege (WinError 1314), before its assertions.

No calculation discrepancies were found in this coverage. The EFL average-price column uses the requested display mapping, not a calculated effective rate. Base fee includes applicable usage charges. Renewal values are hypothetical projections. Eleven other unique PDF plans remain excluded from calculation, so this audit does not validate bills for unsupported plans. This audit uses local source-backed catalog rates and does not independently verify live delivery tariffs or actual utility invoices.

This audit predates efl-average-v3. New PDF comparisons now use mapped inclusive EFL prices; see the specification section 24 for verification of that model.

## Historical inclusive mapped-average verification

For efl-average-v3, four dedicated tests check 1800 kWh at 6.8 cents = $122.40, no added delivery/base charges or credit subtraction, range boundaries, per-plan examples, missing/duplicate examples, renewal rounding, consistent ranking/savings and metadata serialization. All passed. Headless Edge checked 1,296 monthly rows across nine local PDF plans at 12/24/36 months with retain/drop settings: stored results, displayed rate and inclusive total, Included labels, renewal basis, recommendation agreement and mobile overflow. All 25 UI tests passed. Full Python suite: 81 of 82 passed; the existing Windows symlink fixture remains blocked. Earlier component audit results above are historical and do not describe new PDF totals.

## Current custom formula verification

custom-efl-v4 uses the mapped reference rate for Energy, adds PDF base/usage fees and fixed/per-kWh delivery, then subtracts eligible credits. This repeats effects already embedded in the EFL average and is explicitly labeled Custom estimate, not an actual tariff bill. Verified the 1800-kWh example (122.40 + 112.59 - 125 = 109.99), boundaries and renewal credit policies. Five pricing tests and 26 UI tests passed. Full Python suite: 82/83 passed; the existing Windows symlink fixture is blocked. Headless Edge checked 1296 monthly rows and 11664 cells across all nine calculable plans, 12/24/36 horizons and both credit policies, including recommendation agreement. Saved older formats retain their original arithmetic.
