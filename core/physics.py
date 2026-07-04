# core/physics.py
# Physical calculations: boil-off, heel, ETA.
# All parameters come from config.py — no magic numbers here.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    LNG_ENERGY_DENSITY_MMBTU_PER_M3,
    BOILOFF_RATE,
    HEEL_FRACTION,
    DAILY_FUEL_CONSUMPTION_MMBTU,
    BOG_TEMP_REFERENCE_CELSIUS,
    BOG_TEMP_SENSITIVITY_PER_5C,
    BOG_WARMUP_PENALTY_MULTIPLIER,
    PRICE_HFO,
)


# ---------------------------------------------------------------------------
# Boil-off
# ---------------------------------------------------------------------------

def calculate_boiloff(cargo_volume_mmbtu, transit_days, vessel_class,
                       ambient_temp_celsius=25.0, heel_was_sufficient=True):
    """
    Calculate boil-off gas (BOG) for a transit leg.

    Returns a dict with:
      gross_bog_mmbtu       : total gas evolved
      bog_used_as_fuel_mmbtu: portion consumed by engines
      volume_delivered_mmbtu: commercial volume at arrival
      bunker_saving_usd     : USD saved by burning BOG instead of HFO
    """
    base_rate = BOILOFF_RATE[vessel_class]

    # Temperature correction
    temp_delta = max(0.0, ambient_temp_celsius - BOG_TEMP_REFERENCE_CELSIUS)
    temp_factor = 1.0 + (temp_delta / 5.0) * BOG_TEMP_SENSITIVITY_PER_5C

    # Warm-up penalty if heel was insufficient
    if not heel_was_sufficient:
        temp_factor *= BOG_WARMUP_PENALTY_MULTIPLIER

    effective_rate = base_rate * temp_factor

    gross_bog = cargo_volume_mmbtu * effective_rate * transit_days

    daily_fuel = DAILY_FUEL_CONSUMPTION_MMBTU[vessel_class]
    engine_demand = daily_fuel * transit_days
    bog_as_fuel = min(gross_bog, engine_demand)

    volume_delivered = cargo_volume_mmbtu - gross_bog
    bunker_saving = bog_as_fuel * PRICE_HFO

    return {
        "gross_bog_mmbtu":        round(gross_bog, 2),
        "bog_used_as_fuel_mmbtu": round(bog_as_fuel, 2),
        "volume_delivered_mmbtu": round(volume_delivered, 2),
        "bunker_saving_usd":      round(bunker_saving, 2),
    }


# ---------------------------------------------------------------------------
# Heel
# ---------------------------------------------------------------------------

def calculate_heel_requirement(vessel_capacity_m3, vessel_class, actual_heel_m3=None):
    """
    Calculate minimum heel requirement and check compliance.

    Returns a dict with:
      required_heel_m3 : minimum heel needed
      actual_heel_m3    : what the vessel retains
      is_sufficient     : True if actual >= required
    """
    fraction = HEEL_FRACTION[vessel_class]
    required_m3 = vessel_capacity_m3 * fraction

    if actual_heel_m3 is None:
        actual_heel_m3 = required_m3

    is_sufficient = actual_heel_m3 >= required_m3

    return {
        "required_heel_m3": round(required_m3, 1),
        "actual_heel_m3":   round(actual_heel_m3, 1),
        "is_sufficient":    is_sufficient,
        "deficit_m3":       round(max(0.0, required_m3 - actual_heel_m3), 1),
    }


# ---------------------------------------------------------------------------
# ETA
# ---------------------------------------------------------------------------

def calculate_eta(departure_date_iso, distance_nm, speed_knots,
                   weather_delay_hours=0.0, canal_delay_hours=0.0):
    """
    Calculate ETA for a transit leg.

    Returns a dict with:
      transit_days : total transit time in days
      eta_iso      : estimated arrival datetime (ISO format)
    """
    from datetime import datetime, timedelta

    transit_hours = distance_nm / speed_knots
    total_hours = transit_hours + weather_delay_hours + canal_delay_hours

    departure = datetime.fromisoformat(departure_date_iso)
    arrival = departure + timedelta(hours=total_hours)

    return {
        "transit_hours": round(total_hours, 2),
        "transit_days":  round(total_hours / 24.0, 3),
        "eta_iso":       arrival.isoformat(timespec="minutes"),
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from data.vessels   import VESSELS
    from data.cargoes   import CARGOES
    from data.terminals import TERMINALS
    from core.routing   import build_route

    print("=== core/physics.py ===")

    vessel = next(v for v in VESSELS if v["id"] == "VESSEL-QF-01")
    cargo  = next(c for c in CARGOES if c["id"] == "LNG-C01")
    terms  = {t["id"]: t for t in TERMINALS}
    route  = build_route(terms[cargo["loading_terminal"]], terms[cargo["discharge_terminal"]])

    print(f"\nVessel: {vessel['id']} ({vessel['vessel_class']})")
    print(f"Cargo:  {cargo['id']} ({cargo['volume_mmbtu']:,} mmBtu)")
    print(f"Route:  {route['origin_id']} -> {route['destination_id']} ({route['distance_nm']:,} nm)")

    # 1. ETA
    eta = calculate_eta(
        departure_date_iso=cargo["laycan_start"],
        distance_nm=route["distance_nm"],
        speed_knots=vessel["speed_knots"],
        weather_delay_hours=route["weather_delay_hours"],
        canal_delay_hours=route["canal_delay_hours"],
    )
    print(f"\n-- ETA --")
    print(f"  Transit days : {eta['transit_days']}")
    print(f"  ETA          : {eta['eta_iso']}")

    # 2. Boil-off over that transit
    bog = calculate_boiloff(
        cargo_volume_mmbtu=cargo["volume_mmbtu"],
        transit_days=eta["transit_days"],
        vessel_class=vessel["vessel_class"],
        ambient_temp_celsius=30.0,
    )
    print(f"\n-- Boil-off --")
    print(f"  Gross BOG        : {bog['gross_bog_mmbtu']:,.0f} mmBtu")
    print(f"  BOG used as fuel : {bog['bog_used_as_fuel_mmbtu']:,.0f} mmBtu")
    print(f"  Volume delivered : {bog['volume_delivered_mmbtu']:,.0f} mmBtu")
    print(f"  Bunker saving    : ${bog['bunker_saving_usd']:,.0f}")

    # 3. Heel
    heel = calculate_heel_requirement(
        vessel_capacity_m3=vessel["capacity_m3"],
        vessel_class=vessel["vessel_class"],
        actual_heel_m3=vessel["current_heel_m3"],
    )
    print(f"\n-- Heel --")
    print(f"  Required heel : {heel['required_heel_m3']:,.0f} m3")
    print(f"  Actual heel   : {heel['actual_heel_m3']:,.0f} m3")
    print(f"  Sufficient    : {heel['is_sufficient']}")

    print("\nOK")
