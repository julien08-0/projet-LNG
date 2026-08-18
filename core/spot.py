# core/spot.py
# Opportunistic spot trading: buy LNG in one region, sell it in another,
# pocket the spread. Complementary to core/optimizer.py's fixed contracts —
# only vessels not committed to a contract (or idle between two contracts)
# are considered here.
#
# The central rule, and the whole point of this module: a dispatch decision
# on day D can only use prices known on day D. The sell price is only
# realized once the vessel actually arrives, days or weeks later — by
# definition unknown at decision time. So every voyage carries two figures:
#   expected_margin_usd : computed at dispatch time, today's buy price vs
#                          today's sell price (the best available estimate
#                          for a price that follows a random walk).
#   realized_margin_usd : computed once the voyage settles, today's buy
#                          price vs the ACTUAL sell price on arrival day.
# The gap between the two is real trading risk — a voyage dispatched at a
# positive expected margin can still realize a loss if the destination
# market moves against it during transit. That's expected behavior, not a
# bug: it's what "the future price is unknown" means in practice.
#
# Buy side is treated as locked in at dispatch time (day D's regional
# price) — a spot cargo nomination, not a forward guess. Only the sell
# side carries decision-vs-outcome uncertainty, since it only resolves
# after the transit to the discharge terminal.

import sys
import os
import math
import random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta

from config import (
    TERMINAL_PRICE_MARKER, FREIGHT_RATE_USD_PER_DAY,
    LNG_ENERGY_DENSITY_MMBTU_PER_M3, PRICE_JKM, PRICE_TTF, PRICE_HH,
    SPOT_DAILY_VOLATILITY, SPOT_PRICE_SEED, SPOT_MIN_EXPECTED_MARGIN_USD,
    SPOT_MEAN_REVERSION_SPEED, SPOT_JKM_TTF_CORRELATION, SPOT_HORIZON_DAYS,
    HH_INDEXATION_FACTOR, LIQUEFACTION_FEE_USD_MMBTU,
)
from core.routing import build_route
from core.physics import calculate_boiloff, calculate_heel_requirement
from core.constraints import check_draft_compatibility

PRICE_ANCHOR = {"JKM": PRICE_JKM, "TTF": PRICE_TTF, "HH": PRICE_HH}

# How far past the decision horizon to keep generating prices, so a voyage
# dispatched near the end of the horizon still has a real settlement price
# to look up instead of falling off the end of the array.
PRICE_PATH_BUFFER_DAYS = 60

# Random-walk bounds — keeps a multi-week path from wandering to an
# unrealistic price. +/-70% of the anchor.
PRICE_FLOOR_FRACTION   = 0.30
PRICE_CEILING_FRACTION = 3.00


# ---------------------------------------------------------------------------
# Regional price paths
# ---------------------------------------------------------------------------

def generate_price_paths(n_days, seed=SPOT_PRICE_SEED):
    """
    Bounded, mean-reverting, partially-correlated random walk for each
    regional marker (JKM, TTF, HH), one price per day for n_days. Two
    things a plain independent random walk got wrong:

      - Mean reversion: commodity prices don't drift forever — new supply
        arrives when prices run high, producers cut back when they run
        low, both pulling the price back toward a sustainable level.
        Modeled as a daily pull toward the anchor (in log-price space),
        proportional to how far it's drifted (config.SPOT_MEAN_REVERSION_SPEED).
      - Correlation: JKM and TTF arbitrage each other via floating LNG
        cargoes (a cargo can be redirected from one basin to the other),
        so they mostly move on a shared "world gas market" shock each
        day, plus their own idiosyncratic noise on top
        (config.SPOT_JKM_TTF_CORRELATION). HH is a domestic US benchmark,
        drawn fully independently of both.

    Same seed -> same path, every run.

    Returns {marker: [price_day0, price_day1, ...]}.
    """
    rng = random.Random(seed)
    markers = list(PRICE_ANCHOR.keys())   # fixed order (dict insertion order) -> deterministic draws

    log_anchor = {m: math.log(PRICE_ANCHOR[m]) for m in markers}
    log_price  = dict(log_anchor)
    log_floor   = {m: math.log(PRICE_ANCHOR[m] * PRICE_FLOOR_FRACTION) for m in markers}
    log_ceiling = {m: math.log(PRICE_ANCHOR[m] * PRICE_CEILING_FRACTION) for m in markers}

    paths = {m: [PRICE_ANCHOR[m]] for m in markers}

    for _ in range(1, n_days):
        market_shock = rng.gauss(0.0, 1.0)   # shared "world gas market" factor, drawn once per day

        for marker in markers:
            idiosyncratic = rng.gauss(0.0, 1.0)
            loading = SPOT_JKM_TTF_CORRELATION if marker in ("JKM", "TTF") else 0.0
            shock = loading * market_shock + math.sqrt(max(0.0, 1.0 - loading ** 2)) * idiosyncratic

            reversion = SPOT_MEAN_REVERSION_SPEED * (log_anchor[marker] - log_price[marker])
            vol = SPOT_DAILY_VOLATILITY[marker]
            log_price[marker] += reversion + vol * shock
            log_price[marker] = max(log_floor[marker], min(log_ceiling[marker], log_price[marker]))

            paths[marker].append(round(math.exp(log_price[marker]), 3))

    return paths


