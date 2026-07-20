# core/pnl.py
# Economic destination selection: net margin per (cargo, vessel, destination).
#
# DES cargoes let the seller choose the discharge terminal that maximizes
# net margin (JKM vs TTF arbitrage). FOB cargoes have a fixed destination
# (buyer nominates) — the margin is still computed, but there's nothing to
# choose.
#
# Phase 1 scope: destination choice is optimized economically for an
# assignment already fixed by priority (core/optimizer.py). Coupling
# vessel+destination in a single MILP objective is a Phase 2 extension —
# see CONTEXT.md.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta

from config import TERMINAL_PRICE_MARKER, FREIGHT_RATE_USD_PER_DAY, DEMURRAGE_RATE
from core.routing import build_route, haversine_nm
from core.physics import calculate_eta, calculate_boiloff, calculate_demurrage
from core.constraints import check_draft_compatibility, check_laycan_compliance
from core.market import get_market_snapshot


# ---------------------------------------------------------------------------
# Margin for one (cargo, vessel, destination) combination
# ---------------------------------------------------------------------------

def calculate_cargo_margin(cargo, vessel, loading_terminal, destination_terminal,
                            closed_chokepoints=None, market_snapshot=None):
    """
    Full P&L for delivering `cargo`, carried by `vessel`, from
    `loading_terminal` to `destination_terminal`.

    market_snapshot (core.market.get_market_snapshot() shape) lets callers
    fetch prices once and reuse them across many calls — if omitted, a
    fallback snapshot is fetched here (no live network call by default).

    Returns a dict. When infeasible (draft or blocked route): {feasible: False, reason, destination_id}.
    When feasible: feasible=True plus the full cost breakdown and net_margin_usd.
    """
    draft = check_draft_compatibility(vessel["vessel_class"], destination_terminal["max_draft_m"])
    if not draft["compatible"]:
        return {"feasible": False, "reason": "draft incompatible at destination",
                "destination_id": destination_terminal["id"]}

    route = build_route(loading_terminal, destination_terminal, closed_chokepoints)
    if route["blocked"]:
        return {"feasible": False, "reason": "route blocked by closed chokepoint",
                "destination_id": destination_terminal["id"]}

    if market_snapshot is None:
        market_snapshot = get_market_snapshot()

    marker = TERMINAL_PRICE_MARKER[destination_terminal["id"]]
    price = market_snapshot[marker]["price_usd_mmbtu"]

    loading_start = datetime.fromisoformat(cargo["laycan_start"])
    loading_end   = loading_start + timedelta(hours=24)

    eta = calculate_eta(
        departure_date_iso=loading_end.isoformat(timespec="minutes"),
        distance_nm=route["distance_nm"],
        speed_knots=vessel["speed_knots"],
        weather_delay_hours=route["weather_delay_hours"],
        canal_delay_hours=route["canal_delay_hours"],
    )

    bog = calculate_boiloff(
        cargo_volume_mmbtu=cargo["volume_mmbtu"],
        transit_days=eta["transit_days"],
        vessel_class=vessel["vessel_class"],
        ambient_temp_celsius=28.0,
    )

    revenue_usd        = cargo["volume_mmbtu"] * price
    bog_cost_usd        = bog["gross_bog_mmbtu"] * price
    net_bog_cost_usd    = bog_cost_usd - bog["bunker_saving_usd"]
    transport_cost_usd  = FREIGHT_RATE_USD_PER_DAY[vessel["vessel_class"]] * eta["transit_days"]
    canal_toll_usd       = route["canal_toll_usd"]

    # Demurrage: is the vessel late arriving at the loading terminal?
    dist_to_load = haversine_nm(
        vessel["current_lat"], vessel["current_lon"],
        loading_terminal["lat"], loading_terminal["lon"],
    )
    eta_to_load = calculate_eta(
        departure_date_iso=vessel["available_from"],
        distance_nm=max(dist_to_load, 1.0),
        speed_knots=vessel["speed_knots"],
    )
    laycan = check_laycan_compliance(
        eta_iso=eta_to_load["eta_iso"],
        laycan_start_iso=cargo["laycan_start"],
        laycan_end_iso=cargo["laycan_end"],
    )
    if laycan["demurrage_risk"]:
        daily_rate = cargo.get("demurrage_rate_usd_day", DEMURRAGE_RATE[vessel["vessel_class"]])
        demurrage_usd = calculate_demurrage(laycan["delay_hours"], daily_rate)["demurrage_usd"]
    else:
        demurrage_usd = 0.0

    net_margin_usd = revenue_usd - net_bog_cost_usd - transport_cost_usd - canal_toll_usd - demurrage_usd

    return {
        "feasible":           True,
        "destination_id":     destination_terminal["id"],
        "price_marker":       marker,
        "price_usd_mmbtu":    price,
        "transit_days":       eta["transit_days"],
        "revenue_usd":        round(revenue_usd, 2),
        "gross_bog_mmbtu":    bog["gross_bog_mmbtu"],
        "bog_cost_usd":       round(bog_cost_usd, 2),
        "bunker_saving_usd":  bog["bunker_saving_usd"],
        "net_bog_cost_usd":   round(net_bog_cost_usd, 2),
        "transport_cost_usd": round(transport_cost_usd, 2),
        "canal_toll_usd":     round(canal_toll_usd, 2),
        "demurrage_usd":      round(demurrage_usd, 2),
        "net_margin_usd":     round(net_margin_usd, 2),
    }


