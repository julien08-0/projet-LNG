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

PRICE_TTF = 10.80   # Title Transfer Facility (European spot)
PRICE_HH  =  2.40   # Henry Hub (US benchmark)
PRICE_HFO = 12.00   # Heavy fuel oil equivalent (bunker saving calc)
PRICE_BRENT = 78.00 # $/bbl — informational only, not consumed by core/pnl.py yet

ASIAN_SPREAD_USD_MMBTU = 0.70   # JKM = TTF + spread (core/market.py)
PRICE_JKM = PRICE_TTF + ASIAN_SPREAD_USD_MMBTU   # Japan/Korea Marker (Asian spot)

# Static fallback FX rates (USD -> quote currency). Informational only —
# nothing in core/pnl.py converts currency yet.
FX_RATE_USD_TO = {
    "EUR": 0.92,
    "JPY": 149.00,
}

# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

DEFAULT_LAYTIME_LOADING_HOURS   = 24.0   # Free berth time at load port
DEFAULT_LAYTIME_DISCHARGE_HOURS = 24.0   # Free berth time at discharge port

# Ballast (empty) vs laden (loaded) speed — a ship rides higher and meets
# less resistance empty, so ballast speed is a bit faster in practice.
# BALLAST_SPEED_BONUS_KNOTS is the default gap used when a vessel is added
# via Fleet Management (only laden speed is asked for there); vessels in
# data/vessels.py carry both explicitly.
DEFAULT_LADEN_SPEED_KNOTS   = 17.0   # Planning speed (eco), loaded
BALLAST_SPEED_BONUS_KNOTS   = 0.5
DEFAULT_BALLAST_SPEED_KNOTS = DEFAULT_LADEN_SPEED_KNOTS + BALLAST_SPEED_BONUS_KNOTS
FULL_SPEED_KNOTS            = 19.0   # Catch-up speed after disruption

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
# Weather delay — core/routing.py used to add a single flat constant per
# route branch (every Gulf->Europe voyage got the identical +18h, forever).
# Real weather varies leg to leg. Reproducible per route instead of a live
# marine-weather feed (a full route spans many waypoints over many transit
# days — not the single fixed point train_ops/core/weather.py can query):
# each (origin, destination, branch) draws its own value, seeded so it's
# stable within a run rather than jittering on every rerun.
# ---------------------------------------------------------------------------

WEATHER_DELAY_VOLATILITY_FRACTION = 0.30   # +/-30% around the base estimate
WEATHER_DELAY_SEED                = 11

# ---------------------------------------------------------------------------
# Market price marker by terminal (for P&L / destination choice, and for
# core/spot.py's regional buy/sell prices). Live/fallback price resolution
# lives in core/market.py, not here.
#
# Loading terminals are included too (RAS-LAFFAN, SABINE-PASS) — they only
# matter for core/spot.py, which needs a "buy" price on the loading side.
# core/pnl.py only ever looks up the destination terminal, so adding these
# is additive and doesn't change existing contract P&L.
# ---------------------------------------------------------------------------

TERMINAL_PRICE_MARKER = {
    "FUTTSU":         "JKM",
    "ZEEBRUGGE":      "TTF",
    "GATE-ROTTERDAM": "TTF",
    "AL-ZOUR":        "JKM",   # no dedicated MENA marker modeled — Asia/MENA proxy
    "RAS-LAFFAN":     "JKM",   # Qatari cargoes commonly netback-priced off Asian benchmarks
    "SABINE-PASS":    "HH",    # standard US LNG feedgas indexation (HH + liquefaction fee)
}

# ---------------------------------------------------------------------------
# Spot market simulation (core/spot.py) — daily regional price paths and
# the opportunistic dispatch decision.
# ---------------------------------------------------------------------------

# Shared by ui/map.py (day slider range) and ui/spot.py (simulation window +
# price chart) — the two MUST agree, otherwise the map can show a vessel
# still mid-voyage on the last visible day while the Trade Log already
# reports that same voyage as fully settled (realized price, GAIN/LOSS).
# 90 days, not 46: real-routed ballast + laden legs on a long haul (e.g.
# Sabine Pass <-> Futtsu, ~25-30 days each way) can settle past day 60 —
# the window has to comfortably outlast the longest voyage it dispatches,
# not just the shortest.
SPOT_HORIZON_DAYS = 90