# ---------------------------------------------------------------------------
# Vessel economics helpers
# ---------------------------------------------------------------------------

def loading_buy_price(load_term, day, price_paths):
    """
    FOB cargo cost at a loading terminal on a given day.

    HH-linked terminals (Sabine Pass): raw Henry Hub is a feedgas/wellhead
    price, not a delivered-cargo price — apply the standard US offtake SPA
    formula (115% HH + liquefaction fee) so the buy side is on the same
    "cost of an LNG cargo" basis as the JKM/TTF sell side. JKM/TTF-linked
    loading terminals (Ras Laffan) are left as-is: already a landed-price
    proxy, no tolling fee modeled on top (documented simplification).
    """
    marker = TERMINAL_PRICE_MARKER[load_term["id"]]
    base_price = price_paths[marker][day]
    if marker == "HH":
        return base_price * HH_INDEXATION_FACTOR + LIQUEFACTION_FEE_USD_MMBTU
    return base_price


def usable_volume_mmbtu(vessel, ballast_days=0.0):
    """
    Commercially loadable volume: capacity minus the heel that never
    leaves the tanks. ballast_days matters here specifically because spot
    voyages often involve a long empty leg to reach a loading terminal
    (e.g. Gulf -> Sabine Pass) — the heel eroding along the way means a
    vessel must reserve MORE of its capacity as heel to still have enough
    on arrival, leaving slightly less commercially loadable. 0 (the
    default) reduces to the original flat-fraction behavior.
    """
    heel = calculate_heel_requirement(vessel["capacity_m3"], vessel["vessel_class"], ballast_days=ballast_days)
    loadable_m3 = vessel["capacity_m3"] - heel["required_heel_m3"]
    return loadable_m3 * LNG_ENERGY_DENSITY_MMBTU_PER_M3


def _contract_busy_window(cargo, vessel, discharge_terminal_id, terminals_by_id, sim_start):
    """Day (float, offset from sim_start) this vessel becomes free again after its fixed contract."""
    from core.physics import calculate_eta

    loading_start = datetime.fromisoformat(cargo["laycan_start"])
    loading_end   = loading_start + timedelta(hours=24)

    route = build_route(terminals_by_id[cargo["loading_terminal"]], terminals_by_id[discharge_terminal_id])
    eta = calculate_eta(
        departure_date_iso=loading_end.isoformat(timespec="minutes"),
        distance_nm=route["distance_nm"],
        speed_knots=vessel["laden_speed_knots"],
        weather_delay_hours=route["weather_delay_hours"],
        canal_delay_hours=route["canal_delay_hours"],
    )
    discharge_end = datetime.fromisoformat(eta["eta_iso"]) + timedelta(hours=24)
    return (discharge_end - sim_start).total_seconds() / 86400.0


