# train_ops/core/performance.py
# Converts a train's nameplate capacity into an actual daily production
# rate given ambient temperature (derating), the chosen load factor,
# whether it's under planned maintenance, and whether it's down for an
# unplanned trip.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from train_ops.config import (
    LNG_DENSITY_KG_PER_M3, DAYS_PER_YEAR, DEFAULT_BREAKEVEN_USD_MMBTU, BREAKEVEN_SAFETY_MARGIN,
    UNPLANNED_TRIP_DAILY_PROBABILITY, UNPLANNED_REPAIR_MIN_DAYS, UNPLANNED_REPAIR_MAX_DAYS,
)
from config import LNG_ENERGY_DENSITY_MMBTU_PER_M3   # shared physical constant, main project's config.py


def nameplate_capacity_mmbtu_day(train):
    """
    MTPA (million tonnes/year) -> mmBtu/day, via the same m3<->mmBtu
    conversion the main project already uses for every cargo/vessel
    volume — one physical constant, not two competing ones.
    """
    tonnes_per_year = train["capacity_mtpa"] * 1_000_000
    m3_per_year      = tonnes_per_year * 1000.0 / LNG_DENSITY_KG_PER_M3
    mmbtu_per_year   = m3_per_year * LNG_ENERGY_DENSITY_MMBTU_PER_M3
    return mmbtu_per_year / DAYS_PER_YEAR


def calculate_derating_factor(ambient_temp_c, train):
    """
    Fraction of nameplate capacity actually available at this temperature.
    Gas-turbine-driven refrigeration compressors lose air mass flow (and
    so power) above the ISO reference condition — this is a real,
    well-documented effect, not a cosmetic penalty.
    """
    delta  = max(0.0, ambient_temp_c - train["reference_temp_c"])
    factor = 1.0 - train["derating_pct_per_c"] * delta
    return max(0.0, min(1.0, factor))


def is_under_maintenance(train, day):
    for window in train["maintenance_windows"]:
        if window["start_day"] <= day < window["start_day"] + window["duration_days"]:
            return True, window["label"]
    return False, None


def decide_unplanned_trip(rng):
    """
    One Bernoulli draw: does an unplanned trip start today? Pure function
    of the RNG handed in — core.forecast owns the seed (per train, so
    adding a train never changes another train's draws) and the
    day-by-day state (whether a previous trip's repair is still ongoing),
    since neither is knowable from a single day in isolation.
    """
    return rng.random() < UNPLANNED_TRIP_DAILY_PROBABILITY


def draw_repair_duration(rng):
    return rng.randint(UNPLANNED_REPAIR_MIN_DAYS, UNPLANNED_REPAIR_MAX_DAYS)


def decide_load_factor(train, price_usd_mmbtu):
    """
    Two-tier throttle: run at the max sustainable rate if today's price
    clears breakeven by a safety margin, drop to the technical minimum
    otherwise. Real trains don't turn down continuously between 0-100% —
    they run near a ceiling or near a floor, rarely in between.
    """
    breakeven = train.get("breakeven_usd_mmbtu", DEFAULT_BREAKEVEN_USD_MMBTU)
    if price_usd_mmbtu >= breakeven * BREAKEVEN_SAFETY_MARGIN:
        return train["max_load_factor"], "above breakeven + margin -> max sustainable rate"
    return train["min_load_factor"], "below breakeven + margin -> technical minimum"


