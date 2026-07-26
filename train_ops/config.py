# train_ops/config.py
# Single source of truth for all train-performance parameters.
# No logic, no imports of other train_ops modules — mirrors the root
# config.py's own role for the main project.
#
# train_ops/ is intentionally its own self-contained package (its own
# config/data/core/ui), separate from the cargo-scheduling project it
# feeds. The only cross-package reads are physical/reference constants
# that have no business being duplicated (LNG energy density, terminal
# coordinates) and the shared TTF price fetcher — see core/forecast.py.

# ---------------------------------------------------------------------------
# Physical — LNG density (train_ops-specific: converts MTPA nameplate
# capacity to a daily mmBtu rate). Typical industry planning value; real
# density varies 430-470 kg/m3 with composition and temperature.
# ---------------------------------------------------------------------------

LNG_DENSITY_KG_PER_M3 = 450.0
DAYS_PER_YEAR         = 365.0

# ---------------------------------------------------------------------------
# Derating — gas-turbine-driven refrigeration compressors lose air mass
# flow (and so power) as ambient temperature rises above the ISO reference
# condition. ~0.5-1%/°C above reference is the commonly cited range for
# industrial gas turbines; 0.7%/°C is a representative mid-point.
# ---------------------------------------------------------------------------

REFERENCE_TEMP_C     = 15.0    # ISO standard rating condition
DERATING_PCT_PER_C    = 0.007

# ---------------------------------------------------------------------------
# Load factor — operating range. Real trains don't run at a clean 0-100%:
# there's a technical floor below which it's more efficient to shut down
# entirely, and a practical ceiling below nameplate that accounts for
# routine variability (not sustained 100% indefinitely).
# ---------------------------------------------------------------------------

MIN_LOAD_FACTOR = 0.60
MAX_LOAD_FACTOR = 0.95

# ---------------------------------------------------------------------------
# Breakeven — the load-factor decision throttles down if today's price
# doesn't clear cost by this safety margin. Feedgas + opex is the
# per-mmBtu cost floor; DEFAULT_BREAKEVEN_USD_MMBTU below is representative
# of a low-cost basin (Qatar-class North Field feedgas) — a higher-cost
# site (e.g. a future US-based train) would set this much closer to its
# HH-linked feedgas cost, and would visibly throttle far more often. This
# gap IS the point: it's what makes breakeven worth modeling per train.
# ---------------------------------------------------------------------------

DEFAULT_BREAKEVEN_USD_MMBTU = 3.0
BREAKEVEN_SAFETY_MARGIN     = 1.15   # price must clear breakeven x this to run at max

# ---------------------------------------------------------------------------
# Cargo generation — how continuous production becomes discrete cargoes
# the existing scheduler (core.optimizer.assign_cargoes) can consume.
# ---------------------------------------------------------------------------

CARGO_SIZE_MMBTU        = 3_000_000.0   # matches the scale of data/cargoes.py's existing cargoes
LOADING_LEAD_TIME_DAYS  = 1.5           # tank full -> ready to load (logistics/berth coordination)
LAYCAN_WINDOW_DAYS      = 2.0
DEFAULT_CARGO_PRIORITY  = 6             # mid-range vs. the existing 4-10 scale in data/cargoes.py
FORECAST_HORIZON_DAYS   = 90

# ---------------------------------------------------------------------------
# Weather — Open-Meteo gives real daily forecasts up to ~16 days out; nothing
# free goes further because nothing CAN, reliably (matches this project's
# own stance in core/spot.py: don't fabricate certainty about the future).
# Beyond the live window, fall back to monthly climatological averages.
# ---------------------------------------------------------------------------

WEATHER_LIVE_FORECAST_DAYS = 16

# Approximate Doha/Ras Laffan (Qatar) monthly average temperatures, °C —
# desert climate, source: public climate normals, informational precision.
SEASONAL_AVG_TEMP_C_BY_MONTH = {
    1: 18.0, 2: 19.0, 3: 23.0, 4: 28.0, 5: 33.0, 6: 36.0,
    7: 37.0, 8: 37.0, 9: 34.0, 10: 30.0, 11: 25.0, 12: 20.0,
}


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== train_ops/config.py ===")

    print("\n-- Derating --")
    print(f"  Reference temp    : {REFERENCE_TEMP_C}°C")
    print(f"  Derating rate     : {DERATING_PCT_PER_C*100:.2f}%/°C above reference")

    print("\n-- Load factor range --")
    print(f"  Min : {MIN_LOAD_FACTOR*100:.0f}%")
    print(f"  Max : {MAX_LOAD_FACTOR*100:.0f}%")

    print("\n-- Breakeven --")
    print(f"  Default breakeven : ${DEFAULT_BREAKEVEN_USD_MMBTU}/mmBtu")
    print(f"  Safety margin     : x{BREAKEVEN_SAFETY_MARGIN}")

    print("\n-- Cargo generation --")
    print(f"  Cargo size        : {CARGO_SIZE_MMBTU:,.0f} mmBtu")
    print(f"  Loading lead time : {LOADING_LEAD_TIME_DAYS} days")
    print(f"  Laycan window     : {LAYCAN_WINDOW_DAYS} days")

    print("\n-- Seasonal fallback temps (Qatar) --")
    for month, temp in SEASONAL_AVG_TEMP_C_BY_MONTH.items():
        print(f"  Month {month:>2}: {temp}°C")

    print("\nOK")