def _project_price(marker, today_price, days_ahead):
    """
    Best available estimate of a future price, given that the market is
    KNOWN to mean-revert (a real trader would price that in, not assume
    tomorrow looks like today forever). The center of the estimate decays
    geometrically from today's price back toward the anchor as days_ahead
    grows, at the same rate the price process itself reverts
    (config.SPOT_MEAN_REVERSION_SPEED) — the conditional mean of an
    Ornstein-Uhlenbeck-style process in log space.

    Log space is exactly where this gets subtle: revenue is LINEAR in
    price (volume x price), but the price path is log-normal, so
    E[price] != exp(E[log price]) — that would be the MEDIAN, not the
    mean, and Jensen's inequality means the true arithmetic mean sits
    above it by exp(0.5 x variance). Dropping that term would silently
    and systematically understate the expected price (and so the
    expected margin) on every voyage, worst on the longest transits where
    the variance term is largest — which is exactly what an earlier,
    median-only version of this function did: every realized margin came
    out above expected, on every voyage, in every seed. Not "occasionally
    lucky" — a real, structural bias with a name.

    Still only an expectation, still not a certainty: the realized price
    carries whatever shock actually lands between now and arrival, which
    this function has no way to know in advance.
    """
    if days_ahead <= 0:
        return today_price

    anchor = PRICE_ANCHOR[marker]
    vol    = SPOT_DAILY_VOLATILITY[marker]
    decay  = 1.0 - SPOT_MEAN_REVERSION_SPEED

    mean_log = math.log(anchor) + (decay ** days_ahead) * (math.log(today_price) - math.log(anchor))

    # Conditional variance after days_ahead steps of shocks that decay at
    # the same rate as the mean reverts (geometric series).
    if abs(decay - 1.0) < 1e-9:
        variance_log = (vol ** 2) * days_ahead
    else:
        variance_log = (vol ** 2) * (1.0 - decay ** (2 * days_ahead)) / (1.0 - decay ** 2)

    return math.exp(mean_log + 0.5 * variance_log)


# ---------------------------------------------------------------------------
# Evaluate one candidate voyage (load_terminal -> discharge_terminal) for
# one vessel, using only prices known on `day`.
# ---------------------------------------------------------------------------

def _evaluate_voyage(vessel, position, day, load_term, dis_term, price_paths, horizon_days):
    if not check_draft_compatibility(vessel["vessel_class"], load_term["max_draft_m"])["compatible"]:
        return None
    if not check_draft_compatibility(vessel["vessel_class"], dis_term["max_draft_m"])["compatible"]:
        return None

    buy_marker  = TERMINAL_PRICE_MARKER[load_term["id"]]
    sell_marker = TERMINAL_PRICE_MARKER[dis_term["id"]]

    # Real routed distance for the ballast leg, not straight-line — same
    # principle as core.optimizer's reachability check (a chokepoint
    # detour can make the real distance meaningfully longer). Ballast
    # speed, since the vessel isn't carrying cargo yet.
    vessel_position = {"id": "VESSEL_POSITION", "lat": position[0], "lon": position[1]}
    ballast_route = build_route(vessel_position, load_term)
    ballast_days = (ballast_route["distance_nm"] / vessel["ballast_speed_knots"]
                     + ballast_route["weather_delay_hours"] + ballast_route["canal_delay_hours"]) / 24.0
    loading_done_day = day + ballast_days + 1.0   # +1.0 = 24h loading window

    if loading_done_day > horizon_days - 1:
        return None   # not enough runway left to even finish loading

    # No closed_chokepoints here by design: ui/spot.py doesn't expose a
    # disruption control, unlike the Fleet Map / Disruption Simulator pages.
    # Spot voyages always assume open chokepoints.
    route = build_route(load_term, dis_term)
    if route["blocked"]:
        return None

    laden_transit_days = (route["distance_nm"] / vessel["laden_speed_knots"]
                           + route["weather_delay_hours"] + route["canal_delay_hours"]) / 24.0
    arrival_day = loading_done_day + laden_transit_days
    arrival_day_int = min(int(math.ceil(arrival_day)), len(price_paths[sell_marker]) - 1)

    volume_mmbtu = usable_volume_mmbtu(vessel, ballast_days=ballast_days)
    buy_price_today = loading_buy_price(load_term, day, price_paths)
    buy_cost_usd = volume_mmbtu * buy_price_today

    bog = calculate_boiloff(volume_mmbtu, laden_transit_days, vessel["vessel_class"], ambient_temp_celsius=28.0)
    net_bog_cost_usd = bog["gross_bog_mmbtu"] * price_paths[sell_marker][day] - bog["bunker_saving_usd"]

    total_days_chartered = ballast_days + 1.0 + laden_transit_days
    transport_cost_usd = FREIGHT_RATE_USD_PER_DAY[vessel["vessel_class"]] * total_days_chartered
    canal_toll_usd = route["canal_toll_usd"]

    # Mean-reversion-adjusted estimate, not a flat "today's price holds" —
    # see _project_price. Still only an estimate: the shocks between now
    # and arrival are unknown, which is where realized margin can diverge.
    expected_sell_price = _project_price(sell_marker, price_paths[sell_marker][day], arrival_day_int - day)
    expected_revenue_usd = volume_mmbtu * expected_sell_price
    expected_margin_usd = (expected_revenue_usd - net_bog_cost_usd
                            - transport_cost_usd - canal_toll_usd - buy_cost_usd)

    return {
        "load_terminal_id":     load_term["id"],
        "discharge_terminal_id": dis_term["id"],
        "buy_marker":           buy_marker,
        "sell_marker":          sell_marker,
        "volume_mmbtu":         round(volume_mmbtu, 0),
        "buy_price_usd_mmbtu":  buy_price_today,
        "expected_sell_price_usd_mmbtu": expected_sell_price,
        "net_bog_cost_usd":     round(net_bog_cost_usd, 2),
        "transport_cost_usd":   round(transport_cost_usd, 2),
        "canal_toll_usd":       round(canal_toll_usd, 2),
        "buy_cost_usd":         round(buy_cost_usd, 2),
        "expected_margin_usd":  round(expected_margin_usd, 2),
        "ballast_days":         round(ballast_days, 2),
        "laden_transit_days":   round(laden_transit_days, 2),
        "loading_done_day":     loading_done_day,
        "arrival_day":          arrival_day_int,
    }