def calculate_daily_production(train, day, ambient_temp_c, price_usd_mmbtu, unplanned_outage_label=None):
    """
    Full chain for one train, one day: maintenance check -> unplanned
    outage check -> load-factor decision (breakeven) -> derating
    (temperature) -> mmBtu produced.

    unplanned_outage_label: set by core.forecast's day-by-day loop (not
    computed here) when this day falls inside an unplanned trip's repair
    window — whether that's true depends on state across days (did a trip
    start recently and is repair still ongoing), which a single day's
    calculation can't know on its own.

    Returns a dict with every intermediate figure — nothing here is a
    black box, each step is inspectable (useful both for the UI and for
    explaining the number in an interview).
    """
    under_maintenance, label = is_under_maintenance(train, day)
    if under_maintenance:
        return {
            "day": day, "produced_mmbtu": 0.0, "load_factor": 0.0,
            "derating_factor": 0.0, "ambient_temp_c": ambient_temp_c,
            "status": f"Maintenance — {label}",
        }

    if unplanned_outage_label:
        return {
            "day": day, "produced_mmbtu": 0.0, "load_factor": 0.0,
            "derating_factor": 0.0, "ambient_temp_c": ambient_temp_c,
            "status": f"Unplanned outage — {unplanned_outage_label}",
        }

    load_factor, reason = decide_load_factor(train, price_usd_mmbtu)
    derating = calculate_derating_factor(ambient_temp_c, train)
    nameplate = nameplate_capacity_mmbtu_day(train)
    produced = nameplate * load_factor * derating

    return {
        "day": day, "produced_mmbtu": round(produced, 0),
        "load_factor": load_factor, "derating_factor": round(derating, 4),
        "ambient_temp_c": ambient_temp_c, "status": reason,
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from train_ops.data.trains import TRAINS

    print("=== train_ops/core/performance.py ===")
    train = TRAINS[0]

    nameplate = nameplate_capacity_mmbtu_day(train)
    print(f"\n-- Nameplate capacity --")
    print(f"  {train['capacity_mtpa']} MTPA -> {nameplate:,.0f} mmBtu/day at 100% load, no derating")

    print(f"\n-- Derating vs ambient temperature (reference {train['reference_temp_c']}C) --")
    for temp in [15, 25, 35, 40, 45]:
        factor = calculate_derating_factor(temp, train)
        print(f"  {temp}C -> {factor*100:.1f}% of nameplate")

    print(f"\n-- Load factor decision vs price (breakeven ${train['breakeven_usd_mmbtu']}/mmBtu) --")
    for price in [2.0, 3.0, 4.0, 10.0]:
        lf, reason = decide_load_factor(train, price)
        print(f"  price=${price:<5} -> load_factor={lf*100:.0f}%  ({reason})")

    print(f"\n-- Maintenance window check --")
    for day in [0, 44, 45, 47, 50, 51]:
        under, label = is_under_maintenance(train, day)
        print(f"  day {day:>2}: {'MAINTENANCE (' + label + ')' if under else 'operating'}")

    print(f"\n-- Full daily production chain, a few sample days --")
    for day, temp, price in [(0, 20.0, 10.8), (10, 38.0, 10.8), (45, 20.0, 10.8), (60, 45.0, 1.5)]:
        result = calculate_daily_production(train, day, temp, price)
        print(f"  day {day:>2} temp={temp:>5.1f}C price=${price:<5} -> "
              f"{result['produced_mmbtu']:>10,.0f} mmBtu  [{result['status']}]")

    print(f"\n-- Unplanned outage: forced trip + repair override --")
    forced_trip = calculate_daily_production(train, 20, 20.0, 10.8, unplanned_outage_label="trip, 3d repair")
    print(f"  day 20 (forced trip) -> {forced_trip['produced_mmbtu']:,.0f} mmBtu  [{forced_trip['status']}]")
    assert forced_trip["produced_mmbtu"] == 0.0

    print(f"\n-- Unplanned trip draws, reproducibility check --")
    import random
    rng_a = random.Random(42)
    rng_b = random.Random(42)
    draws_a = [decide_unplanned_trip(rng_a) for _ in range(200)]
    draws_b = [decide_unplanned_trip(rng_b) for _ in range(200)]
    assert draws_a == draws_b
    print(f"  same seed -> identical draws over 200 days ({sum(draws_a)} trips)")

    print("\nOK")