# Daily volatility of each regional benchmark, as a fraction of price
# (e.g. 0.02 = 2%/day standard deviation of the daily log-return). Applied
# as a bounded random walk seeded by SPOT_PRICE_SEED — same seed, same
# price path, every run (reproducible for demos and tests).
SPOT_DAILY_VOLATILITY = {
    "JKM": 0.030,
    "TTF": 0.030,
    "HH":  0.050,   # HH is historically more volatile than the LNG spot markers
}
SPOT_PRICE_SEED = 2650   # picked because it produces both wins and a loss
                          # over the 46-day horizon on the current fleet/cargo
                          # data — demonstrates the risk this module exists to
                          # show. The HH->JKM spread is structurally so wide
                          # (cheap US feedgas vs. Asian LNG) that a realized
                          # loss is rare even with realistic volatility — most
                          # seeds land 5/5 wins with a smaller-than-expected
                          # margin (the real risk this module is built to
                          # surface), not a sign flip. Re-pick if the price
                          # anchors, volatility, or mean-reversion speed above
                          # ever change, since those change which seeds land
                          # a loss.

# Mean reversion: commodity prices don't drift forever — new supply shows
# up when prices run high, producers cut back when they run low, both pull
# the price back toward a level the market can sustain. Modeled as an
# Ornstein-Uhlenbeck-style pull toward the anchor each day, proportional to
# how far the (log) price has drifted. 0.03 = ~3% of the gap closes daily.
SPOT_MEAN_REVERSION_SPEED = 0.03

# Correlation: JKM and TTF arbitrage each other via floating LNG cargoes
# (a cargo can be redirected from Europe to Asia and back, which pulls the
# two prices together), so they mostly move on a shared "world gas market"
# shock each day, with their own idiosyncratic noise on top. HH is a
# domestic US benchmark, structurally decoupled from both — drawn fully
# independently (0 loading on the shared factor).
SPOT_JKM_TTF_CORRELATION = 0.70

# A spot voyage is only dispatched if its expected margin (computed with
# today's prices — the only prices known at decision time) clears this
# floor. 0 = dispatch anything with a positive expected margin.
SPOT_MIN_EXPECTED_MARGIN_USD = 0.0

# US Gulf Coast FOB cargo cost is NOT the raw Henry Hub commodity price —
# HH is wellhead/feedgas, not delivered LNG. Standard US offtake SPA
# formula (Cheniere-style): 115% of Henry Hub, plus a liquefaction tolling
# fee. Applied only to HH-linked loading terminals in core/spot.py — JKM/TTF
# loading terminals are already a landed-price proxy, no fee on top.
HH_INDEXATION_FACTOR       = 1.15
LIQUEFACTION_FEE_USD_MMBTU = 3.00

# ---------------------------------------------------------------------------
# Freight rates (simulated charter cost by vessel class, USD/day)
# ---------------------------------------------------------------------------

FREIGHT_RATE_USD_PER_DAY = {
    "Q-Max":  95_000,
    "Q-Flex": 85_000,
    "TFDE":   70_000,
    "STEAM":  60_000,
}


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
    print(f"  JKM   : ${PRICE_JKM}/mmBtu  (= TTF + {ASIAN_SPREAD_USD_MMBTU} spread)")
    print(f"  TTF   : ${PRICE_TTF}/mmBtu")
    print(f"  HH    : ${PRICE_HH}/mmBtu")
    print(f"  HFO   : ${PRICE_HFO}/mmBtu")
    print(f"  Brent : ${PRICE_BRENT}/bbl (informational)")

    print("\n-- FX rates (USD ->) --")
    for currency, rate in FX_RATE_USD_TO.items():
        print(f"  {currency:<4} {rate}")

    print("\n-- Demurrage rates --")
    for cls, rate in DEMURRAGE_RATE.items():
        print(f"  {cls:<8} ${rate:,.0f}/day")

    print("\n-- Canals --")
    print(f"  Suez   : {SUEZ_TRANSIT_HOURS}h  ${SUEZ_TOLL_USD:,.0f}")
    print(f"  Panama : {PANAMA_TRANSIT_HOURS}h  ${PANAMA_TOLL_USD:,.0f}")

    print("\n-- Terminal price markers --")
    for term, marker in TERMINAL_PRICE_MARKER.items():
        print(f"  {term:<16} {marker}")

    print("\n-- Freight rates --")
    for cls, rate in FREIGHT_RATE_USD_PER_DAY.items():
        print(f"  {cls:<8} ${rate:,.0f}/day")

    print("\n-- Spot market simulation --")
    print(f"  horizon                 {SPOT_HORIZON_DAYS} days")
    for marker, vol in SPOT_DAILY_VOLATILITY.items():
        print(f"  {marker:<4} daily volatility {vol*100:.1f}%")
    print(f"  seed                    {SPOT_PRICE_SEED}")
    print(f"  min expected margin     ${SPOT_MIN_EXPECTED_MARGIN_USD:,.0f}")
    print(f"  mean reversion speed    {SPOT_MEAN_REVERSION_SPEED*100:.0f}%/day")
    print(f"  JKM/TTF correlation     {SPOT_JKM_TTF_CORRELATION*100:.0f}%")

    print("\nOK")
