# EFL average-price audit

All 22 local PDFs checked against their active catalog records. Prices below are published examples in cents/kWh, not tariff bands. The revised UI mapping uses the 500 example for 0..1000, the 1000 example for >1000..2000, and the 2000 example for >2000. New PDF comparisons use custom-efl-v4: mapped averages supply Energy, with PDF fees/delivery added and credits subtracted. This is a custom formula, not an actual tariff bill. Component pricing remains for catalog validation and legacy/demo calculations.

| Document | Plan | 500 | 1000 | 2000 | Cost comparison |
|---|---|---:|---:|---:|---|
| 4change/4Change Energy max saver value 12.pdf | 4Change Energy Maxx Saver Value 12SM | 19.6 | 6.70 | 12.7 | Yes |
| choosetexaspower/EFL-1.pdf | Bill Credit Bundle 12 | 19.7 | 6.8 | 12.8 | Excluded |
| choosetexaspower/EFL-10.pdf | 4Change Energy Maxx Saver Value 12SM | 19.6 | 6.70 | 12.7 | Yes |
| choosetexaspower/EFL-11.pdf | Gexa Eco Saver Plus 12 | 19.6 | 6.7 | 12.7 | Yes |
| choosetexaspower/EFL-2.pdf | Bill Credit Bundle 24 | 19.7 | 6.8 | 12.8 | Excluded |
| choosetexaspower/EFL-3.pdf | SimpleSaver 24 | 19.7 | 6.8 | 12.8 | Yes |
| choosetexaspower/EFL-4.pdf | Frontier Saver Plus 12 | 19.6 | 6.7 | 12.7 | Yes |
| choosetexaspower/EFL-5.pdf | Real 1000 Deal 12SM | 19.7 | 6.70 | 12.7 | Excluded |
| choosetexaspower/EFL-6.pdf | Gexa Saver Plus 12 | 19.6 | 6.7 | 12.7 | Yes |
| choosetexaspower/EFL-7.pdf | SimpleSaver 12 | 19.5 | 6.6 | 12.6 | Yes |
| choosetexaspower/EFL-8.pdf | SimpleSaver 11 | 19.4 | 6.5 | 12.5 | Excluded |
| choosetexaspower/EFL-9.pdf | TXU Energy Smart 1000 Saver 12SM | 22.5 | 10.5 | 15.1 | Excluded |
| Reliant/EFL - Reliant Energy Retail Services-1.pdf | Reliant Power Savings 24 plan | 20.8 | 12.9 | 16.4 | Yes |
| Reliant/EFL - Reliant Energy Retail Services-10.pdf | Reliant Flextra Credits 24 plan | 19.6 | 19.2 | 18.9 | Excluded |
| Reliant/EFL - Reliant Energy Retail Services-2.pdf | Reliant Power Savings 24 plan | 20.8 | 12.9 | 16.4 | Yes |
| Reliant/EFL - Reliant Energy Retail Services-3.pdf | Reliant Power Savings 9 plan | 19.8 | 11.9 | 15.4 | Excluded |
| Reliant/EFL - Reliant Energy Retail Services-4.pdf | Reliant Get More, Save More 36 plan | 18.7 | 17.6 | 14.5 | Excluded |
| Reliant/EFL - Reliant Energy Retail Services-5.pdf | Reliant Get More, Save More 12 plan | 17.6 | 16.5 | 14.9 | Excluded |
| Reliant/EFL - Reliant Energy Retail Services-6.pdf | Reliant Secure Advantage® 12 plan | 17.5 | 15.2 | 14.9 | Yes |
| Reliant/EFL - Reliant Energy Retail Services-7.pdf | Reliant Cowboys plan | 19.1 | 16.8 | 16.5 | Yes |
| Reliant/EFL - Reliant Energy Retail Services-8.pdf | Reliant ClearSM Flex plan | 21.1 | 18.8 | 18.5 | Excluded |
| Reliant/EFL - Reliant Energy Retail Services-9.pdf | Reliant Free Overnight 12 plan | 17.6 | 17.2 | 16.9 | Excluded |

Verification: all 66 published PDF values matched the catalog. Before the revised mapping, headless Edge rendered all nine calculable plans and verified 108 monthly reference cells against each plan's own examples, including zero, exact and fractional boundaries, and above-maximum usage. Two duplicate document pairs account for 22 files representing 20 unique plans.

Plans excluded from calculation retain their extracted examples in the catalog. Their exclusion is independent of this reference column:

- Bill Credit Bundle 12: Provider TDU link found; this page needs an approved rate-table parser.; Exactly one stated delivery_energy charge required; Exactly one stated delivery_fixed charge required
- Bill Credit Bundle 24: Provider TDU link found; this page needs an approved rate-table parser.; Exactly one stated delivery_energy charge required; Exactly one stated delivery_fixed charge required
- Real 1000 Deal 12SM: Delivery charges are missing and no supported provider TDU link was found.; Exactly one stated delivery_energy charge required; Exactly one stated delivery_fixed charge required
- Reliant ClearSM Flex plan: Variable-rate pricing is not supported; Missing contract_term; Only fixed-rate products supported; Contract does not cover the 12-month comparison horizon
- Reliant Flextra Credits 24 plan: Interval usage is required for free-time pricing; Delivery charges are missing and no supported provider TDU link was found.; Unsupported pricing rule: free days; Unsupported pricing rule: free flex; Exactly one stated delivery_fixed charge required
- Reliant Free Overnight 12 plan: Interval usage is required for free-time pricing; Delivery charges are missing and no supported provider TDU link was found.; Unsupported pricing rule: free overnight; Exactly one stated delivery_energy charge required; Exactly one stated delivery_fixed charge required
- Reliant Get More, Save More 12 plan: Tiered energy rates require a tiered calculator; Unsupported pricing rule: energy charge: (>; Exactly one stated energy charge required
- Reliant Get More, Save More 36 plan: Tiered energy rates require a tiered calculator; Unsupported pricing rule: energy charge: (>; Exactly one stated energy charge required
- Reliant Power Savings 9 plan: Contract does not cover the 12-month comparison horizon
- SimpleSaver 11: Contract does not cover the 12-month comparison horizon
- TXU Energy Smart 1000 Saver 12SM: Seasonal credit pricing is not supported; Provider TDU link found; this page needs an approved rate-table parser.; Unsupported pricing rule: summer bill credit; Exactly one stated delivery_energy charge required; Exactly one stated delivery_fixed charge required

Revised mapping verification: all 15 comparison UI tests passed. Rechecked all 22 PDFs and 66 prices, and verified 108 browser-rendered cells across nine calculable plans with the revised bands, including exact and fractional boundaries.
