"""Controlled provider delivery-rate lookup, separate from untrusted PDF extraction."""
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit, urlunsplit

from backend.catalog.models import Component, Evidence, TduLookup, TduSource

FOUR_CHANGE_URL = 'https://www.4changeenergy.com/tdu-charges'
APPROVED_URLS = frozenset([FOUR_CHANGE_URL])


class Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.rows, self.row, self.cell = [], None, None, None
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.depth += 1
            if self.depth == 1:self.rows = []
        elif self.depth == 1:
            if tag == 'tr':self.row = []
            elif tag in ('td', 'th'):self.cell = []
            elif tag == 'br' and self.cell is not None:self.cell.append(' ')

    def handle_data(self, data):
        if self.depth == 1 and self.cell is not None:self.cell.append(data)

    def handle_endtag(self, tag):
        if self.depth == 1:
            if tag in ('td', 'th') and self.cell is not None:
                if self.row is not None:self.row.append(' '.join(''.join(self.cell).split()))
                self.cell = None
            elif tag == 'tr' and self.row is not None:
                self.rows.append(self.row);self.row = None
            elif tag == 'table':
                self.tables.append(self.rows);self.rows = None
        if tag == 'table':self.depth = max(0,self.depth-1)


def parse_date(text):
    for fmt in ('%B %d, %Y','%m/%d/%Y','%Y-%m-%d'):
        try:return datetime.strptime(text.strip(),fmt).date()
        except ValueError:pass
    raise ValueError('No supported date')


def fetch_html(url):
    # Exact registry: no arbitrary PDF URL, credentials, redirect, query or port can be fetched.
    if url not in APPROVED_URLS:
        raise ValueError('Unapproved TDU source')
    import httpx
    with httpx.Client(timeout=20,follow_redirects=False,trust_env=False) as client:
        with client.stream('GET',url,headers={'Accept':'text/html'}) as response:
            response.raise_for_status()
            if response.status_code != 200 or 'text/html' not in response.headers.get('content-type','').lower():
                raise ValueError('TDU source must return HTML without a redirect')
            chunks,size=[],0
            for chunk in response.iter_bytes():
                size+=len(chunk)
                if size > 1024*1024:raise ValueError('TDU response exceeds 1 MB')
                chunks.append(chunk)
            return b''.join(chunks).decode('utf-8')


def parse_rates(html, area, url=FOUR_CHANGE_URL, fetched_at=None):
    if url not in APPROVED_URLS or area not in ('Oncor','CenterPoint'):
        raise ValueError('Unapproved source or service area')
    parser=Tables();parser.feed(html)
    candidates=[]
    for rows in parser.tables:
        labels=[cell for row in rows for cell in row if re.fullmatch(r'Updated [A-Za-z]+ \d{1,2}, \d{4} - Residential',cell)]
        if len(labels)!=1:continue
        label=labels[0]
        published=parse_date(label.removeprefix('Updated ').removesuffix(' - Residential'))
        if published > datetime.now(timezone.utc).date():raise ValueError('Future TDU publication date')
        for index,header in enumerate(rows):
            if header.count(area)!=1:continue
            column=header.index(area)
            if index+2 >= len(rows):continue
            fixed,variable=rows[index+1:index+3]
            if len(fixed)!=len(header) or len(variable)!=len(header):continue
            if fixed[0]!='Monthly Charge Per Billing Cycle' or variable[0]!='Usage-based Charge Per kWh':continue
            dollars=re.fullmatch(r'\$(\d+(?:\.\d{1,6})?)',fixed[column])
            cents=re.fullmatch(r'(\d+(?:\.\d{1,6})?)¢',variable[column])
            if not dollars or not cents:continue
            snapshot='\n'.join(' | '.join(row) for row in rows)
            candidates.append(TduSource(url=url,service_area=area,published_on=published.isoformat(),date_label=label,
                fetched_at=fetched_at or datetime.now(timezone.utc).isoformat(),snapshot=snapshot,
                sha256=sha256(snapshot.encode()).hexdigest(),monthly_usd=Decimal(dollars[1]),cents_per_kwh=Decimal(cents[1])))
    if len(candidates)!=1:raise ValueError('Missing or ambiguous residential TDU table')
    return candidates[0]