# ---------------------------------------------------------------------------
# Best destination for a cargo
# ---------------------------------------------------------------------------

def best_destination_for_cargo(cargo, vessel, terminals_by_id, closed_chokepoints=None, market_snapshot=None):
    """
    Test every candidate destination for `cargo` and return the one that
    maximizes net margin.

    Candidates are [discharge_terminal] for fixed (FOB) cargoes, or
    possible_destinations for flexible (DES) cargoes.

    Returns a dict with:
      chosen     : margin dict of the winning destination (None if none feasible)
      candidates : all feasible candidates, sorted by net_margin_usd descending
    """
    if market_snapshot is None:
        market_snapshot = get_market_snapshot()

    loading_terminal = terminals_by_id[cargo["loading_terminal"]]
    candidate_ids = [cargo["discharge_terminal"]] if cargo.get("discharge_terminal") \
                    else cargo["possible_destinations"]

    all_results = [
        calculate_cargo_margin(cargo, vessel, loading_terminal, terminals_by_id[dest_id],
                                closed_chokepoints, market_snapshot)
        for dest_id in candidate_ids
    ]
    feasible = sorted(
        (r for r in all_results if r["feasible"]),
        key=lambda r: r["net_margin_usd"], reverse=True,
    )

    return {
        "cargo_id":   cargo["id"],
        "vessel_id":  vessel["id"],
        "chosen":     feasible[0] if feasible else None,
        "candidates": feasible,
        "infeasible": [r for r in all_results if not r["feasible"]],
    }


# ---------------------------------------------------------------------------
# Human-readable explanation
# ---------------------------------------------------------------------------

