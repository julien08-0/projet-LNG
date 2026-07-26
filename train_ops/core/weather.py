# train_ops/core/weather.py
# Ambient temperature at a production site — drives the derating factor
# in core/performance.py.
#
# Open-Meteo gives real daily forecasts for ~16 days out (free, no API
# key). Beyond that horizon nothing free is reliable, so days past the
# live window use a monthly climatological average instead — same
# "don't fabricate the unknown" stance the main project takes with spot
# prices (core/spot.py never lets a decision see tomorrow's price either).

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import timedelta
import requests

from train_ops.config import WEATHER_LIVE_FORECAST_DAYS, SEASONAL_AVG_TEMP_C_BY_MONTH

OPEN_METEO_ENDPOINT = "https://api.open-meteo.com/v1/forecast"


def get_temperature_forecast(lat, lon, start_date, horizon_days, use_live=True):
    """
    List of {day, date, temp_c, source} for `horizon_days` days starting
    at `start_date` (a datetime). Real Open-Meteo forecast for the days it
    actually covers, monthly seasonal average for the rest.
    """
    live_days = min(horizon_days, WEATHER_LIVE_FORECAST_DAYS)
    live_temps = {}

    if use_live and live_days > 0:
        try:
            resp = requests.get(OPEN_METEO_ENDPOINT, params={
                "latitude": lat, "longitude": lon,
                "daily": "temperature_2m_mean",
                "forecast_days": live_days,
                "timezone": "auto",
            }, timeout=5)
            resp.raise_for_status()
            daily = resp.json()["daily"]
            for date_str, temp in zip(daily["time"], daily["temperature_2m_mean"]):
                if temp is not None:
                    live_temps[date_str] = float(temp)
        except Exception:
            pass   # falls through to seasonal average for every day below

    forecast = []
    for day in range(horizon_days):
        date = start_date + timedelta(days=day)
        date_str = date.strftime("%Y-%m-%d")
        if date_str in live_temps:
            forecast.append({"day": day, "date": date_str,
                              "temp_c": round(live_temps[date_str], 1),
                              "source": "live (open-meteo)"})
        else:
            forecast.append({"day": day, "date": date_str,
                              "temp_c": SEASONAL_AVG_TEMP_C_BY_MONTH[date.month],
                              "source": "seasonal average (fallback)"})

    return forecast


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from datetime import datetime

    print("=== train_ops/core/weather.py ===")
    print("  (anchored on real today — this module is forward-looking, unlike")
    print("   the cargo-scheduling side which fixes a reproducible March 2025.)")

    ras_laffan = (25.90, 51.55)
    start = datetime.now()

    print("\n-- Live attempt, 20-day horizon (16 real + 4 seasonal fallback) --")
    forecast = get_temperature_forecast(*ras_laffan, start, horizon_days=20, use_live=True)
    for f in forecast:
        print(f"  day {f['day']:>2} {f['date']}  {f['temp_c']:>5.1f}C  [{f['source']}]")

    live_count = sum(1 for f in forecast if "live" in f["source"])
    fallback_count = sum(1 for f in forecast if "fallback" in f["source"])
    print(f"\n  Live days: {live_count}  Fallback days: {fallback_count}")
    assert live_count + fallback_count == 20

    print("\n-- Offline (use_live=False) — should be 100% seasonal fallback --")
    forecast_offline = get_temperature_forecast(*ras_laffan, start, horizon_days=10, use_live=False)
    assert all("fallback" in f["source"] for f in forecast_offline)
    print("  OK, all fallback")

    print("\nOK")
