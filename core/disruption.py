# core/disruption.py
# Disruption simulation: apply a delay to a vessel or take a terminal offline.
# Recalculates ETAs and detects cascading impacts on assignments.
#
# Future: add route disruption (weather, canal closure, piracy zone).

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from core.physics import calculate_eta
from core.constraints import check_laycan_compliance
from core.optimizer import assign_cargoes
from core.pnl import enrich_assignments_with_pnl
from core.market import get_market_snapshot


# ---------------------------------------------------------------------------
# Vessel delay
# ---------------------------------------------------------------------------

def apply_vessel_delay(vessel, cargo, route, delay_hours):
    """
    Apply a delay to a vessel and recalculate the impact on its cargo.

    'route' must be the route from the vessel's CURRENT position to the
    cargo's loading terminal (not the full loading -> discharge voyage) —
    otherwise the ETA is compared against the wrong leg of the trip.

    Returns a dict with:
      new_eta_iso       : recalculated ETA at loading terminal
      laycan_status     : ON_TIME / EARLY / LATE after delay
      delay_hours       : hours late on laycan (0 if not late)
      demurrage_risk    : True if vessel will arrive after laycan_end
    """
    original_departure = datetime.fromisoformat(vessel["available_from"])
    delayed_departure  = original_departure + timedelta(hours=delay_hours)

    eta = calculate_eta(
        departure_date_iso=delayed_departure.isoformat(timespec="minutes"),
        distance_nm=route["distance_nm"],
        speed_knots=vessel["ballast_speed_knots"],   # current position -> loading terminal: ballast leg
        weather_delay_hours=route["weather_delay_hours"],
        canal_delay_hours=route["canal_delay_hours"],
    )

    laycan = check_laycan_compliance(
        eta_iso=eta["eta_iso"],
        laycan_start_iso=cargo["laycan_start"],
        laycan_end_iso=cargo["laycan_end"],
    )

    return {
        "vessel_id":      vessel["id"],
        "cargo_id":       cargo["id"],
        "delay_hours":    delay_hours,
        "new_eta_iso":    eta["eta_iso"],
        "laycan_status":  laycan["status"],
        "hours_late":     laycan["delay_hours"],
        "demurrage_risk": laycan["demurrage_risk"],
    }


# ---------------------------------------------------------------------------
# Terminal offline
# ---------------------------------------------------------------------------

def apply_terminal_offline(terminal, cargoes, offline_start_iso, offline_end_iso):
    """
    Take a terminal offline for a period and identify all affected cargoes.

    A cargo is affected if its loading or discharge terminal matches
    AND its laycan window overlaps with the offline period.

    Returns a dict with:
      terminal_id     : terminal taken offline
      offline_start   : start of offline period
      offline_end     : end of offline period
      affected_cargoes: list of {cargo_id, reason}
      clear_cargoes   : list of cargo_ids not impacted
    """
    offline_start = datetime.fromisoformat(offline_start_iso)
    offline_end   = datetime.fromisoformat(offline_end_iso)

    affected = []
    clear    = []

    for cargo in cargoes:
        is_loading_terminal   = cargo["loading_terminal"] == terminal["id"]
        is_discharge_terminal = (cargo.get("discharge_terminal") == terminal["id"]
                                  or terminal["id"] in cargo.get("possible_destinations", []))

        if not is_loading_terminal and not is_discharge_terminal:
            clear.append(cargo["id"])
            continue

        # Check if the laycan window overlaps with offline period
        laycan_start = datetime.fromisoformat(cargo["laycan_start"])
        laycan_end   = datetime.fromisoformat(cargo["laycan_end"])
        overlap      = laycan_start < offline_end and offline_start < laycan_end

        if overlap:
            role = "loading" if is_loading_terminal else "discharge"
            affected.append({
                "cargo_id": cargo["id"],
                "reason":   f"{role} terminal {terminal['id']} offline during laycan",
            })
        else:
            clear.append(cargo["id"])

    return {
        "terminal_id":      terminal["id"],
        "offline_start":    offline_start_iso,
        "offline_end":      offline_end_iso,
        "affected_cargoes": affected,
        "clear_cargoes":    clear,
    }