def format_decision_text(cargo_id, result):
    """Explain a destination decision, e.g. for display in the UI."""
    if result["chosen"] is None:
        return f"{cargo_id} -> NO FEASIBLE DESTINATION"

    best = result["candidates"][0]
    lines = [f"{cargo_id} -> {best['destination_id']}"]

    price_line = " | ".join(
        f"{c['price_marker']} ({c['destination_id']}) = ${c['price_usd_mmbtu']}/mmBtu"
        for c in result["candidates"]
    )
    lines.append(price_line)

    margin_line = " | ".join(
        f"Margin {c['destination_id']} = {c['net_margin_usd']/1e6:+.1f}M$"
        for c in result["candidates"]
    )
    lines.append(margin_line)

    if len(result["candidates"]) > 1:
        second = result["candidates"][1]
        delta = (best["net_margin_usd"] - second["net_margin_usd"]) / 1e6
        lines.append(f"Decision: {best['destination_id']} (+{delta:.1f}M$ vs {second['destination_id']})")
    else:
        lines.append(f"Decision: {best['destination_id']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Enrich a full assignment list with resolved destinations + margins
# ---------------------------------------------------------------------------

def enrich_assignments_with_pnl(assignments, cargoes, vessels, terminals, closed_chokepoints=None, market_snapshot=None):
    """
    For each {cargo_id, vessel_id} assignment, resolve the best destination
    and attach the full margin breakdown.

    Prices are fetched once (core.market.get_market_snapshot()) and reused
    across every cargo in the batch — consistent pricing, one fetch instead
    of N. Pass an explicit market_snapshot when comparing two runs (e.g. a
    disruption baseline vs scenario, see core/disruption.py) so both are
    priced identically and any $ delta reflects only the disruption itself.

    Returns a list of dicts: cargo_id, vessel_id, discharge_terminal,
    feasible, margin (None if infeasible), candidates.
    """
    cargoes_by_id   = {c["id"]: c for c in cargoes}
    vessels_by_id   = {v["id"]: v for v in vessels}
    terminals_by_id = {t["id"]: t for t in terminals}
    if market_snapshot is None:
        market_snapshot = get_market_snapshot()

    enriched = []
    for a in assignments:
        cargo  = cargoes_by_id[a["cargo_id"]]
        vessel = vessels_by_id[a["vessel_id"]]
        result = best_destination_for_cargo(cargo, vessel, terminals_by_id, closed_chokepoints, market_snapshot)

        enriched.append({
            "cargo_id":           a["cargo_id"],
            "vessel_id":          a["vessel_id"],
            "discharge_terminal": result["chosen"]["destination_id"] if result["chosen"] else None,
            "feasible":           result["chosen"] is not None,
            "margin":             result["chosen"],
            "candidates":         result["candidates"],
        })

    return enriched


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from data.cargoes   import CARGOES
    from data.vessels    import VESSELS
    from data.terminals import TERMINALS
    from core.optimizer  import assign_cargoes

    print("=== core/pnl.py ===")

    terminals_by_id = {t["id"]: t for t in TERMINALS}
    cargoes_by_id    = {c["id"]: c for c in CARGOES}
    vessels_by_id    = {v["id"]: v for v in VESSELS}

    result = assign_cargoes(CARGOES, VESSELS, TERMINALS)
    assigned_vessel_id = {a["cargo_id"]: a["vessel_id"] for a in result["assignments"]}

    # LNG-C01 (normal DES case) and LNG-C04 (tight short-haul DES case)
    for cargo_id in ["LNG-C01", "LNG-C04"]:
        cargo  = cargoes_by_id[cargo_id]
        vessel = vessels_by_id[assigned_vessel_id[cargo_id]]
        decision = best_destination_for_cargo(cargo, vessel, terminals_by_id)
        print(f"\n-- {cargo_id} ({vessel['id']}) --")
        print(format_decision_text(cargo_id, decision))

    print("\n-- Fleet-wide enrichment --")
    enriched = enrich_assignments_with_pnl(result["assignments"], CARGOES, VESSELS, TERMINALS)
    total_margin = 0.0
    for e in enriched:
        if e["feasible"]:
            total_margin += e["margin"]["net_margin_usd"]
            print(f"  {e['cargo_id']:<10} -> {e['vessel_id']:<16} -> {e['discharge_terminal']:<16} "
                  f"margin=${e['margin']['net_margin_usd']:,.0f}")
        else:
            print(f"  {e['cargo_id']:<10} -> {e['vessel_id']:<16} -> NO FEASIBLE DESTINATION")

    print(f"\n  Total fleet net margin: ${total_margin:,.0f}")

    print("\nOK")
