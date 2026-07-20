# core/market.py
# Market data access: TTF, JKM (derived), HH, Brent, FX.
#
# Every getter defaults to use_live=False and falls back to the static
# values in config.py — fast, offline, deterministic (matches every other
# self-test in this project). Live fetch code paths exist but are not
# exercised by default; see CONTEXT.md for what's actually wired up vs.
# still a documented gap (TTF has no confirmed free source, HH needs an
# EIA_API_KEY environment variable that isn't set here).

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from config import PRICE_TTF, PRICE_HH, PRICE_BRENT, ASIAN_SPREAD_USD_MMBTU, FX_RATE_USD_TO

FRANKFURTER_FX_ENDPOINT = "https://api.frankfurter.app/latest"
EIA_HH_SERIES_ENDPOINT  = "https://api.eia.gov/v2/natural-gas/pri/fut/data/"


# ---------------------------------------------------------------------------
# TTF
# ---------------------------------------------------------------------------

def get_ttf_price(use_live=False):
    """
    Title Transfer Facility spot price, $/mmBtu.

    No confirmed free public source for TTF spot prices has been identified
    (ENTSOG publishes grid flow/capacity data, not prices — TTF is normally
    a paid feed via ICE Endex or similar). use_live=True therefore raises
    internally and falls back, rather than guessing at a URL that wouldn't
    actually serve the right data.
    """
    if use_live:
        try:
            raise NotImplementedError(
                "No confirmed free TTF spot price source — needs a real "
                "market data subscription (ICE Endex etc.) before going live."
            )
        except NotImplementedError:
            pass

    return {"price_usd_mmbtu": PRICE_TTF, "source": "fallback (config.py)"}


# ---------------------------------------------------------------------------
# JKM — derived from TTF + Asian spread
# ---------------------------------------------------------------------------

def get_jkm_price(use_live=False):
    """Japan/Korea Marker, $/mmBtu = TTF + ASIAN_SPREAD_USD_MMBTU."""
    ttf = get_ttf_price(use_live)
    jkm_price = ttf["price_usd_mmbtu"] + ASIAN_SPREAD_USD_MMBTU

    return {
        "price_usd_mmbtu": round(jkm_price, 3),
        "source": ttf["source"],
        "basis": "TTF + spread",
    }


# ---------------------------------------------------------------------------
# Henry Hub
# ---------------------------------------------------------------------------

def get_hh_price(use_live=False):
    """
    Henry Hub spot price, $/mmBtu. Live path needs an EIA_API_KEY
    environment variable (free registration at eia.gov) — never hardcode
    the key in source. Exact EIA v2 query params are not verified here
    (no key available to test against) — the structure is in place, the
    request shape should be checked against EIA v2 docs before real use.
    """
    api_key = os.environ.get("EIA_API_KEY")

    if use_live and api_key:
        try:
            resp = requests.get(
                EIA_HH_SERIES_ENDPOINT,
                params={"api_key": api_key, "frequency": "daily",
                        "data[0]": "value", "facets[series][]": "RNGWHHD",
                        "sort[0][column]": "period", "sort[0][direction]": "desc",
                        "length": 1},
                timeout=5,
            )
            resp.raise_for_status()
            value = resp.json()["response"]["data"][0]["value"]
            return {"price_usd_mmbtu": round(float(value), 3), "source": "live (EIA)"}
        except Exception:
            pass

    source = "fallback (config.py)" if api_key else "fallback (no EIA_API_KEY)"
    return {"price_usd_mmbtu": PRICE_HH, "source": source}


# ---------------------------------------------------------------------------
# Brent
# ---------------------------------------------------------------------------

def get_brent_price(use_live=False):
    """
    Brent crude, $/bbl. Live path uses yfinance (ticker BZ=F) — optional
    dependency, not installed by default (pip install yfinance).
    Informational only: nothing in core/pnl.py consumes Brent yet.
    """
    if use_live:
        try:
            import yfinance as yf
            history = yf.Ticker("BZ=F").history(period="1d")
            price = float(history["Close"].iloc[-1])
            return {"price_usd_bbl": round(price, 2), "source": "live (yfinance)"}
        except ImportError:
            pass
        except Exception:
            pass

    return {"price_usd_bbl": PRICE_BRENT, "source": "fallback (config.py)"}


# ---------------------------------------------------------------------------
# FX
# ---------------------------------------------------------------------------

def get_fx_rate(quote_currency, use_live=False):
    """USD -> quote_currency rate. Live path uses frankfurter.app (ECB, free, no key)."""
    if use_live:
        try:
            resp = requests.get(
                FRANKFURTER_FX_ENDPOINT,
                params={"from": "USD", "to": quote_currency},
                timeout=5,
            )
            resp.raise_for_status()
            rate = resp.json()["rates"][quote_currency]
            return {"rate": round(float(rate), 4), "source": "live (frankfurter.app)"}
        except Exception:
            pass

    return {"rate": FX_RATE_USD_TO[quote_currency], "source": "fallback (config.py)"}


# ---------------------------------------------------------------------------
# Snapshot — public entry point for core/pnl.py
# ---------------------------------------------------------------------------

def get_market_snapshot(use_live=False):
    """One consistent set of prices, fetched once, reused across a whole
    assignment batch by core/pnl.py (avoids re-fetching per candidate
    destination and re-pricing mid-batch if a live price moves)."""
    return {
        "TTF":   get_ttf_price(use_live),
        "JKM":   get_jkm_price(use_live),
        "HH":    get_hh_price(use_live),
        "BRENT": get_brent_price(use_live),
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== core/market.py ===")

    print("\n-- Fallback prices (use_live=False, default) --")
    snapshot = get_market_snapshot()
    for marker, data in snapshot.items():
        price_key = "price_usd_bbl" if marker == "BRENT" else "price_usd_mmbtu"
        unit = "bbl" if marker == "BRENT" else "mmBtu"
        print(f"  {marker:<6} ${data[price_key]}/{unit}  [{data['source']}]")

    print("\n-- FX (fallback) --")
    for currency in ["EUR", "JPY"]:
        fx = get_fx_rate(currency)
        print(f"  USD -> {currency}: {fx['rate']}  [{fx['source']}]")

    print("\n-- Live paths (best-effort, not required to succeed offline) --")
    ttf_live = get_ttf_price(use_live=True)
    print(f"  TTF live attempt  -> {ttf_live['source']}")
    hh_live = get_hh_price(use_live=True)
    print(f"  HH live attempt   -> {hh_live['source']}")
    brent_live = get_brent_price(use_live=True)
    print(f"  Brent live attempt -> {brent_live['source']}")

    print("\nOK")
