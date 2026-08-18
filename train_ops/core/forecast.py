# train_ops/core/forecast.py
# Day-by-day production forecast, one or more trains. This is the one file
# in train_ops/ that reaches outside the package on purpose:
#   - data.terminals (main project)  -> a train's site coordinates/id are
#     physical reference data, not business logic; no reason to duplicate
#     the terminal list a second time.
#   - core.market.get_ttf_price (main project) -> one shared source of
#     truth for the TTF price, same live/fallback contract the trading
#     side already uses. Never imported the other way around.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import math
import random
import zlib
from datetime import datetime

from data.terminals import TERMINALS
from core.market     import get_ttf_price

from train_ops.config           import (
    FORECAST_HORIZON_DAYS, RELIABILITY_SEED,
    TRAIN_PRICE_DAILY_VOLATILITY, TRAIN_PRICE_MEAN_REVERSION_SPEED, TRAIN_PRICE_SEED,
)
from train_ops.core.weather     import get_temperature_forecast
from train_ops.core.performance import (
    calculate_daily_production, is_under_maintenance, decide_unplanned_trip, draw_repair_duration,
    resolve_maintenance_windows,
)

TERMINALS_BY_ID = {t["id"]: t for t in TERMINALS}


def _reliability_rng(train):
    """
    Seeded per train (via a deterministic string hash — not Python's
    built-in hash(), which is randomized per process) so adding a train
    never changes another train's unplanned-trip draws.
    """
    return random.Random(RELIABILITY_SEED + zlib.crc32(train["id"].encode()))


def generate_price_path(anchor_price, horizon_days, seed=TRAIN_PRICE_SEED):
    """
    Day-by-day, mean-reverting TTF-linked price for one forecast horizon —
    the train side's own generator (see train_ops/config.py), separate
    from core.spot's, so this package never has to import trading-side
    internals to know what tomorrow's price might be. Anchored on today's
    real snapshot (core.market.get_ttf_price, live or fallback) rather
    than a second hardcoded constant, and reverts back toward that same
    anchor over the horizon — same Ornstein-Uhlenbeck-in-log-space idea as
    core.spot's price paths, independently seeded.

    Same seed -> same path, every run.
    """
    rng = random.Random(seed)
    log_anchor = math.log(anchor_price)
    log_price  = log_anchor
    path = [anchor_price]
    for _ in range(1, horizon_days):
        shock = rng.gauss(0.0, 1.0)
        log_price += TRAIN_PRICE_MEAN_REVERSION_SPEED * (log_anchor - log_price) + TRAIN_PRICE_DAILY_VOLATILITY * shock
        path.append(round(math.exp(log_price), 3))
    return path


def simulate_train_forecast(train, start_date, horizon_days, price_path, use_live_weather=True):
    """
    Day-by-day production for ONE train. Pure function of its inputs — the
    fleet-level runner below just calls this once per train in TRAINS, so
    going from 1 train to N is a loop, not a rewrite.

    price_path: day-indexed daily price (generate_price_path) — drives
    both the day-by-day load-factor decision and, via
    resolve_maintenance_windows, where this run lands the planned
    turnaround (the cheapest/lowest-output stretch of THIS horizon, so a
    different call with a different horizon or price path can legitimately
    land it on a different day).

    Unplanned outages are the one piece of state that carries across days
    within this loop (is a trip's repair still ongoing) — everything else
    in core.performance is a pure function of (train, day, weather, price).

    Returns (days, resolved_train) — resolved_train is `train` with its
    maintenance_windows' start_day filled in for this run, so callers that
    need to display/reuse the resolved schedule don't have to re-derive it.
    """
    terminal = TERMINALS_BY_ID[train["terminal_id"]]
    weather  = get_temperature_forecast(terminal["lat"], terminal["lon"], start_date, horizon_days, use_live_weather)
    resolved_train = resolve_maintenance_windows(train, weather, price_path)
    rng = _reliability_rng(train)

    days = []
    cumulative  = 0.0
    recovery_day = -1   # -1 = no unplanned outage in progress
    for w in weather:
        day = w["day"]
        unplanned_label = None

        if day <= recovery_day:
            unplanned_label = "in repair"
        else:
            under_maintenance, _ = is_under_maintenance(resolved_train, day)
            if not under_maintenance and decide_unplanned_trip(rng):
                repair_days  = draw_repair_duration(rng)
                recovery_day = day + repair_days - 1
                unplanned_label = f"trip started, {repair_days}d repair"

        result = calculate_daily_production(resolved_train, day, w["temp_c"], price_path[day], unplanned_label)
        cumulative += result["produced_mmbtu"]
        days.append({
            **result,
            "date":              w["date"],
            "weather_source":    w["source"],
            "cumulative_mmbtu":  cumulative,
        })
    return days, resolved_train


