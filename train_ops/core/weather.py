# train_ops/core/weather.py
# Ambient temperature at a production site — drives the derating factor
# in core/performance.py.
#
# Open-Meteo's free forecast API gives real daily forecasts for ~16 days
# out. That's a real forecasting-skill limit, not an arbitrary cutoff: no
# weather model, free or paid, can reliably predict a specific day's
# temperature 90 days ahead — the atmosphere just isn't predictable that
# far out. So "Live weather" ON does NOT fall back to a synthetic monthly
# average beyond day 16 — it uses Open-Meteo's HISTORICAL archive instead,
# fetching the actually-measured temperature at this site on the same
# calendar day one year earlier. That's real, observed data for every day
# of the horizon, not a guess — just not a *forecast* beyond day 16,
# because no forecast that far out can honestly exist.
# "Live weather" OFF skips all network calls and uses the static monthly
# climatological table for every day instead (same "don't fabricate the
# unknown" stance the main project takes with spot prices).

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import timedelta
import requests

from train_ops.config import WEATHER_LIVE_FORECAST_DAYS, SEASONAL_AVG_TEMP_C_BY_MONTH

OPEN_METEO_FORECAST_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE_ENDPOINT  = "https://archive-api.open-meteo.com/v1/archive"


def _same_day_last_year(date):
    """Same calendar day one year earlier. Feb 29 -> Feb 28 (no Feb 29 in
    a non-leap prior year)."""
    try:
        return date.replace(year=date.year - 1)
    except ValueError:
        return date.replace(year=date.year - 1, day=28)


def _fetch_daily_temps(endpoint, lat, lon, start_date, end_date):
    """One batched call -> {date_str: temp_c}. Empty dict on any failure
    (network, rate limit, bad response) — callers fall back to the
    seasonal table, this never raises."""
    try:
        resp = requests.get(endpoint, params={
            "latitude": lat, "longitude": lon,
            "daily": "temperature_2m_mean",
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "timezone": "auto",
        }, timeout=5)
        resp.raise_for_status()
        daily = resp.json()["daily"]
        return {d: float(t) for d, t in zip(daily["time"], daily["temperature_2m_mean"]) if t is not None}
    except Exception:
        return {}


def get_temperature_forecast(lat, lon, start_date, horizon_days, use_live=True):
    """
    List of {day, date, temp_c, source} for `horizon_days` days starting
    at `start_date` (a datetime).

    use_live=True: day 0..WEATHER_LIVE_FORECAST_DAYS-1 use the real
    Open-Meteo forecast; every day beyond that uses the real Open-Meteo
    HISTORICAL temperature for the same calendar day one year earlier at
    this site (one batched archive call for the whole remainder) — so the
    entire horizon runs on measured data, not a synthetic average. Only
    falls back to the monthly seasonal table for a specific day if the
    relevant API call itself fails.

    use_live=False: every day uses the static monthly seasonal average,
    no network calls at all.
    """
    if not use_live:
        forecast = []
        for day in range(horizon_days):
            date = start_date + timedelta(days=day)
            forecast.append({"day": day, "date": date.strftime("%Y-%m-%d"),
                              "temp_c": SEASONAL_AVG_TEMP_C_BY_MONTH[date.month],
                              "source": "seasonal average (offline)"})
        return forecast

    live_days = min(horizon_days, WEATHER_LIVE_FORECAST_DAYS)
    live_temps = {}
    if live_days > 0:
        live_end = start_date + timedelta(days=live_days - 1)
        live_temps = _fetch_daily_temps(OPEN_METEO_FORECAST_ENDPOINT, lat, lon, start_date, live_end)

    # Historical leg: same calendar days one year earlier, one batched call
    # covering the whole remainder of the horizon.
    historical_temps = {}
    if horizon_days > live_days:
        hist_start = _same_day_last_year(start_date + timedelta(days=live_days))
        hist_end   = _same_day_last_year(start_date + timedelta(days=horizon_days - 1))
        historical_temps = _fetch_daily_temps(OPEN_METEO_ARCHIVE_ENDPOINT, lat, lon, hist_start, hist_end)

    forecast = []
    for day in range(horizon_days):
        date = start_date + timedelta(days=day)
        date_str = date.strftime("%Y-%m-%d")

        if date_str in live_temps:
            forecast.append({"day": day, "date": date_str,
                              "temp_c": round(live_temps[date_str], 1),
                              "source": "live forecast (open-meteo)"})
            continue

        hist_date_str = _same_day_last_year(date).strftime("%Y-%m-%d")
        if hist_date_str in historical_temps:
            forecast.append({"day": day, "date": date_str,
                              "temp_c": round(historical_temps[hist_date_str], 1),
                              "source": "historical, same day last year (open-meteo)"})
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

    print("\n-- Live weather, 20-day horizon (16 real forecast + 4 historical) --")
    forecast = get_temperature_forecast(*ras_laffan, start, horizon_days=20, use_live=True)
    for f in forecast:
        print(f"  day {f['day']:>2} {f['date']}  {f['temp_c']:>5.1f}C  [{f['source']}]")

    live_count     = sum(1 for f in forecast if "live forecast" in f["source"])
    hist_count     = sum(1 for f in forecast if "historical" in f["source"])
    fallback_count = sum(1 for f in forecast if "fallback" in f["source"])
    print(f"\n  Live forecast days: {live_count}  Historical days: {hist_count}  Fallback days: {fallback_count}")
    assert live_count + hist_count + fallback_count == 20

    print("\n-- Offline (use_live=False) — should be 100% seasonal average --")
    forecast_offline = get_temperature_forecast(*ras_laffan, start, horizon_days=10, use_live=False)
    assert all("offline" in f["source"] for f in forecast_offline)
    print("  OK, all offline/seasonal")

    print("\nOK")
