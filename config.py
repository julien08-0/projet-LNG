# config.py
# Single source of truth for all parameters.
# No logic, no imports, just values.

# ---------------------------------------------------------------------------
# Physical — LNG properties
# ---------------------------------------------------------------------------

LNG_ENERGY_DENSITY_MMBTU_PER_M3 = 21.0   # mmBtu per m³ at -162°C
LNG_BOILING_POINT_CELSIUS        = -162.0

# ---------------------------------------------------------------------------
# Boil-off rates by vessel class (fraction of cargo per day)
# ---------------------------------------------------------------------------

BOILOFF_RATE = {
    "Q-Max":  0.00150,   # 0.150% /day
    "Q-Flex": 0.00150,   # 0.150% /day
    "TFDE":   0.00100,   # 0.100% /day — re-liquefaction capable
    "STEAM":  0.00150,   # 0.150% /day — older vessels
}

# ---------------------------------------------------------------------------
# Heel fractions by vessel class (fraction of total capacity, non-commercial)
# ---------------------------------------------------------------------------

HEEL_FRACTION = {
    "Q-Max":  0.030,   # 3%
    "Q-Flex": 0.030,   # 3%
    "TFDE":   0.040,   # 4%
    "STEAM":  0.050,   # 5%
}

# ---------------------------------------------------------------------------
# Max draft by vessel class (meters, laden)
# ---------------------------------------------------------------------------

MAX_DRAFT_M = {
    "Q-Max":  12.5,
    "Q-Flex": 12.0,
    "TFDE":   11.5,
    "STEAM":  11.5,
}

# ---------------------------------------------------------------------------
# Daily fuel consumption by vessel class (mmBtu/day)
# ---------------------------------------------------------------------------

DAILY_FUEL_CONSUMPTION_MMBTU = {
    "Q-Max":  700.0,
    "Q-Flex": 650.0,
    "TFDE":   580.0,
    "STEAM":  750.0,
}

# ---------------------------------------------------------------------------
# Boil-off corrections
# ---------------------------------------------------------------------------

BOG_TEMP_REFERENCE_CELSIUS    = 15.0   # baseline temperature
BOG_TEMP_SENSITIVITY_PER_5C   = 0.01   # +1% BOG rate per +5°C above reference
BOG_WARMUP_PENALTY_MULTIPLIER = 1.40   # +40% BOG if tanks insufficiently cooled
BOG_ANCHOR_RATE_FRACTION      = 0.50   # BOG rate at anchor vs underway

# ---------------------------------------------------------------------------
# Market prices (USD/mmBtu) — indicative Q1 2025
# ---------------------------------------------------------------------------

PRICE_JKM = 11.50   # Japan/Korea Marker (Asian spot)
PRICE_TTF = 10.80   # Title Transfer Facility (European spot)
PRICE_HH  =  2.40   # Henry Hub (US benchmark)
PRICE_HFO = 12.00   # Heavy fuel oil equivalent (bunker saving calc)

# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

DEFAULT_LAYTIME_LOADING_HOURS   = 24.0   # Free berth time at load port
DEFAULT_LAYTIME_DISCHARGE_HOURS = 24.0   # Free berth time at discharge port
DEFAULT_SPEED_KNOTS             = 17.0   # Planning speed (eco)
FULL_SPEED_KNOTS                = 19.0   # Catch-up speed after disruption

DEMURRAGE_RATE = {
    "Q-Max":  150_000,
    "Q-Flex": 120_000,
    "TFDE":    95_000,
    "STEAM":   80_000,
}

# ---------------------------------------------------------------------------
# Canal parameters
# ---------------------------------------------------------------------------

SUEZ_TRANSIT_HOURS   = 16.0
SUEZ_TOLL_USD        = 600_000

PANAMA_TRANSIT_HOURS = 24.0
PANAMA_TOLL_USD      = 350_000


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== config.py ===")

    print("\n-- Boil-off rates --")
    for cls, rate in BOILOFF_RATE.items():
        print(f"  {cls:<8} {rate*100:.3f}% /day")

    print("\n-- Heel fractions --")
    for cls, frac in HEEL_FRACTION.items():
        print(f"  {cls:<8} {frac*100:.1f}%")

    print("\n-- Max draft --")
    for cls, draft in MAX_DRAFT_M.items():
        print(f"  {cls:<8} {draft}m")

    print("\n-- Market prices --")
    print(f"  JKM : ${PRICE_JKM}/mmBtu")
    print(f"  TTF : ${PRICE_TTF}/mmBtu")
    print(f"  HH  : ${PRICE_HH}/mmBtu")
    print(f"  HFO : ${PRICE_HFO}/mmBtu")

    print("\n-- Demurrage rates --")
    for cls, rate in DEMURRAGE_RATE.items():
        print(f"  {cls:<8} ${rate:,.0f}/day")

    print("\n-- Canals --")
    print(f"  Suez   : {SUEZ_TRANSIT_HOURS}h  ${SUEZ_TOLL_USD:,.0f}")
    print(f"  Panama : {PANAMA_TRANSIT_HOURS}h  ${PANAMA_TOLL_USD:,.0f}")

    print("\nOK")
