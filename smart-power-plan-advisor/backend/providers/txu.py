"""Bounded TXU public API client. No credentials or browser cookies required."""
import json
import re
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit
from uuid import UUID

import httpx

BASE = 'https://shop.txu.com/api'
DOCUMENT_HOSTS = {'shopping.txu.com', 'www.txu.com', 'residential.txu.com'}


class TxuError(ValueError):
    """Controlled public error text without response bodies or credentials."""



def zip_code(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{5}', value):
        raise TxuError('Enter a five-digit ZIP code.')
    return value


def identifier(value):
    if not isinstance(value, str):
        raise TxuError('Invalid TXU identifier')
    return str(UUID(value))


def document_url(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 4096:
        raise TxuError('Invalid TXU document URL')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.hostname not in DOCUMENT_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise TxuError('Unapproved TXU document URL')
    return value


def normalized_rates(offer):
    """API decimal USD values -> catalog units; never derive billing rules."""
    mapping = {'EnergyCharge': ('energy', 100), 'BaseCharge': ('base', 1),
               'DeliveryChargeKwh': ('delivery_energy', 100),
               'DeliveryChargeMonthly': ('delivery_fixed', 1),
               'FiveHundredKwh': ('500', 100), 'OneThousandKwh': ('1000', 100),
               'TwoThousandKwh': ('2000', 100)}
    result = {}
    for rate in offer.get('rates', []):
        if not isinstance(rate, dict):
            raise TxuError('Invalid TXU rate')
        if rate.get('type') not in mapping:
            continue
        key, factor = mapping[rate['type']]
        try:
            amount = Decimal(str(rate['price']))
        except (KeyError, InvalidOperation):
            raise TxuError('Invalid TXU rate amount') from None
        if key in result or not amount.is_finite() or not 0 <= amount <= 100000:
            raise TxuError('Invalid or duplicate TXU rate')
        result[key] = amount * factor
    return result


class TxuClient:
    def __init__(self, client=None):
        self.client = client or httpx.Client(timeout=20, follow_redirects=False,
                                             headers={'Accept': 'application/json, application/pdf'})
        self.owned = client is None

    def close(self):
        if self.owned:
            self.client.close()

    def _get(self, url, *, pdf=False):
        limit = 20 * 1024 * 1024 if pdf else 2 * 1024 * 1024
        for redirect in range(4):
            if pdf:
                document_url(url)
            for attempt in range(3):
                try:
                    with self.client.stream('GET', url, follow_redirects=False) as response:
                        if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                            time.sleep(0.2 * (attempt + 1))
                            continue
                        if response.is_redirect:
                            if not pdf or redirect == 3:
                                raise TxuError('Unexpected TXU redirect')
                            url = urljoin(url, response.headers.get('location', ''))
                            break
                        response.raise_for_status()
                        chunks, size = [], 0
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > limit:
                                raise TxuError('TXU response exceeds size limit')
                            chunks.append(chunk)
                        content = b''.join(chunks)
                        if pdf and not content.startswith(b'%PDF-'):
                            raise TxuError('TXU EFL response is not a PDF')
                        return content
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt == 2:
                        raise
                    time.sleep(0.2 * (attempt + 1))
        raise TxuError('Too many TXU redirects')

    def get_utilities(self, zip_value):
        payload = json.loads(self._get(f'{BASE}/utilities/?zipCode={zip_code(zip_value)}'))
        data = payload.get('data') if isinstance(payload, dict) else None
        values = data.get('utilities') if isinstance(data, dict) else None
        if not isinstance(values, list) or len(values) > 10:
            raise TxuError('Invalid TXU utilities response')
        utilities = []
        for item in values:
            if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not 1 <= len(item['name']) <= 100:
                raise TxuError('Invalid TXU utility')
            utilities.append({'id': identifier(item.get('id')), 'name': item['name']})
        if len({u['id'] for u in utilities}) != len(utilities):
            raise TxuError('Duplicate TXU utilities')
        return utilities

    def get_plans(self, zip_value, utility_id):
        utility_id = identifier(utility_id)
        url = f'{BASE}/plans/?utilityId={utility_id}&zipCode={zip_code(zip_value)}'
        values = json.loads(self._get(url), parse_float=Decimal)
        if not isinstance(values, list) or len(values) > 200:
            raise TxuError('Invalid TXU plans response')
        seen = set()
        for offer in values:
            if not isinstance(offer, dict):
                raise TxuError('Invalid TXU offer')
            offer_id = identifier(offer.get('id'))
            if offer_id in seen:
                raise TxuError('Duplicate TXU offer ID')
            seen.add(offer_id)
            utility, supplier = offer.get('utility'), offer.get('supplier')
            if (not isinstance(utility, dict) or not isinstance(supplier, dict)
                    or identifier(utility.get('id')) != utility_id
                    or supplier.get('name') != 'TXU Energy'):
                raise TxuError('TXU offer provider/utility mismatch')
            if not isinstance(offer.get('name'), str) or not 1 <= len(offer['name']) <= 300:
                raise TxuError('Invalid TXU plan name')
            if type(offer.get('active')) is not bool or type(offer.get('hideOnGrid')) is not bool:
                raise TxuError('Missing TXU availability flags')
        return values

    def get_efl(self, url):
        return self._get(document_url(url), pdf=True)
