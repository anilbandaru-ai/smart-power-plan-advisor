"""Delivery-area discovery; no plan fetching or offer-availability updates."""
import json
from datetime import datetime, timedelta, timezone
from backend.providers.txu import TxuClient, InvalidUtilities, zip_code


def area_name(name):
    normalized = ' '.join(name.casefold().split())
    aliases = {'oncor': 'Oncor', 'oncor electric delivery': 'Oncor',
               'oncor electric delivery company llc': 'Oncor',
               'centerpoint': 'CenterPoint', 'centerpoint energy': 'CenterPoint',
               'centerpoint energy houston electric llc': 'CenterPoint'}
    return aliases.get(normalized, name.strip())


def cached_utilities(store, zipcode):
    with store.connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS delivery_utilities (zip_code TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, payload TEXT NOT NULL, error TEXT)')
        row = db.execute('SELECT * FROM delivery_utilities WHERE zip_code=?', (zip_code(zipcode),)).fetchone()
    if not row:
        return None
    stale = bool(row['error']) or datetime.now(timezone.utc)-datetime.fromisoformat(row['fetched_at']) >= timedelta(hours=24)
    return dict(zip_code=zipcode, utilities=json.loads(row['payload']), fetched_at=row['fetched_at'], stale=stale, error=row['error'])


def resolve_utilities(store, zipcode, client=None):
    zipcode = zip_code(zipcode)
    cached = cached_utilities(store, zipcode)
    if cached and not cached['stale']:
        return cached
    owned = client is None
    client = client or TxuClient()
    error = None
    try:
        values = client.get_utilities(zipcode)
    except InvalidUtilities:
        values = []
        error = (f"We couldn't verify the delivery utility for ZIP {zipcode}. "
                 "The lookup returned incomplete or invalid utility information. "
                 "Check the utility name on your electricity bill or confirm service for your exact address with your local utility. "
                 "We haven't selected a provider or compared plans for this ZIP.")
    except Exception:
        values = []
        error = 'Delivery utility lookup failed. Please try again.'
    finally:
        if owned:
            client.close()
    timestamp = datetime.now(timezone.utc).isoformat()
    with store.connection() as db:
        db.execute('INSERT OR REPLACE INTO delivery_utilities VALUES (?,?,?,?)', (zipcode, timestamp, json.dumps(values), error))
    return dict(zip_code=zipcode, utilities=values, fetched_at=timestamp, stale=bool(error), error=error)
