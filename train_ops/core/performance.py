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
    MAINTENANCE_EARLIEST_START_DAY,
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
        start_day = window.get("start_day")
        if start_day is None:
            continue   # not yet resolved (see resolve_maintenance_windows) -> treat as not scheduled
        if start_day <= day < start_day + window["duration_days"]:
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
    Continuous throttle between the technical minimum and the max
    sustainable rate, ramping linearly as price clears breakeven. A real
    train's turbine/compressor train modulates output continuously across
    this middle band — it's only at the floor (price at or below
    breakeven, no margin left to justify running harder) and the ceiling
    (price already clearing the safety margin, no reason to hold back)
    that the rate flattens out, not a hard on/off switch in between.
    """
    breakeven = train.get("breakeven_usd_mmbtu", DEFAULT_BREAKEVEN_USD_MMBTU)
    ratio = price_usd_mmbtu / breakeven

    if ratio >= BREAKEVEN_SAFETY_MARGIN:
        return train["max_load_factor"], "above breakeven + margin -> max sustainable rate"
    if ratio <= 1.0:
        return train["min_load_factor"], "at or below breakeven -> technical minimum"

    span   = BREAKEVEN_SAFETY_MARGIN - 1.0
    weight = (ratio - 1.0) / span
    load_factor = train["min_load_factor"] + weight * (train["max_load_factor"] - train["min_load_factor"])
    return load_factor, f"{weight*100:.0f}% of the way from breakeven to breakeven+margin -> ramping up"


def _counterfactual_daily_value(train, price_usd_mmbtu, ambient_temp_c):
    """What this train would have produced (and earned) on a day it's NOT
    down for maintenance — the opportunity cost a turnaround gives up."""
    load_factor, _ = decide_load_factor(train, price_usd_mmbtu)
    derating = calculate_derating_factor(ambient_temp_c, train)
    produced = nameplate_capacity_mmbtu_day(train) * load_factor * derating
    return produced * price_usd_mmbtu


def optimize_maintenance_start_day(train, duration_days, weather, price_path,
                                    earliest_day=MAINTENANCE_EARLIEST_START_DAY):
    """
    Pick the planned-turnaround start day that minimizes the value of
    production given up, instead of pinning it to an arbitrary fixed
    date. A real operator schedules a shutdown for the cheapest,
    lowest-output stretch it can find (low price, and/or hot weather
    already suppressing output via derating) — this searches every
    feasible window in the forecast horizon and picks that one.

    weather: this train's day-by-day forecast (core.weather's output —
    one entry per day, `day` + `temp_c`).
    price_path: day-indexed list, same horizon (see generate_price_path).

    Returns (start_day, lost_value_usd). None if no window of this
    duration fits in [earliest_day, horizon).
    """
    horizon_days = len(weather)
    temp_by_day = {w["day"]: w["temp_c"] for w in weather}

    def _search(start_from):
        best_start, best_value = None, None
        for start in range(start_from, horizon_days - duration_days + 1):
            window_days = range(start, start + duration_days)
            if any(d not in temp_by_day or d >= len(price_path) for d in window_days):
                continue
            value = sum(_counterfactual_daily_value(train, price_path[d], temp_by_day[d]) for d in window_days)
            if best_value is None or value < best_value:
                best_start, best_value = start, value
        return best_start, best_value

    best_start, best_value = _search(earliest_day)
    if best_start is None and earliest_day > 0:
        # Short horizon (e.g. a quick preview run) — the preferred buffer
        # doesn't leave room for the window; fall back to "as soon as
        # possible" rather than silently dropping the turnaround.
        best_start, best_value = _search(0)

    return best_start, best_value


def resolve_maintenance_windows(train, weather, price_path):
    """
    Returns a copy of `train` with every maintenance window's start_day
    filled in via optimize_maintenance_start_day (windows that already
    carry an explicit start_day are left alone — lets a specific date be
    pinned by hand if ever needed, without touching this code path).
    """
    resolved_windows = []
    for window in train["maintenance_windows"]:
        if "start_day" in window:
            resolved_windows.append(window)
            continue
        start_day, lost_value_usd = optimize_maintenance_start_day(train, window["duration_days"], weather, price_path)
        if start_day is None:
            continue   # horizon too short to fit this window at all — skip it this run, not a crash
        resolved_windows.append({
            **window,
            "start_day":      start_day,
            "lost_value_usd": round(lost_value_usd, 2),
        })
    return {**train, "maintenance_windows": resolved_windows}


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
    breakeven_price = train["breakeven_usd_mmbtu"]
    for price in [2.0, breakeven_price, breakeven_price * 1.075, 4.0, 10.0]:
        lf, reason = decide_load_factor(train, price)
        print(f"  price=${price:<6.3f} -> load_factor={lf*100:.1f}%  ({reason})")

    print(f"\n-- Continuous ramp: load factor should strictly increase as price clears breakeven --")
    mid_price = breakeven_price * (1.0 + BREAKEVEN_SAFETY_MARGIN) / 2.0   # halfway between breakeven and breakeven+margin
    lf_floor, _ = decide_load_factor(train, breakeven_price)
    lf_mid, _   = decide_load_factor(train, mid_price)
    lf_ceil, _  = decide_load_factor(train, breakeven_price * BREAKEVEN_SAFETY_MARGIN)
    print(f"  at breakeven      -> {lf_floor*100:.1f}%")
    print(f"  halfway to margin -> {lf_mid*100:.1f}%")
    print(f"  at breakeven+margin -> {lf_ceil*100:.1f}%")
    assert lf_floor == train["min_load_factor"]
    assert lf_ceil == train["max_load_factor"]
    assert lf_floor < lf_mid < lf_ceil, "load factor should ramp strictly between floor and ceiling"
    print("  OK, ramps continuously instead of jumping straight from min to max")

    print(f"\n-- Maintenance window optimization: cheapest/lowest-output stretch wins --")
    # Deliberately cheap AND hot (so both price and derating pull the same
    # way) for days 40-45 — a correct optimizer should land the turnaround
    # exactly there, not at the earliest allowed day.
    horizon_days = 60
    weather_synth = [{"day": d, "temp_c": 45.0 if 40 <= d < 46 else 25.0} for d in range(horizon_days)]
    price_synth   = [1.5 if 40 <= d < 46 else 10.8 for d in range(horizon_days)]
    start_day, lost_value = optimize_maintenance_start_day(train, 6, weather_synth, price_synth)
    print(f"  chosen start day: {start_day}  (lost value ${lost_value:,.0f})")
    assert start_day == 40, f"expected the cheap/hot window at day 40, got {start_day}"
    print("  OK, landed on the cheap/low-output window instead of the earliest feasible day")

    resolved = resolve_maintenance_windows(train, weather_synth, price_synth)
    resolved_window = resolved["maintenance_windows"][0]
    print(f"  resolved window: start_day={resolved_window['start_day']} "
          f"duration={resolved_window['duration_days']}d ({resolved_window['label']})")
    assert resolved_window["start_day"] == start_day

    print(f"\n-- Maintenance window check (using the resolved window above) --")
    for day in [0, resolved_window["start_day"] - 1, resolved_window["start_day"],
                resolved_window["start_day"] + resolved_window["duration_days"] - 1,
                resolved_window["start_day"] + resolved_window["duration_days"]]:
        under, label = is_under_maintenance(resolved, day)
        print(f"  day {day:>2}: {'MAINTENANCE (' + label + ')' if under else 'operating'}")

    print(f"\n-- Maintenance search: short horizon falls back gracefully instead of crashing --")
    tiny_weather = [{"day": d, "temp_c": 25.0} for d in range(10)]
    tiny_price   = [10.8] * 10
    fallback_start, _ = optimize_maintenance_start_day(train, 6, tiny_weather, tiny_price)
    print(f"  10-day horizon, 6-day window, earliest-preferred day 7 -> falls back to day {fallback_start}")
    assert fallback_start is not None and fallback_start + 6 <= 10
    too_short_start, too_short_value = optimize_maintenance_start_day(train, 20, tiny_weather, tiny_price)
    print(f"  10-day horizon, 20-day window -> {too_short_start} (doesn't fit at all)")
    assert too_short_start is None and too_short_value is None
    print("  OK, no crash either way")

    print(f"\n-- Full daily production chain, a few sample days --")
    maint_day = resolved_window["start_day"]
    for day, temp, price in [(0, 20.0, 10.8), (10, 38.0, 10.8), (maint_day, 20.0, 10.8), (60, 45.0, 1.5)]:
        result = calculate_daily_production(resolved, day, temp, price)
        print(f"  day {day:>2} temp={temp:>5.1f}C price=${price:<5} -> "
              f"{result['produced_mmbtu']:>10,.0f} mmBtu  [{result['status']}]")
    assert calculate_daily_production(resolved, maint_day, 20.0, 10.8)["produced_mmbtu"] == 0.0

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