# ---------------------------------------------------------------------------
# Terminal offline -> cargo list transformation
# ---------------------------------------------------------------------------

def apply_terminal_offline_to_cargoes(terminal, cargoes, offline_start_iso, offline_end_iso):
    """
    Turn a terminal-offline period into a modified cargo list, ready to feed
    into assign_cargoes(). Never mutates the input cargoes — CARGOES is a
    module-level list shared by every Streamlit page, mutating in place
    would leak the disruption into every other page in the session.

    A cargo whose loading terminal is offline, or whose only possible
    destination (fixed FOB, or the last remaining DES candidate) is offline,
    can't be served at all and is dropped. A DES cargo with several
    candidate destinations just loses that one option and stays in the list.

    Returns a dict with:
      cargoes              : new cargo list (drop-in replacement for CARGOES)
      dropped               : [{cargo_id, reason}] cargoes entirely unservable
      destination_removed   : [{cargo_id, removed_destination}] DES cargoes
                               that lost one option but remain servable
    """
    overlap_check = apply_terminal_offline(terminal, cargoes, offline_start_iso, offline_end_iso)
    affected_ids = {a["cargo_id"] for a in overlap_check["affected_cargoes"]}

    new_cargoes = []
    dropped = []
    destination_removed = []

    for cargo in cargoes:
        if cargo["id"] not in affected_ids:
            new_cargoes.append(cargo)
            continue

        if cargo["loading_terminal"] == terminal["id"]:
            dropped.append({"cargo_id": cargo["id"], "reason": f"loading terminal {terminal['id']} offline"})
            continue

        if cargo.get("discharge_terminal") == terminal["id"]:
            dropped.append({"cargo_id": cargo["id"], "reason": f"fixed destination {terminal['id']} offline"})
            continue

        remaining = [d for d in cargo.get("possible_destinations", []) if d != terminal["id"]]
        if not remaining:
            dropped.append({"cargo_id": cargo["id"], "reason": "all possible destinations offline"})
            continue

        new_cargo = dict(cargo)
        new_cargo["possible_destinations"] = remaining
        new_cargoes.append(new_cargo)
        destination_removed.append({"cargo_id": cargo["id"], "removed_destination": terminal["id"]})

    return {"cargoes": new_cargoes, "dropped": dropped, "destination_removed": destination_removed}


# ---------------------------------------------------------------------------
# Vessel delay -> vessel list transformation
# ---------------------------------------------------------------------------

def apply_vessel_delay_to_vessels(vessels, vessel_id, delay_hours):
    """
    Return a copy of `vessels` where vessel_id's available_from is pushed
    back by delay_hours. Feeds directly into assign_cargoes() /
    enrich_assignments_with_pnl(), which already read available_from for
    reachability, ETA and demurrage — no logic duplicated here. Never
    mutates the input list (see apply_terminal_offline_to_cargoes).
    """
    delayed = []
    for vessel in vessels:
        if vessel["id"] != vessel_id:
            delayed.append(vessel)
            continue
        new_available_from = (datetime.fromisoformat(vessel["available_from"])
                               + timedelta(hours=delay_hours)).isoformat(timespec="minutes")
        delayed.append({**vessel, "available_from": new_available_from})
    return delayed


# ---------------------------------------------------------------------------
# Fleet-wide impact simulation
# ---------------------------------------------------------------------------

