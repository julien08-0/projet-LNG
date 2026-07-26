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

from datetime import datetime

from data.terminals import TERMINALS
from core.market     import get_ttf_price

from train_ops.config           import FORECAST_HORIZON_DAYS
from train_ops.core.weather     import get_temperature_forecast
from train_ops.core.performance import calculate_daily_production

TERMINALS_BY_ID = {t["id"]: t for t in TERMINALS}


def simulate_train_forecast(train, start_date, horizon_days, price_usd_mmbtu, use_live_weather=True):
    """
    Day-by-day production for ONE train. Pure function of its inputs — the
    fleet-level runner below just calls this once per train in TRAINS, so
    going from 1 train to N is a loop, not a rewrite.
    """
    terminal = TERMINALS_BY_ID[train["terminal_id"]]
    weather  = get_temperature_forecast(terminal["lat"], terminal["lon"], start_date, horizon_days, use_live_weather)

    days = []
    cumulative = 0.0
    for w in weather:
        result = calculate_daily_production(train, w["day"], w["temp_c"], price_usd_mmbtu)
        cumulative += result["produced_mmbtu"]
        days.append({
            **result,
            "date":              w["date"],
            "weather_source":    w["source"],
            "cumulative_mmbtu":  cumulative,
        })
    return days


def run_fleet_forecast(trains, horizon_days=FORECAST_HORIZON_DAYS, use_live_weather=True, use_live_price=False):
    """
    Forecast for every train in `trains` (normally train_ops.data.trains.TRAINS),
    sharing one TTF price fetched once so every train's load-factor decision
    is priced consistently, same principle as core.pnl fetching one market
    snapshot per batch instead of re-pricing per candidate.
    """
    start_date = datetime.now()
    price = get_ttf_price(use_live_price)

    by_train = {
        train["id"]: simulate_train_forecast(train, start_date, horizon_days,
                                              price["price_usd_mmbtu"], use_live_weather)
        for train in trains
    }

    return {
        "start_date":       start_date,
        "price_usd_mmbtu":  price["price_usd_mmbtu"],
        "price_source":     price["source"],
        "by_train":         by_train,
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from train_ops.data.trains import TRAINS

    print("=== train_ops/core/forecast.py ===")

    fleet = run_fleet_forecast(TRAINS, horizon_days=60)
    print(f"\n  Price used: ${fleet['price_usd_mmbtu']}/mmBtu  [{fleet['price_source']}]")
    print(f"  Start date: {fleet['start_date'].strftime('%Y-%m-%d')}")

    for train_id, days in fleet["by_train"].items():
        print(f"\n-- {train_id} (first 5 + last 5 of {len(days)} days) --")
        for d in days[:5] + days[-5:]:
            print(f"  day {d['day']:>2} {d['date']}  {d['ambient_temp_c']:>5.1f}C  "
                  f"produced={d['produced_mmbtu']:>9,.0f}  cumulative={d['cumulative_mmbtu']:>12,.0f}  "
                  f"[{d['status']}]")
        total = days[-1]["cumulative_mmbtu"]
        print(f"  TOTAL over {len(days)} days: {total:,.0f} mmBtu")

    # Sanity: with a single train and default config, going from 1 to 2
    # trains should be a pure data change — prove it here without touching
    # this file.
    print("\n-- Evolvability check: simulate a hypothetical 2nd train --")
    second_train = {**TRAINS[0], "id": "TRAIN-TEST-02", "capacity_mtpa": 3.0}
    fleet2 = run_fleet_forecast(TRAINS + [second_train], horizon_days=10)
    assert set(fleet2["by_train"].keys()) == {TRAINS[0]["id"], "TRAIN-TEST-02"}
    print(f"  OK, {len(fleet2['by_train'])} trains forecast with zero changes to forecast.py")

    print("\nOK")