def candidate_url(plan,pages):
    provider=(plan.provider.value if plan.provider else '').casefold()
    # Domains are tied to provider identity. Other providers are discoverable, not yet fetchable.
    domains={'4change':'4changeenergy.com','discount power':'discountpowertx.com','txu':'txu.com',
             'trieagle':'trieagleenergy.com','gexa':'gexaenergy.com','frontier':'frontierutilities.com',
             'reliant':'reliant.com','ap gas':'apge.com'}
    domain=next((value for name,value in domains.items() if name in provider),None)
    if not domain:return None
    text=' '.join(p['text'] for p in pages)
    text=re.sub(r'/\s+','/',text)
    for raw in re.findall(r'(?:https?://)?(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}/[^\s|<>"\)]+',text):
        parsed=urlsplit(raw if '://' in raw else 'https://'+raw)
        if parsed.hostname and (parsed.hostname.lower()==domain or parsed.hostname.lower().endswith('.'+domain)):
            if 'tdu' in parsed.path.lower() or 'tdsp' in parsed.path.lower():
                if parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:continue
                if domain=='4changeenergy.com' and parsed.path.rstrip('/').lower()=='/tdu-charges':return FOUR_CHANGE_URL
                return urlunsplit(('https',parsed.hostname,parsed.path.rstrip('.,'),'', ''))
    return FOUR_CHANGE_URL if domain=='4changeenergy.com' else None


def needs_tdu(plan):
    kinds={c.kind for c in plan.components}
    return plan.tdu_lookup is not None or not {'delivery_fixed','delivery_energy'} <= kinds


class Resolver:
    def __init__(self,fetcher=fetch_html):
        self.fetcher=fetcher
        self.cache={}
        self.fetched_at=datetime.now(timezone.utc).isoformat()

    def enrich(self,plan,pages):
        # Refresh must remove prior web-derived components before attempting replacement.
        plan=plan.model_copy(deep=True)
        plan.components=[c for c in plan.components if c.evidence.url is None]
        plan.tdu_lookup=None
        missing={'delivery_fixed','delivery_energy'}-{c.kind for c in plan.components}
        if not missing:return plan
        url=candidate_url(plan,pages)
        def blocked(detail,status='unavailable'):
            plan.tdu_lookup=TduLookup(candidate_url=url,status=status,detail=detail)
            return plan
        if not url:return blocked('Delivery charges are missing and no supported provider TDU link was found.')
        if url not in APPROVED_URLS:return blocked('Provider TDU link found; this page needs an approved rate-table parser.','unsupported_source')
        try:
            if url not in self.cache:
                try:self.cache[url]=self.fetcher(url)
                except Exception:self.cache[url]=None
            if self.cache[url] is None:return blocked('Provider TDU page could not be fetched. Retry with --refresh-tdu.')
            source=parse_rates(self.cache[url],plan.service_area.value if plan.service_area else '',url,self.fetched_at)
            issue=parse_date(plan.issue_date.value) if plan.issue_date else None
            if issue is None or parse_date(source.published_on)>issue:
                return blocked('Published TDU table is newer than the PDF issue date or the PDF date is unknown; dated tariff review required.','date_mismatch')
            for component in plan.components:
                expected=source.monthly_usd if component.kind=='delivery_fixed' else source.cents_per_kwh
                if component.kind in ('delivery_fixed','delivery_energy') and component.amount!=expected:
                    return blocked('Stated PDF delivery rate conflicts with the provider table; dated tariff review required.','rate_conflict')
            plan.tdu_lookup=TduLookup(candidate_url=url,status='resolved',detail='Missing delivery charges sourced from the provider residential table.',source=source)
            for kind in sorted(missing):
                plan.components.append(Component(kind=kind,amount=source.monthly_usd if kind=='delivery_fixed' else source.cents_per_kwh,
                    unit='usd_per_month' if kind=='delivery_fixed' else 'cents_per_kwh',minimum_kwh=None,minimum_inclusive=False,
                    maximum_kwh=None,maximum_inclusive=False,evidence=Evidence(page=None,url=url,quote=source.snapshot[:4000])))
            return plan
        except Exception:
            return blocked('Provider TDU page has missing, ambiguous or unsupported dated rates. Manual review required.','review_required')
