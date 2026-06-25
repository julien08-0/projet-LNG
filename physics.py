"""
core/scheduling/physics.py
--------------------------
LNG tanker physical constraints and calculations.

Every function here models a real operational constraint that schedulers
deal with daily. The formulas are simplified versus reality (we lack tank
geometry data, real insulation specs, and sea-state sensors) but the
structure and the interdependencies are accurate.

Units convention (enforced throughout):
  - Volumes   : mmBtu  (energy basis, standard commercial unit)
  - Volumes   : m³     (physical tank capacity)
  - Time      : hours  (transit, port stays) or days (boil-off rates)
  - Rates     : % per day (boil-off), $/day (demurrage)
  - Distance  : nautical miles
  - Speed     : knots (nautical miles per hour)
  - Temperature: Celsius
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import math


# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

LNG_ENERGY_DENSITY_MMBTU_PER_M3 = 21.0   # ~21 mmBtu/m³ at -162°C, varies with composition
M3_PER_MMBTU = 1.0 / LNG_ENERGY_DENSITY_MMBTU_PER_M3

# Standard boil-off rates by vessel class (% of total cargo per day)
# Source: industry literature (Gales, LNG Shipping Knowledge, 2009)
# TFDE vessels can re-liquefy BOG — net boil-off is lower
BOILOFF_RATE_BY_CLASS = {
    "Q-Flex": 0.0015,   # 0.15% /day  — modern membrane tanks
    "Q-Max":  0.0015,   # 0.15% /day  — same generation
    "TFDE":   0.0010,   # 0.10% /day  — tri-fuel diesel electric, re-liquefaction capable
    "STEAM":  0.0015,   # 0.15% /day  — older steam turbine vessels
}

# Heel fraction by vessel class (fraction of total capacity, kept post-discharge)
# Keeps tanks at -162°C; prevents thermal shock and mechanical stress on membranes
HEEL_FRACTION_BY_CLASS = {
    "Q-Flex": 0.03,    # 3%
    "Q-Max":  0.03,    # 3%
    "TFDE":   0.04,    # 4% — larger heel for re-liquefaction plant cooling
    "STEAM":  0.05,    # 5% — older insulation, higher thermal losses
}

# Warm-up BOG penalty: if heel was insufficient and tanks partially warmed,
# the first hours of loading consume extra energy cooling down the tank walls.
# Modelled as an additional boil-off multiplier during loading.
WARMUP_BOG_MULTIPLIER = 1.4  # 40% higher BOG rate if tanks are warm


# ---------------------------------------------------------------------------
# Boil-off calculation (BOG = Boil-Off Gas)
# ---------------------------------------------------------------------------

@dataclass
class BoilOffResult:
    """
    Full breakdown of boil-off for a transit leg.

    BOG has a dual role:
      1. It REDUCES the commercial volume delivered to the buyer.
      2. It REPLACES bunker fuel (HFO/LNG) used for propulsion.
    Both effects must be modelled to get the P&L right.
    """
    cargo_volume_start_mmbtu: float    # Volume at departure
    transit_days: float                # Duration of leg
    gross_bog_mmbtu: float             # Total gas evolved (physics)
    bog_used_as_fuel_mmbtu: float      # Portion consumed by engines
    bog_vented_or_reliq_mmbtu: float   # Residual: vented (old ships) or re-liquefied (TFDE)
    volume_delivered_mmbtu: float      # Commercial volume at arrival
    warmup_penalty_applied: bool       # True if tanks were insufficiently cooled
    bunker_cost_saving_usd: float      # USD saved by using BOG instead of HFO


def calculate_boiloff(
    cargo_volume_mmbtu: float,
    transit_days: float,
    vessel_class: str,
    ambient_temp_celsius: float = 25.0,
    sea_state_factor: float = 1.0,
    heel_was_sufficient: bool = True,
    hfo_price_usd_per_mmbtu: float = 12.0,
    daily_fuel_consumption_mmbtu: float = 600.0,
) -> BoilOffResult:
    """
    Calculate boil-off gas (BOG) for a transit leg.

    The base rate is adjusted for:
      - Ambient temperature: warmer climate → faster heat ingress → more BOG
      - Sea state: rough seas → sloshing → accelerated vaporisation
      - Tank warm-up: if previous heel was insufficient

    Args:
        cargo_volume_mmbtu      : Volume loaded (mmBtu)
        transit_days            : Duration of transit (days)
        vessel_class            : One of Q-Flex, Q-Max, TFDE, STEAM
        ambient_temp_celsius     : Average ambient temperature during transit
        sea_state_factor        : 1.0 = calm, 1.2 = moderate, 1.4 = rough
        heel_was_sufficient     : False triggers warm-up BOG penalty
        hfo_price_usd_per_mmbtu : Heavy fuel oil price (for bunker saving calc)
        daily_fuel_consumption_mmbtu: Engine fuel demand per day

    Returns:
        BoilOffResult with full breakdown
    """
    base_rate = BOILOFF_RATE_BY_CLASS.get(vessel_class, 0.0015)

    # Temperature correction: +1% BOG rate per +5°C above 15°C reference
    # Physical basis: Q_in = U * A * (T_ambient - T_LNG); higher T_ambient = more heat ingress
    temp_ref = 15.0
    temp_factor = 1.0 + max(0.0, (ambient_temp_celsius - temp_ref) / 5.0) * 0.01

    # Warm-up penalty: if previous discharge left tanks under-heeled, tank walls
    # partially warm up. Loading cool LNG into a warm tank generates a spike in BOG.
    warmup_applied = False
    if not heel_was_sufficient:
        temp_factor *= WARMUP_BOG_MULTIPLIER
        warmup_applied = True

    effective_rate = base_rate * temp_factor * sea_state_factor

    # Gross BOG = cargo × daily_rate × days
    # Note: cargo decreases daily, so technically this should be exponential decay.
    # For transit legs < 30 days, linear approximation error < 1% — acceptable.
    gross_bog_mmbtu = cargo_volume_mmbtu * effective_rate * transit_days

    # BOG available as fuel: min(gross BOG, engine demand)
    # If BOG > engine demand: excess is re-liquefied (TFDE) or vented (STEAM/older)
    engine_demand_mmbtu = daily_fuel_consumption_mmbtu * transit_days
    bog_as_fuel = min(gross_bog_mmbtu, engine_demand_mmbtu)

    # Residual BOG
    bog_residual = gross_bog_mmbtu - bog_as_fuel

    # Commercial volume at arrival
    volume_delivered = cargo_volume_mmbtu - gross_bog_mmbtu

    # Bunker cost saving: BOG used as fuel replaces HFO at market price
    bunker_saving = bog_as_fuel * hfo_price_usd_per_mmbtu

    return BoilOffResult(
        cargo_volume_start_mmbtu=cargo_volume_mmbtu,
        transit_days=transit_days,
        gross_bog_mmbtu=round(gross_bog_mmbtu, 2),
        bog_used_as_fuel_mmbtu=round(bog_as_fuel, 2),
        bog_vented_or_reliq_mmbtu=round(bog_residual, 2),
        volume_delivered_mmbtu=round(volume_delivered, 2),
        warmup_penalty_applied=warmup_applied,
        bunker_cost_saving_usd=round(bunker_saving, 2),
    )


# ---------------------------------------------------------------------------
# Heel management
# ---------------------------------------------------------------------------

@dataclass
class HeelResult:
    """
    Heel is the LNG volume retained in tanks after discharge.
    It is NOT a commercial volume — the buyer never receives it.

    Purpose:
      1. Keeps tank membranes at -162°C → prevents thermal cycling fatigue
      2. Prevents nitrogen purge cycle (expensive, time-consuming)
      3. Reduces BOG spike at next loading (warm tank = warm-up penalty)
    """
    required_heel_m3: float      # Minimum required to keep tanks cold
    required_heel_mmbtu: float   # Same in energy units
    actual_heel_m3: float        # What the vessel actually retains
    is_sufficient: bool          # True if actual >= required
    deficit_m3: float            # Volume short of requirement (0 if sufficient)
    next_loading_penalty: bool   # True if insufficient → warm-up BOG at next loading


def calculate_heel_requirement(
    vessel_capacity_m3: float,
    vessel_class: str,
    actual_heel_m3: Optional[float] = None,
) -> HeelResult:
    """
    Calculate heel requirement and check compliance.

    Args:
        vessel_capacity_m3  : Total tank capacity of the vessel (m³)
        vessel_class        : Determines required heel fraction
        actual_heel_m3      : What the vessel plans to retain (None = assume exact required)

    Returns:
        HeelResult
    """
    fraction = HEEL_FRACTION_BY_CLASS.get(vessel_class, 0.04)
    required_m3 = vessel_capacity_m3 * fraction
    required_mmbtu = required_m3 * LNG_ENERGY_DENSITY_MMBTU_PER_M3

    if actual_heel_m3 is None:
        actual_heel_m3 = required_m3

    is_sufficient = actual_heel_m3 >= required_m3
    deficit = max(0.0, required_m3 - actual_heel_m3)

    return HeelResult(
        required_heel_m3=round(required_m3, 1),
        required_heel_mmbtu=round(required_mmbtu, 1),
        actual_heel_m3=round(actual_heel_m3, 1),
        is_sufficient=is_sufficient,
        deficit_m3=round(deficit, 1),
        next_loading_penalty=not is_sufficient,
    )


def heel_boiloff_during_ballast(
    heel_volume_m3: float,
    ballast_days: float,
    vessel_class: str,
    ambient_temp_celsius: float = 25.0,
) -> float:
    """
    BOG lost from heel during ballast voyage (vessel travelling empty to load port).

    The heel volume shrinks during the ballast leg due to boil-off.
    If it falls below minimum before arrival, a warm-up penalty is incurred.

    Returns:
        heel_remaining_m3 after ballast transit
    """
    base_rate = BOILOFF_RATE_BY_CLASS.get(vessel_class, 0.0015)
    temp_factor = 1.0 + max(0.0, (ambient_temp_celsius - 15.0) / 5.0) * 0.01
    effective_rate = base_rate * temp_factor

    # BOG rate applied to heel volume (not cargo, heel is the only LNG aboard)
    heel_volume_mmbtu = heel_volume_m3 * LNG_ENERGY_DENSITY_MMBTU_PER_M3
    bog_from_heel = heel_volume_mmbtu * effective_rate * ballast_days
    remaining_mmbtu = max(0.0, heel_volume_mmbtu - bog_from_heel)
    return round(remaining_mmbtu * M3_PER_MMBTU, 1)


# ---------------------------------------------------------------------------
# ETA calculation
# ---------------------------------------------------------------------------

@dataclass
class ETAResult:
    """
    Full ETA breakdown for a vessel transit leg.

    ETA is critical for:
      - Laycan compliance (must arrive in window)
      - Slot booking at discharge terminal
      - Demurrage calculation
    """
    departure_date: str        # ISO format: "2025-01-15T06:00"
    distance_nm: float         # Nautical miles
    speed_knots: float         # Knots
    weather_delay_hours: float # Extra hours from adverse weather
    canal_delay_hours: float   # Extra hours from canal transit (Suez/Panama)
    transit_hours: float       # Pure sailing time (distance / speed)
    total_hours: float         # transit + weather + canal
    transit_days: float        # total_hours / 24  (used in boil-off calc)
    eta_iso: str               # Estimated arrival date/time (ISO format)


def calculate_eta(
    departure_date_iso: str,
    distance_nm: float,
    speed_knots: float,
    weather_delay_hours: float = 0.0,
    canal_delay_hours: float = 0.0,
) -> ETAResult:
    """
    Calculate ETA for a transit leg.

    Speed is assumed constant (no acceleration model). Real schedulers
    use speed instructions from the chartering team — often "eco speed"
    (reduced speed to save fuel) vs "full speed" when behind schedule.

    Args:
        departure_date_iso  : Departure datetime, ISO 8601 format
        distance_nm         : Route distance in nautical miles
        speed_knots         : Vessel speed in knots
        weather_delay_hours : Additional hours from weather routing model
        canal_delay_hours   : Additional hours for Suez / Panama transit + waiting

    Returns:
        ETAResult
    """
    from datetime import datetime, timedelta

    if speed_knots <= 0:
        raise ValueError("Speed must be positive")

    transit_hours = distance_nm / speed_knots
    total_hours = transit_hours + weather_delay_hours + canal_delay_hours
    transit_days = total_hours / 24.0

    departure_dt = datetime.fromisoformat(departure_date_iso)
    arrival_dt = departure_dt + timedelta(hours=total_hours)

    return ETAResult(
        departure_date=departure_date_iso,
        distance_nm=distance_nm,
        speed_knots=speed_knots,
        weather_delay_hours=weather_delay_hours,
        canal_delay_hours=canal_delay_hours,
        transit_hours=round(transit_hours, 2),
        total_hours=round(total_hours, 2),
        transit_days=round(transit_days, 3),
        eta_iso=arrival_dt.isoformat(timespec="minutes"),
    )


# ---------------------------------------------------------------------------
# Laycan compliance
# ---------------------------------------------------------------------------

@dataclass
class LaycanResult:
    """
    Laycan = the contractual loading window (start, end).
    The vessel MUST arrive within this window or financial penalties apply.

    Early arrival: vessel waits at anchor → extra BOG + waiting cost
    Late arrival:  demurrage clock starts → expensive (often $80k-150k/day)
    """
    eta_iso: str
    laycan_start_iso: str
    laycan_end_iso: str
    status: str                    # "ON_TIME", "EARLY", "LATE"
    waiting_hours: float           # Hours waiting at anchor if early (0 if on time / late)
    delay_hours: float             # Hours late (0 if early / on time)
    waiting_bog_loss_mmbtu: float  # BOG lost during anchor wait
    demurrage_risk: bool           # True if late (demurrage may start immediately)


def check_laycan_compliance(
    eta_iso: str,
    laycan_start_iso: str,
    laycan_end_iso: str,
    cargo_volume_mmbtu: float,
    vessel_class: str,
    waiting_bog_rate_multiplier: float = 0.5,
) -> LaycanResult:
    """
    Check whether the vessel ETA falls within the contractual laycan window.

    Args:
        eta_iso                     : Vessel ETA (from calculate_eta)
        laycan_start_iso            : Earliest acceptable arrival
        laycan_end_iso              : Latest acceptable arrival (demurrage trigger)
        cargo_volume_mmbtu          : Cargo aboard (for BOG calculation during wait)
        vessel_class                : For BOG rate lookup
        waiting_bog_rate_multiplier : Anchor BOG is lower than transit BOG (no propulsion)

    Returns:
        LaycanResult
    """
    from datetime import datetime

    eta = datetime.fromisoformat(eta_iso)
    lc_start = datetime.fromisoformat(laycan_start_iso)
    lc_end = datetime.fromisoformat(laycan_end_iso)

    if eta < lc_start:
        status = "EARLY"
        waiting_hours = (lc_start - eta).total_seconds() / 3600.0
        delay_hours = 0.0
    elif eta > lc_end:
        status = "LATE"
        waiting_hours = 0.0
        delay_hours = (eta - lc_end).total_seconds() / 3600.0
    else:
        status = "ON_TIME"
        waiting_hours = 0.0
        delay_hours = 0.0

    # BOG during anchor wait: vessel at anchor, engines on low, reduced BOG rate
    bog_rate_per_day = BOILOFF_RATE_BY_CLASS.get(vessel_class, 0.0015) * waiting_bog_rate_multiplier
    waiting_days = waiting_hours / 24.0
    waiting_bog = cargo_volume_mmbtu * bog_rate_per_day * waiting_days

    return LaycanResult(
        eta_iso=eta_iso,
        laycan_start_iso=laycan_start_iso,
        laycan_end_iso=laycan_end_iso,
        status=status,
        waiting_hours=round(waiting_hours, 2),
        delay_hours=round(delay_hours, 2),
        waiting_bog_loss_mmbtu=round(waiting_bog, 2),
        demurrage_risk=(status == "LATE"),
    )


# ---------------------------------------------------------------------------
# Demurrage calculation
# ---------------------------------------------------------------------------

@dataclass
class DemurrageResult:
    """
    Demurrage = penalty for keeping a vessel at berth beyond the agreed free time.

    Free time (laytime) is negotiated in the charter party.
    Typical: 24-36h at loading terminal, 24h at discharge terminal.
    Typical demurrage rate: $80,000 - $150,000 / day for a Q-Flex.
    """
    allowed_hours: float      # Contractual laytime (free hours at berth)
    actual_hours: float       # Time vessel actually spent at berth
    demurrage_hours: float    # Hours in demurrage (max(0, actual - allowed))
    demurrage_days: float     # demurrage_hours / 24
    demurrage_usd: float      # Financial impact
    on_demurrage: bool        # True if any demurrage accrued


def calculate_demurrage(
    allowed_laytime_hours: float,
    actual_port_hours: float,
    demurrage_rate_usd_per_day: float,
    late_arrival_hours: float = 0.0,
) -> DemurrageResult:
    """
    Calculate demurrage cost for a port call.

    Late arrival does NOT extend the laytime — it just shifts the
    demurrage clock forward. The cargo must still be loaded/discharged
    within the allowed laytime from NOR (Notice of Readiness) tendering.

    Args:
        allowed_laytime_hours       : Free time at berth from charter party
        actual_port_hours           : Actual time from NOR to completion
        demurrage_rate_usd_per_day  : Rate from contract ($/day)
        late_arrival_hours          : Hours vessel arrived late (for alert flagging)

    Returns:
        DemurrageResult
    """
    excess_hours = max(0.0, actual_port_hours - allowed_laytime_hours)
    excess_days = excess_hours / 24.0
    cost = excess_days * demurrage_rate_usd_per_day

    return DemurrageResult(
        allowed_hours=allowed_laytime_hours,
        actual_hours=actual_port_hours,
        demurrage_hours=round(excess_hours, 2),
        demurrage_days=round(excess_days, 4),
        demurrage_usd=round(cost, 2),
        on_demurrage=(excess_hours > 0),
    )


# ---------------------------------------------------------------------------
# Cargo volume: net commercial volume after all deductions
# ---------------------------------------------------------------------------

@dataclass
class CargoVolumeResult:
    """
    Full reconciliation of what was loaded vs what is commercially deliverable.

    This is what the scheduler uses to match contractual obligations:
        net_deliverable = gross_loaded - heel_retained - transit_bog
    """
    gross_loaded_mmbtu: float        # Volume at loading terminal (bill of lading)
    heel_deduction_mmbtu: float      # Heel kept aboard (non-commercial)
    transit_bog_mmbtu: float         # BOG lost in transit
    waiting_bog_mmbtu: float         # BOG lost while waiting at anchor
    net_deliverable_mmbtu: float     # What arrives at discharge terminal
    contractual_quantity_mmbtu: float # What the buyer expects
    quantity_shortfall_mmbtu: float  # max(0, contractual - deliverable)
    quantity_surplus_mmbtu: float    # max(0, deliverable - contractual)


def reconcile_cargo_volume(
    gross_loaded_mmbtu: float,
    heel_mmbtu: float,
    transit_bog: BoilOffResult,
    waiting_bog_mmbtu: float,
    contractual_quantity_mmbtu: float,
) -> CargoVolumeResult:
    """
    Reconcile all volume deductions to get the net deliverable quantity.

    In real operations this is done via custody transfer metering at the
    loading terminal (CTMS) and confirmed at the discharge terminal.
    Disputes over quantity are a major source of commercial tension.

    Args:
        gross_loaded_mmbtu          : Volume from loading terminal meter
        heel_mmbtu                  : Heel retained (from HeelResult)
        transit_bog                 : Full BOG result from calculate_boiloff()
        waiting_bog_mmbtu           : BOG from laycan wait at anchor
        contractual_quantity_mmbtu  : Volume the buyer contracted to receive

    Returns:
        CargoVolumeResult
    """
    total_deductions = heel_mmbtu + transit_bog.gross_bog_mmbtu + waiting_bog_mmbtu
    net = gross_loaded_mmbtu - total_deductions

    shortfall = max(0.0, contractual_quantity_mmbtu - net)
    surplus = max(0.0, net - contractual_quantity_mmbtu)

    return CargoVolumeResult(
        gross_loaded_mmbtu=round(gross_loaded_mmbtu, 2),
        heel_deduction_mmbtu=round(heel_mmbtu, 2),
        transit_bog_mmbtu=round(transit_bog.gross_bog_mmbtu, 2),
        waiting_bog_mmbtu=round(waiting_bog_mmbtu, 2),
        net_deliverable_mmbtu=round(net, 2),
        contractual_quantity_mmbtu=round(contractual_quantity_mmbtu, 2),
        quantity_shortfall_mmbtu=round(shortfall, 2),
        quantity_surplus_mmbtu=round(surplus, 2),
    )


# ---------------------------------------------------------------------------
# Draft compliance
# ---------------------------------------------------------------------------

def check_draft_compatibility(vessel_class: str, terminal_max_draft_m: float) -> dict:
    """
    Check whether a vessel class can physically berth at a terminal.

    Max draft = maximum water depth required for the vessel to berth safely.
    If the terminal's channel or berth is shallower than the vessel's draft,
    the vessel cannot berth — full stop. This is a hard constraint.

    Typical drafts (laden, at maximum cargo):
        STEAM  : ~11.5m
        TFDE   : ~11.5m
        Q-Flex : ~12.0m
        Q-Max  : ~12.5m  (cannot enter most terminals — only Ras Laffan, Sabetta)

    Args:
        vessel_class          : One of Q-Flex, Q-Max, TFDE, STEAM
        terminal_max_draft_m  : Maximum draft allowed at the terminal (meters)

    Returns:
        dict with keys: compatible (bool), vessel_draft_m, shortfall_m
    """
    vessel_drafts = {
        "Q-Max":  12.5,
        "Q-Flex": 12.0,
        "TFDE":   11.5,
        "STEAM":  11.5,
    }
    vessel_draft = vessel_drafts.get(vessel_class, 12.0)
    compatible = vessel_draft <= terminal_max_draft_m
    shortfall = max(0.0, vessel_draft - terminal_max_draft_m)

    return {
        "compatible": compatible,
        "vessel_class": vessel_class,
        "vessel_draft_m": vessel_draft,
        "terminal_max_draft_m": terminal_max_draft_m,
        "shortfall_m": round(shortfall, 2),
        "alert": None if compatible else (
            f"{vessel_class} draft {vessel_draft}m exceeds terminal max {terminal_max_draft_m}m "
            f"(shortfall: {shortfall:.1f}m) — vessel CANNOT berth"
        ),
    }