# ---------------------------------------------------------------------------
# Full simulation — walk day by day, dispatch when profitable, settle once
# each voyage's arrival day is reached.
# ---------------------------------------------------------------------------

def simulate_spot_market(vessels, terminals, cargoes, contract_assignments_enriched,
                          n_days=SPOT_HORIZON_DAYS, seed=SPOT_PRICE_SEED):
    """
    Day-by-day opportunistic dispatch for every vessel not tied up on a
    fixed contract.

    cargoes: the fixed-contract cargo list (data.cargoes.CARGOES) — needed
    to read each committed vessel's laycan/loading terminal.
    contract_assignments_enriched: output of core.pnl.enrich_assignments_with_pnl()
    for the fixed-contract fleet — used only to compute when each
    contract-committed vessel becomes free for spot trading.

    Returns:
      price_paths : {marker: [price_day0, ...]}, length n_days + buffer
      decisions   : list of dispatched voyages, each with expected AND
                    realized margin, sorted by dispatch day
      summary     : aggregate totals (expected vs realized, win/loss count)
    """
    sim_start = datetime(2025, 3, 1)
    terminals_by_id = {t["id"]: t for t in terminals}
    cargoes_by_id   = {c["id"]: c for c in cargoes}
    loading_terminals   = [t for t in terminals if t["type"] == "loading"]
    discharge_terminals = [t for t in terminals if t["type"] == "discharge"]

    price_paths = generate_price_paths(n_days + PRICE_PATH_BUFFER_DAYS, seed=seed)

    committed_by_vessel = {e["vessel_id"]: e for e in contract_assignments_enriched if e["feasible"]}

    free_from_day = {}
    position      = {}
    for v in vessels:
        if v["id"] in committed_by_vessel:
            e = committed_by_vessel[v["id"]]
            cargo = cargoes_by_id[e["cargo_id"]]
            free_from_day[v["id"]] = math.ceil(_contract_busy_window(
                cargo=cargo, vessel=v, discharge_terminal_id=e["discharge_terminal"],
                terminals_by_id=terminals_by_id, sim_start=sim_start,
            ))
            dest = terminals_by_id[e["discharge_terminal"]]
            position[v["id"]] = (dest["lat"], dest["lon"])
        else:
            vessel_available = datetime.fromisoformat(v["available_from"])
            free_from_day[v["id"]] = max(0, math.ceil((vessel_available - sim_start).total_seconds() / 86400.0))
            position[v["id"]] = (v["current_lat"], v["current_lon"])

    decisions = []

    for day in range(n_days):
        for v in vessels:
            if free_from_day[v["id"]] > day:
                continue

            best = None
            for load_term in loading_terminals:
                for dis_term in discharge_terminals:
                    candidate = _evaluate_voyage(v, position[v["id"]], day, load_term, dis_term,
                                                  price_paths, n_days + PRICE_PATH_BUFFER_DAYS)
                    if candidate is None:
                        continue
                    if best is None or candidate["expected_margin_usd"] > best["expected_margin_usd"]:
                        best = candidate

            if best is None or best["expected_margin_usd"] <= SPOT_MIN_EXPECTED_MARGIN_USD:
                continue

            realized_sell_price = price_paths[best["sell_marker"]][best["arrival_day"]]
            realized_revenue_usd = best["volume_mmbtu"] * realized_sell_price
            realized_margin_usd = (realized_revenue_usd - best["net_bog_cost_usd"]
                                    - best["transport_cost_usd"] - best["canal_toll_usd"]
                                    - best["buy_cost_usd"])

            # A voyage dispatched late enough that its arrival lands on or
            # after the last simulated day hasn't actually happened yet —
            # realized_margin_usd/realized_sell_price above are still a real
            # forward calculation (the price path already extends past
            # n_days via PRICE_PATH_BUFFER_DAYS, so the number isn't
            # fabricated), but presenting it as a settled GAIN/LOSS would
            # claim knowledge of a delivery that, as of day n_days, hasn't
            # occurred — same category of bug as showing a still-in-transit
            # vessel on the Fleet Map as already discharged.
            settled = best["arrival_day"] < n_days
            outcome = ("gain" if realized_margin_usd >= 0 else "loss") if settled else "pending"

            decisions.append({
                "vessel_id":            v["id"],
                "vessel_class":         v["vessel_class"],
                "dispatch_day":         day,
                "arrival_day":          best["arrival_day"],
                "load_terminal_id":     best["load_terminal_id"],
                "discharge_terminal_id": best["discharge_terminal_id"],
                "buy_marker":           best["buy_marker"],
                "sell_marker":          best["sell_marker"],
                "volume_mmbtu":         best["volume_mmbtu"],
                "buy_price_usd_mmbtu":  best["buy_price_usd_mmbtu"],
                "expected_sell_price_usd_mmbtu": best["expected_sell_price_usd_mmbtu"],
                "realized_sell_price_usd_mmbtu": round(realized_sell_price, 3),
                "expected_margin_usd":  best["expected_margin_usd"],
                "realized_margin_usd":  round(realized_margin_usd, 2),
                "settled":              settled,
                "outcome":              outcome,
                # Timeline fields — used by ui/map.py to animate this voyage
                # the same way a fixed contract is animated (ballast ->
                # loading -> transit -> discharge), reusing get_vessel_state()
                # unchanged rather than adding a second rendering path.
                "ballast_days":         best["ballast_days"],
                "loading_done_day":     best["loading_done_day"],
                "laden_transit_days":   best["laden_transit_days"],
            })

            dest_term = terminals_by_id[best["discharge_terminal_id"]]
            free_from_day[v["id"]] = math.ceil(best["arrival_day"]) + 1   # +1 = 24h discharge window
            position[v["id"]] = (dest_term["lat"], dest_term["lon"])

    settled_decisions = [d for d in decisions if d["settled"]]

    # Expected-vs-realized ("surprise") only makes sense compared over the
    # SAME set of voyages — mixing in still-pending voyages (real margin
    # unknowable yet) into "realized" while "expected" counts everyone
    # dispatched would make every pending voyage look like a phantom loss.
    total_expected = sum(d["expected_margin_usd"] for d in settled_decisions)
    total_realized = sum(d["realized_margin_usd"] for d in settled_decisions)
    wins   = sum(1 for d in settled_decisions if d["outcome"] == "gain")
    losses = sum(1 for d in settled_decisions if d["outcome"] == "loss")

    summary = {
        "voyage_count":         len(decisions),
        "settled_count":        len(settled_decisions),
        "pending_count":        len(decisions) - len(settled_decisions),
        "total_expected_margin_usd": round(total_expected, 2),
        "total_realized_margin_usd": round(total_realized, 2),
        "surprise_usd":         round(total_realized - total_expected, 2),
        "wins":                 wins,
        "losses":               losses,
    }

    return {"price_paths": price_paths, "decisions": decisions, "summary": summary}


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from data.cargoes   import CARGOES
    from data.vessels   import VESSELS
    from data.terminals import TERMINALS
    from core.optimizer import assign_cargoes
    from core.pnl       import enrich_assignments_with_pnl

    print("=== core/spot.py ===\n")

    result = assign_cargoes(CARGOES, VESSELS, TERMINALS)
    enriched = enrich_assignments_with_pnl(result["assignments"], CARGOES, VESSELS, TERMINALS)

    print("-- Price paths (first 10 days) --")
    paths = generate_price_paths(SPOT_HORIZON_DAYS)
    for marker, prices in paths.items():
        print(f"  {marker:<4} {[round(p,2) for p in prices[:10]]}")

    print("\n-- Reproducibility (same seed -> same path) --")
    paths_again = generate_price_paths(SPOT_HORIZON_DAYS)
    assert paths == paths_again
    print("  OK, identical")

    print("\n-- Correlation: JKM/TTF should move together more than HH does with either --")
    long_paths = generate_price_paths(500, seed=999)   # long path -> stable correlation estimate

    def _returns(prices):
        return [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]

    def _correlation(a, b):
        n = len(a)
        mean_a, mean_b = sum(a) / n, sum(b) / n
        cov = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n)) / n
        std_a = (sum((x - mean_a) ** 2 for x in a) / n) ** 0.5
        std_b = (sum((x - mean_b) ** 2 for x in b) / n) ** 0.5
        return cov / (std_a * std_b)

    jkm_ret, ttf_ret, hh_ret = (_returns(long_paths[m]) for m in ("JKM", "TTF", "HH"))
    corr_jkm_ttf = _correlation(jkm_ret, ttf_ret)
    corr_jkm_hh  = _correlation(jkm_ret, hh_ret)
    print(f"  corr(JKM, TTF) = {corr_jkm_ttf:+.2f}")
    print(f"  corr(JKM, HH)  = {corr_jkm_hh:+.2f}")
    assert corr_jkm_ttf > corr_jkm_hh + 0.3, "JKM/TTF should be meaningfully more correlated than JKM/HH"
    print("  OK, JKM/TTF move together more than JKM/HH does")

    print("\n-- Mean reversion: a path forced far from anchor should drift back, not stay put --")
    # Same generator, but starting the walk far below anchor — reversion
    # should pull it back up over time rather than leaving it to wander.
    import random as _random
    forced_rng = _random.Random(1)
    log_anchor_jkm = math.log(PRICE_JKM)
    displaced = log_anchor_jkm - 1.5   # well below anchor
    path = [math.exp(displaced)]
    for _ in range(200):
        shock = forced_rng.gauss(0.0, 1.0)
        displaced += SPOT_MEAN_REVERSION_SPEED * (log_anchor_jkm - displaced) + SPOT_DAILY_VOLATILITY["JKM"] * shock
        path.append(math.exp(displaced))
    print(f"  Start (displaced): ${path[0]:.2f}   Anchor: ${PRICE_JKM:.2f}   After 200 days: ${path[-1]:.2f}")
    assert abs(path[-1] - PRICE_JKM) < abs(path[0] - PRICE_JKM), \
        "mean reversion should pull a displaced price back toward the anchor over time"
    print("  OK, drifted back toward the anchor instead of staying displaced")

    print("\n-- No-lookahead invariant: a decision cannot see prices after `day` --")
    test_day = 10
    paths_clean = generate_price_paths(SPOT_HORIZON_DAYS, seed=1)
    paths_corrupted = {m: list(p) for m, p in paths_clean.items()}
    for marker in paths_corrupted:
        for i in range(test_day + 1, len(paths_corrupted[marker])):
            paths_corrupted[marker][i] = 999.0   # if this leaks into the decision, the assert below fails

    vessel_t    = VESSELS[0]
    load_term_t = next(t for t in TERMINALS if t["id"] == "SABINE-PASS")
    dis_term_t  = next(t for t in TERMINALS if t["id"] == "ZEEBRUGGE")
    position_t  = (vessel_t["current_lat"], vessel_t["current_lon"])
    horizon_t   = SPOT_HORIZON_DAYS + PRICE_PATH_BUFFER_DAYS

    result_clean     = _evaluate_voyage(vessel_t, position_t, test_day, load_term_t, dis_term_t, paths_clean, horizon_t)
    result_corrupted = _evaluate_voyage(vessel_t, position_t, test_day, load_term_t, dis_term_t, paths_corrupted, horizon_t)
    assert result_clean["expected_margin_usd"] == result_corrupted["expected_margin_usd"], \
        "expected_margin_usd changed when future prices were corrupted -> the decision leaked a future price"
    print(f"  OK, expected_margin_usd unchanged (${result_clean['expected_margin_usd']:,.0f}) "
          f"even with every price after day {test_day} corrupted to $999")

    print("\n-- Usable volume by vessel --")
    for v in VESSELS:
        print(f"  {v['id']:<16} {usable_volume_mmbtu(v):,.0f} mmBtu loadable")

    print("\n-- Usable volume erodes with a long ballast (heel erosion, VESSEL-QM-01) --")
    qm01 = next(v for v in VESSELS if v["id"] == "VESSEL-QM-01")
    for ballast_days in [0, 10, 20]:
        vol = usable_volume_mmbtu(qm01, ballast_days=ballast_days)
        print(f"  {ballast_days:>2}d ballast -> {vol:,.0f} mmBtu loadable")
    assert usable_volume_mmbtu(qm01, ballast_days=20) < usable_volume_mmbtu(qm01, ballast_days=0)

    print(f"\n-- Spot simulation over {SPOT_HORIZON_DAYS} days (contracts fixed, spot fills the gaps) --")
    sim = simulate_spot_market(VESSELS, TERMINALS, CARGOES, enriched, n_days=SPOT_HORIZON_DAYS)
    for d in sim["decisions"]:
        print(f"  day {d['dispatch_day']:>2} {d['vessel_id']:<16} "
              f"{d['load_terminal_id']:<12}->{d['discharge_terminal_id']:<16} "
              f"buy {d['buy_marker']}@{d['buy_price_usd_mmbtu']:.2f} "
              f"sell exp {d['sell_marker']}@{d['expected_sell_price_usd_mmbtu']:.2f} "
              f"real@{d['realized_sell_price_usd_mmbtu']:.2f}  "
              f"margin exp ${d['expected_margin_usd']:,.0f} real ${d['realized_margin_usd']:,.0f} "
              f"[{d['outcome'].upper()}]")

    print(f"\n  Voyages dispatched : {sim['summary']['voyage_count']}")
    print(f"  Settled / pending  : {sim['summary']['settled_count']} / {sim['summary']['pending_count']}")
    print(f"  Wins / losses      : {sim['summary']['wins']} / {sim['summary']['losses']}")
    print(f"  Total expected     : ${sim['summary']['total_expected_margin_usd']:,.0f}")
    print(f"  Total realized     : ${sim['summary']['total_realized_margin_usd']:,.0f}")
    print(f"  Surprise (real-exp): ${sim['summary']['surprise_usd']:,.0f}")

    assert sim["summary"]["settled_count"] + sim["summary"]["pending_count"] == sim["summary"]["voyage_count"]
    assert sim["summary"]["wins"] + sim["summary"]["losses"] == sim["summary"]["settled_count"]
    for d in sim["decisions"]:
        assert d["settled"] == (d["arrival_day"] < SPOT_HORIZON_DAYS)
        if not d["settled"]:
            assert d["outcome"] == "pending"
    print("  OK, pending voyages (arrival on/after the last simulated day) "
          "are excluded from wins/losses and from the realized/expected totals")

    print("\n-- A voyage dispatched right at the edge of the horizon is marked pending, not settled --")
    tight_sim = simulate_spot_market(VESSELS, TERMINALS, CARGOES, enriched, n_days=10, seed=SPOT_PRICE_SEED)
    if tight_sim["decisions"]:
        assert all(not d["settled"] and d["outcome"] == "pending" for d in tight_sim["decisions"]), \
            "a 10-day horizon is far shorter than any real ballast+laden transit -- nothing should settle"
        print(f"  OK, all {len(tight_sim['decisions'])} voyage(s) dispatched within a 10-day horizon "
              f"are pending (transit alone takes weeks)")
    else:
        print("  OK, no voyage dispatched within a 10-day horizon")

    print("\nOK")
