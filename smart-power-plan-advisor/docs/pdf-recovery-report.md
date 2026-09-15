# PDF recovery report - 2026-09-15

Scope: all 25 PDFs in data/. These are file counts, not unique plan counts. PDF and API records remain independent.

**18 validated for ranking; 3 reviewed estimates; 4 blocked from ranking; 0 missing catalog source entries.**

Published 19 selected PDFs (16 validated, 3 reviewed estimates). Preserved the two previously validated 4Change PDF records. Four diagnostic records remain excluded; their original saved issue text may differ from the latest review below.

SQLite backup: `.data\backups\plans-before-pdf-recovery-20260915T183808Z.sqlite3`. PDF bytes, API tables and existing comparison payloads were verified unchanged.

A fresh 78681 comparison includes Reliant Get More, Save More 36 at a 36-month maximum and excludes it at 24 months. Short fixed contracts use modeled renewal after their actual term. Existing conversations retain frozen records: compare again and start a new chat.

| PDF relative to data/ | Plan | Status | Notes |
| --- | --- | --- | --- |
| 4change/4Change Energy max saver value 12.pdf | 4Change Energy Maxx Saver Value 12SM | Validated for ranking | Preserved validated September 1 delivery snapshot; current web table was not substituted. |
| centerpoint/eflviewer1.pdf | Gexa Eco Saver Plus 12 | Validated for ranking | - |
| centerpoint/eflviewer2.pdf | SimpleSaver 11 | Validated for ranking | - |
| centerpoint/eflviewer3.pdf | SimpleSaver 12 | Validated for ranking | - |
| choosetexaspower/EFL-1.pdf | Bill Credit Bundle 12 | Blocked from ranking | Dated delivery evidence needed: PDF 2026-09-01; current official Discount Power table 2026-09-13 is newer. |
| choosetexaspower/EFL-10.pdf | 4Change Energy Maxx Saver Value 12SM | Validated for ranking | Preserved validated September 1 delivery snapshot; current web table was not substituted. |
| choosetexaspower/EFL-11.pdf | Gexa Eco Saver Plus 12 | Validated for ranking | - |
| choosetexaspower/EFL-2.pdf | Bill Credit Bundle 24 | Blocked from ranking | Dated delivery evidence needed: PDF 2026-09-01; current official Discount Power table 2026-09-13 is newer. |
| choosetexaspower/EFL-3.pdf | SimpleSaver 24 | Validated for ranking | - |
| choosetexaspower/EFL-4.pdf | Frontier Saver Plus 12 | Validated for ranking | - |
| choosetexaspower/EFL-5.pdf | Real 1000 Deal 12SM | Blocked from ranking | No separate delivery breakdown. The stated price reconciles as a bundled illustration, but zero separate delivery charges cannot be asserted from this document. |
| choosetexaspower/EFL-6.pdf | Gexa Saver Plus 12 | Validated for ranking | - |
| choosetexaspower/EFL-7.pdf | SimpleSaver 12 | Validated for ranking | - |
| choosetexaspower/EFL-8.pdf | SimpleSaver 11 | Validated for ranking | - |
| choosetexaspower/EFL-9.pdf | TXU Energy Smart 1000 Saver 12SM | Blocked from ranking | Requires dated delivery evidence and seasonal credit support ($100 at >=1000 kWh; extra $25 for cycles ending July-September). Current linked official delivery PDF is dated 2026-09-13, later than EFL 2026-09-11. |
| Reliant/EFL - Reliant Energy Retail Services-1.pdf | Reliant Power Savings 24 plan | Validated for ranking | - |
| Reliant/EFL - Reliant Energy Retail Services-10.pdf | Reliant Flextra Credits 24 plan | Reviewed estimate only | Reviewed source assumptions pass benchmark checks; interval usage or future variable rates remain unknown. Excluded from ranking. |
| Reliant/EFL - Reliant Energy Retail Services-2.pdf | Reliant Power Savings 24 plan | Validated for ranking | - |
| Reliant/EFL - Reliant Energy Retail Services-3.pdf | Reliant Power Savings 9 plan | Validated for ranking | - |
| Reliant/EFL - Reliant Energy Retail Services-4.pdf | Reliant Get More, Save More 36 plan | Validated for ranking | - |
| Reliant/EFL - Reliant Energy Retail Services-5.pdf | Reliant Get More, Save More 12 plan | Validated for ranking | - |
| Reliant/EFL - Reliant Energy Retail Services-6.pdf | Reliant Secure Advantage® 12 plan | Validated for ranking | - |
| Reliant/EFL - Reliant Energy Retail Services-7.pdf | Reliant Cowboys plan | Validated for ranking | - |
| Reliant/EFL - Reliant Energy Retail Services-8.pdf | Reliant ClearSM Flex plan | Reviewed estimate only | Reviewed source assumptions pass benchmark checks; interval usage or future variable rates remain unknown. Excluded from ranking. |
| Reliant/EFL - Reliant Energy Retail Services-9.pdf | Reliant Free Overnight 12 plan | Reviewed estimate only | Reviewed source assumptions pass benchmark checks; interval usage or future variable rates remain unknown. Excluded from ranking. |

## Remaining evidence and implementation requirements

- Bill Credit Bundle 12/24: an official delivery table effective on or before the September 1 EFL date, with matching utility and reconciled examples. Current inspected provider source: https://www.discountpowertx.com/en/customer-care/billing/tdsp-delivery-charges .
- Real 1000 Deal: provider clarification or a document explicitly separating or confirming bundled recurring charges. Do not reverse-engineer delivery rates from average prices.
- TXU Smart 1000 Saver: dated delivery evidence plus a seasonal-credit component model, calendar applicability and benchmark validation. Inspected current delivery-page link points to September 13 evidence: https://www.txu.com/en/help/billing-payments/tdu-charges .
- Free-time plans remain reviewed estimates unless interval consumption is supplied; variable-rate forecasts cannot establish unknown future prices.

## Verification

Final full Python run: 230 tests, 228 passed, 2 Windows symlink-permission skips, zero failures/errors. All 57 frontend tests passed. Live catalog 24/36-month eligibility and short-term renewal checks passed. No new paid LLM evaluation was needed for these deterministic changes.
