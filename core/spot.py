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
    HH_INDEXATION_FACTOR, LIQUEFACTION_FEE_USD_MMBTU,
)
from core.routing import build_route, haversine_nm
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
    Bounded random walk for each regional marker (JKM, TTF, HH), one price
    per day for n_days. Same seed -> same path, every run.

    Returns {marker: [price_day0, price_day1, ...]}.
    """
    rng = random.Random(seed)
    paths = {}

    for marker, anchor in PRICE_ANCHOR.items():
        vol = SPOT_DAILY_VOLATILITY[marker]
        floor   = anchor * PRICE_FLOOR_FRACTION
        ceiling = anchor * PRICE_CEILING_FRACTION

        prices = [anchor]
        for _ in range(1, n_days):
            log_return = rng.gauss(0.0, vol)
            next_price = prices[-1] * math.exp(log_return)
            next_price = max(floor, min(ceiling, next_price))
            prices.append(round(next_price, 3))

        paths[marker] = prices

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


def usable_volume_mmbtu(vessel):
    """Commercially loadable volume: capacity minus the heel that never leaves the tanks."""
    heel = calculate_heel_requirement(vessel["capacity_m3"], vessel["vessel_class"])
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
        speed_knots=vessel["speed_knots"],
        weather_delay_hours=route["weather_delay_hours"],
        canal_delay_hours=route["canal_delay_hours"],
    )
    discharge_end = datetime.fromisoformat(eta["eta_iso"]) + timedelta(hours=24)
    return (discharge_end - sim_start).total_seconds() / 86400.0


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

    dist_to_load  = haversine_nm(position[0], position[1], load_term["lat"], load_term["lon"])
    ballast_days  = dist_to_load / vessel["speed_knots"] / 24.0
    loading_done_day = day + ballast_days + 1.0   # +1.0 = 24h loading window

    if loading_done_day > horizon_days - 1:
        return None   # not enough runway left to even finish loading

    # No closed_chokepoints here by design: ui/spot.py doesn't expose a
    # disruption control, unlike the Fleet Map / Disruption Simulator pages.
    # Spot voyages always assume open chokepoints.
    route = build_route(load_term, dis_term)
    if route["blocked"]:
        return None

    laden_transit_days = (route["distance_nm"] / vessel["speed_knots"]
                           + route["weather_delay_hours"] + route["canal_delay_hours"]) / 24.0
    arrival_day = loading_done_day + laden_transit_days
    arrival_day_int = min(int(math.ceil(arrival_day)), len(price_paths[sell_marker]) - 1)

    volume_mmbtu = usable_volume_mmbtu(vessel)
    buy_price_today = loading_buy_price(load_term, day, price_paths)
    buy_cost_usd = volume_mmbtu * buy_price_today

    bog = calculate_boiloff(volume_mmbtu, laden_transit_days, vessel["vessel_class"], ambient_temp_celsius=28.0)
    net_bog_cost_usd = bog["gross_bog_mmbtu"] * price_paths[sell_marker][day] - bog["bunker_saving_usd"]

    total_days_chartered = ballast_days + 1.0 + laden_transit_days
    transport_cost_usd = FREIGHT_RATE_USD_PER_DAY[vessel["vessel_class"]] * total_days_chartered
    canal_toll_usd = route["canal_toll_usd"]

    expected_sell_price = price_paths[sell_marker][day]   # unbiased estimate for a random walk: today's price
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

def simulate_spot_market(vessels, terminals, cargoes, contract_assignments_enriched, n_days=46, seed=SPOT_PRICE_SEED):
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
                "outcome":              "gain" if realized_margin_usd >= 0 else "loss",
            })

            dest_term = terminals_by_id[best["discharge_terminal_id"]]
            free_from_day[v["id"]] = math.ceil(best["arrival_day"]) + 1   # +1 = 24h discharge window
            position[v["id"]] = (dest_term["lat"], dest_term["lon"])

    total_expected = sum(d["expected_margin_usd"] for d in decisions)
    total_realized = sum(d["realized_margin_usd"] for d in decisions)
    wins  = sum(1 for d in decisions if d["outcome"] == "gain")
    losses = sum(1 for d in decisions if d["outcome"] == "loss")

    summary = {
        "voyage_count":         len(decisions),
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
    paths = generate_price_paths(46)
    for marker, prices in paths.items():
        print(f"  {marker:<4} {[round(p,2) for p in prices[:10]]}")

    print("\n-- Reproducibility (same seed -> same path) --")
    paths_again = generate_price_paths(46)
    assert paths == paths_again
    print("  OK, identical")

    print("\n-- No-lookahead invariant: a decision cannot see prices after `day` --")
    test_day = 10
    paths_clean = generate_price_paths(46, seed=1)
    paths_corrupted = {m: list(p) for m, p in paths_clean.items()}
    for marker in paths_corrupted:
        for i in range(test_day + 1, len(paths_corrupted[marker])):
            paths_corrupted[marker][i] = 999.0   # if this leaks into the decision, the assert below fails

    vessel_t    = VESSELS[0]
    load_term_t = next(t for t in TERMINALS if t["id"] == "SABINE-PASS")
    dis_term_t  = next(t for t in TERMINALS if t["id"] == "ZEEBRUGGE")
    position_t  = (vessel_t["current_lat"], vessel_t["current_lon"])
    horizon_t   = 46 + PRICE_PATH_BUFFER_DAYS

    result_clean     = _evaluate_voyage(vessel_t, position_t, test_day, load_term_t, dis_term_t, paths_clean, horizon_t)
    result_corrupted = _evaluate_voyage(vessel_t, position_t, test_day, load_term_t, dis_term_t, paths_corrupted, horizon_t)
    assert result_clean["expected_margin_usd"] == result_corrupted["expected_margin_usd"], \
        "expected_margin_usd changed when future prices were corrupted -> the decision leaked a future price"
    print(f"  OK, expected_margin_usd unchanged (${result_clean['expected_margin_usd']:,.0f}) "
          f"even with every price after day {test_day} corrupted to $999")

    print("\n-- Usable volume by vessel --")
    for v in VESSELS:
        print(f"  {v['id']:<16} {usable_volume_mmbtu(v):,.0f} mmBtu loadable")

    print("\n-- Spot simulation over 46 days (contracts fixed, spot fills the gaps) --")
    sim = simulate_spot_market(VESSELS, TERMINALS, CARGOES, enriched, n_days=46)
    for d in sim["decisions"]:
        print(f"  day {d['dispatch_day']:>2} {d['vessel_id']:<16} "
              f"{d['load_terminal_id']:<12}->{d['discharge_terminal_id']:<16} "
              f"buy {d['buy_marker']}@{d['buy_price_usd_mmbtu']:.2f} "
              f"sell exp {d['sell_marker']}@{d['expected_sell_price_usd_mmbtu']:.2f} "
              f"real@{d['realized_sell_price_usd_mmbtu']:.2f}  "
              f"margin exp ${d['expected_margin_usd']:,.0f} real ${d['realized_margin_usd']:,.0f} "
              f"[{d['outcome'].upper()}]")

    print(f"\n  Voyages dispatched : {sim['summary']['voyage_count']}")
    print(f"  Wins / losses      : {sim['summary']['wins']} / {sim['summary']['losses']}")
    print(f"  Total expected     : ${sim['summary']['total_expected_margin_usd']:,.0f}")
    print(f"  Total realized     : ${sim['summary']['total_realized_margin_usd']:,.0f}")
    print(f"  Surprise (real-exp): ${sim['summary']['surprise_usd']:,.0f}")

    print("\nOK")