def calculate_availability(days):
    """Fraction of days NOT down for planned maintenance or an unplanned
    outage — the standard reliability KPI (availability %)."""
    if not days:
        return 1.0
    down_days = sum(1 for d in days if d["produced_mmbtu"] == 0.0)
    return 1.0 - down_days / len(days)


def run_fleet_forecast(trains, horizon_days=FORECAST_HORIZON_DAYS, use_live_weather=True, use_live_price=False):
    """
    Forecast for every train in `trains` (normally train_ops.data.trains.TRAINS),
    sharing one day-by-day price path (anchored on one TTF snapshot fetched
    once) so every train's load-factor decision — and its planned-maintenance
    timing — is priced consistently, same principle as core.pnl fetching one
    market snapshot per batch instead of re-pricing per candidate.
    """
    start_date = datetime.now()
    price = get_ttf_price(use_live_price)
    price_path = generate_price_path(price["price_usd_mmbtu"], horizon_days)

    by_train = {}
    resolved_maintenance_by_train = {}
    for train in trains:
        days, resolved_train = simulate_train_forecast(train, start_date, horizon_days, price_path, use_live_weather)
        by_train[train["id"]] = days
        resolved_maintenance_by_train[train["id"]] = resolved_train["maintenance_windows"]

    return {
        "start_date":       start_date,
        "price_usd_mmbtu":  price["price_usd_mmbtu"],
        "price_source":     price["source"],
        "price_path":       price_path,
        "by_train":         by_train,
        "resolved_maintenance_by_train": resolved_maintenance_by_train,
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from train_ops.data.trains import TRAINS

    print("=== train_ops/core/forecast.py ===")

    print("\n-- Price path: mean-reverting, reproducible, own generator --")
    path_a = generate_price_path(10.80, 90)
    path_b = generate_price_path(10.80, 90)
    assert path_a == path_b
    print(f"  day 0: ${path_a[0]:.2f}  day 30: ${path_a[30]:.2f}  day 89: ${path_a[89]:.2f}")
    print("  OK, same seed -> identical path")

    fleet = run_fleet_forecast(TRAINS, horizon_days=90)
    print(f"\n  Price anchor (day 0): ${fleet['price_usd_mmbtu']}/mmBtu  [{fleet['price_source']}]")
    print(f"  Start date: {fleet['start_date'].strftime('%Y-%m-%d')}")
    assert fleet["price_path"][0] == fleet["price_usd_mmbtu"]
    assert len(fleet["price_path"]) == 90

    for train_id, days in fleet["by_train"].items():
        print(f"\n-- {train_id} ({len(days)} days) --")
        for window in fleet["resolved_maintenance_by_train"][train_id]:
            print(f"  Maintenance: day {window['start_day']} for {window['duration_days']}d "
                  f"({window['label']}) — lost value ${window['lost_value_usd']:,.0f}")
            assert window["start_day"] is not None

        unplanned = [d for d in days if "Unplanned" in d["status"] and "started" in d["status"]]
        for d in unplanned:
            print(f"  UNPLANNED TRIP: day {d['day']} ({d['date']}) — {d['status']}")
        if not unplanned:
            print("  No unplanned trips this run (probabilistic — rerun with a different seed to see one).")

        availability = calculate_availability(days)
        total = days[-1]["cumulative_mmbtu"]
        print(f"  Availability : {availability*100:.1f}%")
        print(f"  TOTAL over {len(days)} days: {total:,.0f} mmBtu")

    # Sanity: with a single train and default config, going from 1 to 2
    # trains should be a pure data change — prove it here without touching
    # this file.
    print("\n-- Evolvability check: simulate a hypothetical 2nd train --")
    second_train = {**TRAINS[0], "id": "TRAIN-TEST-02", "capacity_mtpa": 3.0}
    fleet2 = run_fleet_forecast(TRAINS + [second_train], horizon_days=10)
    assert set(fleet2["by_train"].keys()) == {TRAINS[0]["id"], "TRAIN-TEST-02"}
    print(f"  OK, {len(fleet2['by_train'])} trains forecast with zero changes to forecast.py "
          f"(even with a horizon too short for the preferred maintenance buffer)")

    print("\nOK")
