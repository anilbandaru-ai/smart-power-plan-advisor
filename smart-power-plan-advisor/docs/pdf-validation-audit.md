# PDF validation audit - 2026-09-15

25 on-disk PDFs; saved catalog validation and read-only current parser checks. API offers excluded; no ingestion or catalog updates performed. Fresh parser checks do not run delivery-table enrichment. No blocking issues does not verify availability or promise accurate custom-estimate bills.

Files: 25. No blocking issues: 12; Not imported: 2; Issues: 11.

Two saved tiered-pricing exclusions now pass the current parser. Reimport/revalidate before starting a fresh comparison; existing chats retain frozen records.

| PDF (relative to data/) | Plan | Saved catalog status | Issue categories | Notes |
| --- | --- | --- | --- | --- |
| 4change/4Change Energy max saver value 12.pdf | 4Change Energy Maxx Saver Value 12SM | No blocking issues | None | Duplicate page 2 skipped |
| centerpoint/eflviewer1.pdf | Gexa Eco Saver Plus 12 | Not imported | Not imported | Not imported; current parser: passes validation |
| centerpoint/eflviewer2.pdf | SimpleSaver 11 | Not imported | Not imported | Not imported; current parser: Contract does not cover the 12-month comparison horizon |
| centerpoint/eflviewer3.pdf | SimpleSaver 12 | No blocking issues | None | - |
| choosetexaspower/EFL-1.pdf | Bill Credit Bundle 12 | Issues | Delivery/TDU extraction | - |
| choosetexaspower/EFL-10.pdf | 4Change Energy Maxx Saver Value 12SM | No blocking issues | None | Duplicate page 2 skipped |
| choosetexaspower/EFL-11.pdf | Gexa Eco Saver Plus 12 | No blocking issues | None | - |
| choosetexaspower/EFL-2.pdf | Bill Credit Bundle 24 | Issues | Delivery/TDU extraction | - |
| choosetexaspower/EFL-3.pdf | SimpleSaver 24 | No blocking issues | None | - |
| choosetexaspower/EFL-4.pdf | Frontier Saver Plus 12 | No blocking issues | None | - |
| choosetexaspower/EFL-5.pdf | Real 1000 Deal 12SM | Issues | Delivery/TDU extraction | Blank page 2 skipped |
| choosetexaspower/EFL-6.pdf | Gexa Saver Plus 12 | No blocking issues | None | - |
| choosetexaspower/EFL-7.pdf | SimpleSaver 12 | No blocking issues | None | - |
| choosetexaspower/EFL-8.pdf | SimpleSaver 11 | Issues | Contract shorter than 12 months | - |
| choosetexaspower/EFL-9.pdf | TXU Energy Smart 1000 Saver 12SM | Issues | Delivery/TDU extraction, Seasonal credits | Blank page 2 skipped |
| Reliant/EFL - Reliant Energy Retail Services-1.pdf | Reliant Power Savings 24 plan | No blocking issues | None | - |
| Reliant/EFL - Reliant Energy Retail Services-10.pdf | Reliant Flextra Credits 24 plan | Issues | Delivery/TDU extraction, Time-of-use/free periods | - |
| Reliant/EFL - Reliant Energy Retail Services-2.pdf | Reliant Power Savings 24 plan | No blocking issues | None | - |
| Reliant/EFL - Reliant Energy Retail Services-3.pdf | Reliant Power Savings 9 plan | Issues | Contract shorter than 12 months | - |
| Reliant/EFL - Reliant Energy Retail Services-4.pdf | Reliant Get More, Save More 36 plan | Issues | Tiered energy | Saved issues are outdated: current parser passes; reimport/revalidation needed |
| Reliant/EFL - Reliant Energy Retail Services-5.pdf | Reliant Get More, Save More 12 plan | Issues | Tiered energy | Saved issues are outdated: current parser passes; reimport/revalidation needed |
| Reliant/EFL - Reliant Energy Retail Services-6.pdf | Reliant Secure Advantage® 12 plan | No blocking issues | None | - |
| Reliant/EFL - Reliant Energy Retail Services-7.pdf | Reliant Cowboys plan | No blocking issues | None | - |
| Reliant/EFL - Reliant Energy Retail Services-8.pdf | Reliant ClearSM Flex plan | Issues | Variable-rate product | - |
| Reliant/EFL - Reliant Energy Retail Services-9.pdf | Reliant Free Overnight 12 plan | Issues | Delivery/TDU extraction, Time-of-use/free periods | - |

## Exact saved validation messages

### choosetexaspower/EFL-1.pdf

- Provider TDU link found; this page needs an approved rate-table parser.
- Exactly one stated delivery_energy charge required
- Exactly one stated delivery_fixed charge required

### choosetexaspower/EFL-2.pdf

- Provider TDU link found; this page needs an approved rate-table parser.
- Exactly one stated delivery_energy charge required
- Exactly one stated delivery_fixed charge required

### choosetexaspower/EFL-5.pdf

- Delivery charges are missing and no supported provider TDU link was found.
- Exactly one stated delivery_energy charge required
- Exactly one stated delivery_fixed charge required

### choosetexaspower/EFL-8.pdf

- Contract does not cover the 12-month comparison horizon

### choosetexaspower/EFL-9.pdf

- Seasonal credit pricing is not supported
- Provider TDU link found; this page needs an approved rate-table parser.
- Unsupported pricing rule: summer bill credit
- Exactly one stated delivery_energy charge required
- Exactly one stated delivery_fixed charge required

### Reliant/EFL - Reliant Energy Retail Services-10.pdf

- Interval usage is required for free-time pricing
- Delivery charges are missing and no supported provider TDU link was found.
- Unsupported pricing rule: free days
- Unsupported pricing rule: free flex
- Exactly one stated delivery_fixed charge required

### Reliant/EFL - Reliant Energy Retail Services-3.pdf

- Contract does not cover the 12-month comparison horizon

### Reliant/EFL - Reliant Energy Retail Services-4.pdf

- Tiered energy rates require a tiered calculator
- Unsupported pricing rule: energy charge: (>
- Exactly one stated energy charge required

### Reliant/EFL - Reliant Energy Retail Services-5.pdf

- Tiered energy rates require a tiered calculator
- Unsupported pricing rule: energy charge: (>
- Exactly one stated energy charge required

### Reliant/EFL - Reliant Energy Retail Services-8.pdf

- Variable-rate pricing is not supported
- Missing contract_term
- Only fixed-rate products supported
- Contract does not cover the 12-month comparison horizon

### Reliant/EFL - Reliant Energy Retail Services-9.pdf

- Interval usage is required for free-time pricing
- Delivery charges are missing and no supported provider TDU link was found.
- Unsupported pricing rule: free overnight
- Exactly one stated delivery_energy charge required
- Exactly one stated delivery_fixed charge required

