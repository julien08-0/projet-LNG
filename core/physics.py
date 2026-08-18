# core/physics.py
# Physical calculations: boil-off, heel, ETA.
# All parameters come from config.py — no magic numbers here.

import sys
import os
import math
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
# Demurrage
# ---------------------------------------------------------------------------

def calculate_demurrage(delay_hours, daily_rate_usd):
    """
    Calculate demurrage cost for hours spent late against a laycan.

    daily_rate_usd is the rate to apply — typically the cargo's own
    contractual demurrage_rate_usd_day, falling back to config.DEMURRAGE_RATE
    by vessel class when no contract-specific rate is available.

    Returns a dict with:
      demurrage_days : delay expressed in days
      demurrage_usd  : total demurrage cost
    """
    demurrage_days = delay_hours / 24.0
    demurrage_usd = demurrage_days * daily_rate_usd

    return {
        "demurrage_days": round(demurrage_days, 3),
        "demurrage_usd":  round(demurrage_usd, 2),
    }


# ---------------------------------------------------------------------------
# Boil-off
# ---------------------------------------------------------------------------

def calculate_boiloff(cargo_volume_mmbtu, transit_days, vessel_class,
                       ambient_temp_celsius=25.0, heel_was_sufficient=True):
    """
    Calculate boil-off gas (BOG) for a transit leg.

    Exponential decay, not linear: the gas that evaporates is a fraction of
    what's still IN the tank, not of the original load — the same reason
    radioactive decay or drug elimination is exponential, not linear. A
    linear model (volume_initial x rate x days) overstates the loss on
    long transits, since it keeps "charging" the daily rate against gas
    that has already boiled off. Negligible difference under ~10 days;
    increasingly wrong beyond 30 (this project's other long legs — the
    big spot-market ballasts to Sabine Pass — are exactly where it
    mattered enough to fix).

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

    volume_delivered = cargo_volume_mmbtu * math.exp(-effective_rate * transit_days)
    gross_bog = cargo_volume_mmbtu - volume_delivered

    daily_fuel = DAILY_FUEL_CONSUMPTION_MMBTU[vessel_class]
    engine_demand = daily_fuel * transit_days
    bog_as_fuel = min(gross_bog, engine_demand)

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

def calculate_heel_requirement(vessel_capacity_m3, vessel_class, actual_heel_m3=None,
                                ballast_days=0.0, ambient_temp_celsius=25.0):
    """
    Calculate minimum heel requirement and check compliance.

    HEEL_FRACTION (config.py) is the heel a vessel needs to still HAVE on
    arrival — not what it needs to leave with. The heel boils off during
    the ballast leg exactly like cargo does (same LNG, same tanks), so a
    long ballast erodes it. ballast_days=0 (the default) reduces to the
    original flat-fraction behavior; pass the actual ballast leg length to
    size the heel a vessel must carry AT DEPARTURE so the base fraction is
    still there when it arrives to load.

    Returns a dict with:
      required_heel_m3 : minimum heel needed at departure
      actual_heel_m3    : what the vessel retains
      is_sufficient     : True if actual >= required
      erosion_m3        : how much of the departure heel boils off over
                           ballast_days (0 if ballast_days=0)
    """
    fraction = HEEL_FRACTION[vessel_class]
    base_required_m3 = vessel_capacity_m3 * fraction

    if ballast_days > 0:
        # Same physics as calculate_boiloff, applied to the heel volume
        # itself: how much heel survives ballast_days of erosion, and so
        # how much more you must depart with to still have base_required_m3
        # left on arrival.
        retention = calculate_boiloff(base_required_m3, ballast_days, vessel_class,
                                       ambient_temp_celsius)["volume_delivered_mmbtu"] / base_required_m3
        required_m3 = base_required_m3 / retention
        erosion_m3 = required_m3 - base_required_m3
    else:
        required_m3 = base_required_m3
        erosion_m3 = 0.0

    if actual_heel_m3 is None:
        actual_heel_m3 = required_m3

    is_sufficient = actual_heel_m3 >= required_m3

    return {
        "required_heel_m3": round(required_m3, 1),
        "actual_heel_m3":   round(actual_heel_m3, 1),
        "is_sufficient":    is_sufficient,
        "deficit_m3":       round(max(0.0, required_m3 - actual_heel_m3), 1),
        "erosion_m3":       round(erosion_m3, 1),
    }


def calculate_heel_remaining(current_heel_m3, vessel_class, days_elapsed, ambient_temp_celsius=25.0):
    """
    How much heel is left after days_elapsed of ballast erosion — used to
    animate the fill level during the ballast leg (ui/map.py) instead of
    treating heel as a flat floor the whole time it's aboard.
    """
    if days_elapsed <= 0 or current_heel_m3 <= 0:
        return current_heel_m3
    retained_fraction = calculate_boiloff(
        current_heel_m3, days_elapsed, vessel_class, ambient_temp_celsius
    )["volume_delivered_mmbtu"] / current_heel_m3
    return current_heel_m3 * retained_fraction


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

    vessel = next(v for v in VESSELS if v["id"] == "VESSEL-QF-02")
    cargo  = next(c for c in CARGOES if c["id"] == "LNG-C03")
    terms  = {t["id"]: t for t in TERMINALS}
    route  = build_route(terms[cargo["loading_terminal"]], terms[cargo["discharge_terminal"]])

    print(f"\nVessel: {vessel['id']} ({vessel['vessel_class']})")
    print(f"Cargo:  {cargo['id']} ({cargo['volume_mmbtu']:,} mmBtu)")
    print(f"Route:  {route['origin_id']} -> {route['destination_id']} ({route['distance_nm']:,} nm)")

    # 1. ETA
    eta = calculate_eta(
        departure_date_iso=cargo["laycan_start"],
        distance_nm=route["distance_nm"],
        speed_knots=vessel["laden_speed_knots"],
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
    print(f"\n-- Heel (no ballast, flat fraction) --")
    print(f"  Required heel : {heel['required_heel_m3']:,.0f} m3")
    print(f"  Actual heel   : {heel['actual_heel_m3']:,.0f} m3")
    print(f"  Sufficient    : {heel['is_sufficient']}")

    print(f"\n-- Heel requirement vs ballast duration ({vessel['vessel_class']}) --")
    for ballast_days in [0, 5, 15, 25]:
        h = calculate_heel_requirement(vessel["capacity_m3"], vessel["vessel_class"], ballast_days=ballast_days)
        print(f"  {ballast_days:>2}d ballast -> required {h['required_heel_m3']:>8,.0f} m3 "
              f"(+{h['erosion_m3']:>6,.0f} m3 vs flat fraction)")

    print(f"\n-- Heel erosion over an actual ballast leg --")
    heel_m3 = vessel["current_heel_m3"]
    for days in [0, 5, 10, 20]:
        remaining = calculate_heel_remaining(heel_m3, vessel["vessel_class"], days)
        print(f"  day {days:>2}: {remaining:>8,.0f} m3 remaining (started with {heel_m3:,.0f})")
    assert calculate_heel_remaining(heel_m3, vessel["vessel_class"], 0) == heel_m3
    assert calculate_heel_remaining(heel_m3, vessel["vessel_class"], 20) < heel_m3

    print(f"\n-- Exponential vs linear sanity check (long transit) --")
    # ambient = reference temp -> temp_factor is exactly 1.0, so both sides
    # use the identical base rate and the comparison isolates linear-vs-
    # exponential, not an accidental side effect of the temperature term.
    bog_30d = calculate_boiloff(3_000_000, 30, "TFDE", ambient_temp_celsius=BOG_TEMP_REFERENCE_CELSIUS)
    linear_equivalent = 3_000_000 * BOILOFF_RATE["TFDE"] * 30
    print(f"  Exponential gross BOG (30d) : {bog_30d['gross_bog_mmbtu']:,.0f} mmBtu")
    print(f"  Naive linear equivalent     : {linear_equivalent:,.0f} mmBtu")
    assert bog_30d["gross_bog_mmbtu"] < linear_equivalent, "exponential must lose less than naive linear"

    # 4. Demurrage
    demurrage = calculate_demurrage(delay_hours=30.0, daily_rate_usd=cargo["demurrage_rate_usd_day"])
    print(f"\n-- Demurrage --")
    print(f"  Delay          : 30.0h ({demurrage['demurrage_days']} days)")
    print(f"  Rate           : ${cargo['demurrage_rate_usd_day']:,.0f}/day")
    print(f"  Demurrage cost : ${demurrage['demurrage_usd']:,.0f}")

    print("\nOK")
