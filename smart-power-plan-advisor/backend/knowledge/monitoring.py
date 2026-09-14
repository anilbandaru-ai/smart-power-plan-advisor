"""Sanitized process-local counters. Monetary estimates require configured rates."""
import json
import logging
import os
import threading
from collections import Counter
from time import perf_counter
from contextlib import contextmanager

_lock = threading.Lock()
_counts = Counter()
_logger = logging.getLogger("uvicorn.error")


def record(event, **values):
    allowed = {k: v for k, v in values.items() if k in
               ("latency_ms", "input_tokens", "output_tokens", "candidates", "miss", "failure", "unsupported")
               and isinstance(v, (int, float, bool))}
    with _lock:
        _counts[event + ".count"] += 1
        for key, val in allowed.items():
            _counts[event + "." + key] += val
    _logger.info("rag_event %s", json.dumps({"event": event, **allowed}))


def usage(event, response):
    info = getattr(response, "usage", None)
    incoming = getattr(info, "input_tokens", getattr(info, "prompt_tokens", 0)) or 0
    outgoing = getattr(info, "output_tokens", 0) or 0
    if isinstance(incoming, int) and isinstance(outgoing, int):
        record(event, input_tokens=incoming, output_tokens=outgoing)


@contextmanager
def timed(event):
    start = perf_counter()
    try:
        yield
    except Exception:
        record(event, latency_ms=(perf_counter()-start)*1000, failure=1)
        raise
    else:
        record(event, latency_ms=(perf_counter()-start)*1000)


def snapshot():
    with _lock:
        values = dict(_counts)
    estimate = None
    try:
        rates = [float(os.environ[k]) for k in ("RAG_INPUT_USD_PER_MILLION", "RAG_OUTPUT_USD_PER_MILLION")]
        if all(r >= 0 for r in rates):
            estimate = sum(v * rates[0 if k.endswith('.input_tokens') else 1] / 1000000
                           for k, v in values.items() if k.endswith(('.input_tokens', '.output_tokens')))
    except (KeyError, ValueError):
        pass
    return {"counters": values, "estimated_model_cost_usd": estimate,
            "cost_basis": "User-configured blended token rates; excludes Pinecone and local OCR costs",
            "lifetime": "current server process"}