def simulate_disruption_impact(cargoes, vessels, terminals, scenario_cargoes=None,
                                scenario_vessels=None, scenario_closed_chokepoints=None,
                                market_snapshot=None):
    """
    Compare a baseline (no disruption) fleet run against a disrupted
    scenario, both priced with the same market_snapshot so the $ delta
    reflects only the disruption, never market noise.

    Returns a dict with:
      baseline / scenario   : {"total_margin_usd", "enriched"}
      delta_usd, delta_pct
      cargo_diffs            : per-cargo comparison, "changed" flag
      newly_unassigned_with_priority : [(cargo_id, priority)] assigned in
                                        baseline, unassigned in scenario
    """
    if market_snapshot is None:
        market_snapshot = get_market_snapshot()

    cargoes_by_id = {c["id"]: c for c in cargoes}

    baseline_result   = assign_cargoes(cargoes, vessels, terminals)
    baseline_enriched = enrich_assignments_with_pnl(
        baseline_result["assignments"], cargoes, vessels, terminals, market_snapshot=market_snapshot)

    scenario_result = assign_cargoes(
        scenario_cargoes if scenario_cargoes is not None else cargoes,
        scenario_vessels if scenario_vessels is not None else vessels,
        terminals,
        scenario_closed_chokepoints,
    )
    scenario_enriched = enrich_assignments_with_pnl(
        scenario_result["assignments"],
        scenario_cargoes if scenario_cargoes is not None else cargoes,
        scenario_vessels if scenario_vessels is not None else vessels,
        terminals, scenario_closed_chokepoints, market_snapshot=market_snapshot)

    baseline_by_cargo = {e["cargo_id"]: e for e in baseline_enriched if e["feasible"]}
    scenario_by_cargo  = {e["cargo_id"]: e for e in scenario_enriched  if e["feasible"]}

    baseline_total = sum(e["margin"]["net_margin_usd"] for e in baseline_by_cargo.values())
    scenario_total  = sum(e["margin"]["net_margin_usd"] for e in scenario_by_cargo.values())
    delta_usd = scenario_total - baseline_total
    delta_pct = (delta_usd / baseline_total * 100) if baseline_total else 0.0

    cargo_diffs = []
    all_cargo_ids = {c["id"] for c in cargoes} | set(baseline_by_cargo) | set(scenario_by_cargo)
    for cargo_id in sorted(all_cargo_ids):
        b = baseline_by_cargo.get(cargo_id)
        s = scenario_by_cargo.get(cargo_id)
        b_margin = b["margin"]["net_margin_usd"] if b else 0.0
        s_margin = s["margin"]["net_margin_usd"] if s else 0.0
        changed = (b is None) != (s is None) or (b and s and (
            b["vessel_id"] != s["vessel_id"] or b["discharge_terminal"] != s["discharge_terminal"]))
        cargo_diffs.append({
            "cargo_id":              cargo_id,
            "priority":              cargoes_by_id.get(cargo_id, {}).get("priority"),
            "baseline_vessel":       b["vessel_id"] if b else None,
            "baseline_destination":  b["discharge_terminal"] if b else None,
            "baseline_margin_usd":   b_margin,
            "scenario_vessel":       s["vessel_id"] if s else None,
            "scenario_destination":  s["discharge_terminal"] if s else None,
            "scenario_margin_usd":   s_margin,
            "margin_delta_usd":      s_margin - b_margin,
            "changed":               bool(changed),
        })

    newly_unassigned_with_priority = [
        (cid, cargoes_by_id[cid]["priority"])
        for cid in baseline_by_cargo
        if cid not in scenario_by_cargo and cid in cargoes_by_id
    ]

    return {
        "baseline":  {"total_margin_usd": baseline_total, "enriched": baseline_enriched},
        "scenario":  {"total_margin_usd": scenario_total,  "enriched": scenario_enriched},
        "delta_usd": delta_usd,
        "delta_pct": delta_pct,
        "cargo_diffs": cargo_diffs,
        "newly_unassigned_with_priority": newly_unassigned_with_priority,
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from data.vessels   import VESSELS
    from data.cargoes   import CARGOES
    from data.terminals import TERMINALS
    from core.routing   import build_route

    print("=== core/disruption.py ===")

    # --- Vessel delay ---
    vessel = next(v for v in VESSELS if v["id"] == "VESSEL-QF-01")
    cargo  = next(c for c in CARGOES if c["id"] == "LNG-C01")
    terms  = {t["id"]: t for t in TERMINALS}

    vessel_position = {"id": vessel["id"], "lat": vessel["current_lat"], "lon": vessel["current_lon"]}
    route = build_route(vessel_position, terms[cargo["loading_terminal"]])

    print(f"\n-- Vessel delay --")
    print(f"  Vessel : {vessel['id']}")
    print(f"  Cargo  : {cargo['id']}  laycan {cargo['laycan_start']} -> {cargo['laycan_end']}")

    for delay in [0, 12, 24, 48]:
        r = apply_vessel_delay(vessel, cargo, route, delay_hours=delay)
        print(f"  +{delay:>2}h delay -> ETA {r['new_eta_iso']}  "
              f"laycan={r['laycan_status']:<8} "
              f"{'DEMURRAGE RISK' if r['demurrage_risk'] else ''}")

    # --- Terminal offline ---
    terminal = next(t for t in TERMINALS if t["id"] == "RAS-LAFFAN")

    print(f"\n-- Terminal offline --")
    print(f"  Terminal: {terminal['id']}  offline 2025-03-02T00:00 -> 2025-03-04T00:00\n")

    result = apply_terminal_offline(
        terminal=terminal,
        cargoes=CARGOES,
        offline_start_iso="2025-03-02T00:00",
        offline_end_iso="2025-03-04T00:00",
    )

    print(f"  Affected ({len(result['affected_cargoes'])}):")
    for a in result["affected_cargoes"]:
        print(f"    {a['cargo_id']:<10} : {a['reason']}")

    print(f"\n  Not affected ({len(result['clear_cargoes'])}):")
    for c_id in result["clear_cargoes"]:
        print(f"    {c_id}")

    # --- Fleet-wide impact: terminal offline ---
    print(f"\n-- Fleet impact: {terminal['id']} offline 2025-03-01T00:00 -> 2025-03-04T00:00 --")
    offline_transform = apply_terminal_offline_to_cargoes(
        terminal, CARGOES, "2025-03-01T00:00", "2025-03-04T00:00")
    print(f"  Dropped ({len(offline_transform['dropped'])}): "
          f"{[d['cargo_id'] for d in offline_transform['dropped']]}")
    print(f"  Destination removed ({len(offline_transform['destination_removed'])}): "
          f"{[d['cargo_id'] for d in offline_transform['destination_removed']]}")

    impact = simulate_disruption_impact(
        CARGOES, VESSELS, TERMINALS, scenario_cargoes=offline_transform["cargoes"])
    print(f"  Baseline margin : ${impact['baseline']['total_margin_usd']:,.0f}")
    print(f"  Scenario margin : ${impact['scenario']['total_margin_usd']:,.0f}")
    print(f"  Delta           : ${impact['delta_usd']:,.0f} ({impact['delta_pct']:+.1f}%)")
    for cid, priority in impact["newly_unassigned_with_priority"]:
        print(f"  ! {cid} (priority={priority}) newly UNASSIGNED under this disruption")

    # --- Fleet-wide impact: vessel delay ---
    print(f"\n-- Fleet impact: {vessel['id']} delayed 200h --")
    delayed_vessels = apply_vessel_delay_to_vessels(VESSELS, vessel["id"], 200)
    impact2 = simulate_disruption_impact(CARGOES, VESSELS, TERMINALS, scenario_vessels=delayed_vessels)
    print(f"  Baseline margin : ${impact2['baseline']['total_margin_usd']:,.0f}")
    print(f"  Scenario margin : ${impact2['scenario']['total_margin_usd']:,.0f}")
    print(f"  Delta           : ${impact2['delta_usd']:,.0f} ({impact2['delta_pct']:+.1f}%)")
    for cid, priority in impact2["newly_unassigned_with_priority"]:
        print(f"  ! {cid} (priority={priority}) newly UNASSIGNED under this disruption")

    print("\nOK")
