# core/optimizer.py
# Cargo -> vessel assignment.
#
# Uses dynamic routing (core/routing.py) — no hardcoded routes.
# Any terminal pair is valid.
#
# Solvers:
#   assign_cargoes_greedy        : priority-based greedy, no dependencies
#   assign_cargoes_milp_priority : MILP maximizing total priority (Phase 1,
#                                  kept for side-by-side comparison in the
#                                  self-test — destination chosen separately
#                                  afterward by core/pnl.py)
#   assign_cargoes_milp_margin   : MILP maximizing total net margin — chooses
#                                  vessel AND destination together (Phase 2)
#
# assign_cargoes() is the sole public entry point: margin MILP if PuLP is
# available, priority-based greedy otherwise. Signature and return shape
# ({"assignments": [...], "unassigned": [...]}) never change, so no ui/ file
# needs to know which solver actually ran.

import sys
import os
import math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from core.constraints import check_draft_compatibility
from core.routing import build_route, haversine_nm
from core.pnl import best_destination_for_cargo
from core.market import get_market_snapshot


# ---------------------------------------------------------------------------
# Compatibility check
# ---------------------------------------------------------------------------

def _is_compatible(vessel, cargo, terminals_by_id, closed_chokepoints=None):
    """
    Return (compatible: bool, reason: str).
    Checks capacity, draft, reachability via dynamic routing.
    """
    LNG_ENERGY_DENSITY = 21.0

    # Capacity
    if vessel["capacity_m3"] * LNG_ENERGY_DENSITY < cargo["volume_mmbtu"]:
        return False, "capacity too small"

    # Draft at loading terminal
    loading_term = terminals_by_id[cargo["loading_terminal"]]
    draft = check_draft_compatibility(vessel["vessel_class"], loading_term["max_draft_m"])
    if not draft["compatible"]:
        return False, "draft incompatible"

    # Reachability: can vessel reach loading terminal before laycan_end?
    dist_nm = haversine_nm(
        vessel["current_lat"], vessel["current_lon"],
        loading_term["lat"],   loading_term["lon"],
    )
    transit_days     = dist_nm / vessel["speed_knots"] / 24.0
    vessel_available = datetime.fromisoformat(vessel["available_from"])
    earliest_arrival = vessel_available + timedelta(days=transit_days)
    laycan_end       = datetime.fromisoformat(cargo["laycan_end"])

    if earliest_arrival > laycan_end:
        return False, f"cannot reach {cargo['loading_terminal']} before laycan end"

    # Route feasibility (chokepoints)
    # For cargoes with a fixed discharge_terminal, that single leg must be
    # reachable. For flexible (DES) cargoes, at least one of the possible
    # destinations must remain reachable — the actual destination is chosen
    # later, economically, in core/pnl.py.
    if closed_chokepoints:
        candidates = [cargo["discharge_terminal"]] if cargo.get("discharge_terminal") \
                     else cargo.get("possible_destinations", [])
        reachable = any(
            not build_route(loading_term, terminals_by_id[dest_id], closed_chokepoints)["blocked"]
            for dest_id in candidates
        )
        if not reachable:
            return False, "no reachable destination given closed chokepoints"

    return True, "ok"


# ---------------------------------------------------------------------------
# Margin for one (cargo, vessel) pair — best destination included
# ---------------------------------------------------------------------------

def _margin_for_pair(cargo, vessel, terminals_by_id, closed_chokepoints, market_snapshot):
    """
    Return (feasible: bool, margin_usd: float|None, destination_id: str|None, reason: str).

    Two-stage filter: the cheap _is_compatible() check first (capacity,
    draft at loading, reachability) rules out most pairs before any
    routing/BOG/pricing math runs. Only survivors go through
    core.pnl.best_destination_for_cargo(), which also catches feasibility
    gaps _is_compatible() can't see (draft at the destination, per-candidate
    chokepoint blocking).
    """
    ok, reason = _is_compatible(vessel, cargo, terminals_by_id, closed_chokepoints)
    if not ok:
        return False, None, None, reason

    result = best_destination_for_cargo(cargo, vessel, terminals_by_id, closed_chokepoints, market_snapshot)
    if result["chosen"] is None:
        return False, None, None, "no feasible destination (draft or route blocked at every candidate)"

    return True, result["chosen"]["net_margin_usd"], result["chosen"]["destination_id"], "ok"


# ---------------------------------------------------------------------------
# Solver 1 — Greedy
# ---------------------------------------------------------------------------

def assign_cargoes_greedy(cargoes, vessels, terminals, closed_chokepoints=None):
    terminals_by_id     = {t["id"]: t for t in terminals}
    sorted_cargoes      = sorted(cargoes, key=lambda c: c["priority"], reverse=True)
    assigned_vessel_ids = set()
    assignments = []
    unassigned  = []

    for cargo in sorted_cargoes:
        chosen  = None
        reasons = []

        for vessel in vessels:
            if vessel["id"] in assigned_vessel_ids:
                reasons.append(f"{vessel['id']}: already assigned")
                continue
            ok, reason = _is_compatible(vessel, cargo, terminals_by_id, closed_chokepoints)
            if not ok:
                reasons.append(f"{vessel['id']}: {reason}")
                continue
            chosen = vessel
            break

        if chosen:
            assigned_vessel_ids.add(chosen["id"])
            assignments.append({"cargo_id": cargo["id"], "vessel_id": chosen["id"]})
        else:
            unassigned.append({"cargo_id": cargo["id"],
                               "reason": "; ".join(reasons) or "no vessels"})

    return {"assignments": assignments, "unassigned": unassigned}


# ---------------------------------------------------------------------------
# Solver 2 — MILP, priority-based (Phase 1)
# ---------------------------------------------------------------------------

def assign_cargoes_milp_priority(cargoes, vessels, terminals, closed_chokepoints=None):
    """
    Maximizes total priority. Destination is not considered here — it's
    chosen separately, afterward, by core/pnl.py. Kept for side-by-side
    comparison against assign_cargoes_milp_margin() in the self-test; no
    longer called by assign_cargoes().
    """
    import pulp

    terminals_by_id = {t["id"]: t for t in terminals}

    compatible = {}
    for cargo in cargoes:
        for vessel in vessels:
            ok, _ = _is_compatible(vessel, cargo, terminals_by_id, closed_chokepoints)
            compatible[(cargo["id"], vessel["id"])] = ok

    x = {
        (c["id"], v["id"]): pulp.LpVariable(f"x_{c['id']}_{v['id']}", cat="Binary")
        for c in cargoes for v in vessels
    }

    prob = pulp.LpProblem("cargo_vessel_assignment", pulp.LpMaximize)
    prob += pulp.lpSum(
        c["priority"] * x[(c["id"], v["id"])]
        for c in cargoes for v in vessels
        if compatible[(c["id"], v["id"])]
    )

    for c in cargoes:
        prob += pulp.lpSum(x[(c["id"], v["id"])] for v in vessels) <= 1
    for v in vessels:
        prob += pulp.lpSum(x[(c["id"], v["id"])] for c in cargoes) <= 1
    for c in cargoes:
        for v in vessels:
            if not compatible[(c["id"], v["id"])]:
                prob += x[(c["id"], v["id"])] == 0

    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    assignments = []
    unassigned  = []
    assigned_ids = set()

    for c in cargoes:
        assigned = False
        for v in vessels:
            if pulp.value(x[(c["id"], v["id"])]) == 1:
                assignments.append({"cargo_id": c["id"], "vessel_id": v["id"]})
                assigned_ids.add(c["id"])
                assigned = True
                break
        if not assigned:
            unassigned.append({"cargo_id": c["id"], "reason": "no feasible assignment (MILP)"})

    return {"assignments": assignments, "unassigned": unassigned}


# ---------------------------------------------------------------------------
# Solver 3 — MILP, net margin (Phase 2)
# ---------------------------------------------------------------------------

def assign_cargoes_milp_margin(cargoes, vessels, terminals, closed_chokepoints=None, market_snapshot=None):
    """
    Maximizes total net margin — chooses vessel AND destination together.
    The vessel that's individually best for one cargo might be better
    reserved for another cargo elsewhere in the fleet; this is exactly what
    a joint objective captures and a per-cargo-then-per-vessel approach
    can't.
    """
    import pulp

    terminals_by_id = {t["id"]: t for t in terminals}
    if market_snapshot is None:
        market_snapshot = get_market_snapshot()   # one fetch for the whole batch

    feasible = {}
    margin   = {}
    destination = {}
    reasons_by_cargo = {c["id"]: [] for c in cargoes}

    for c in cargoes:
        for v in vessels:
            ok, margin_usd, dest_id, reason = _margin_for_pair(
                c, v, terminals_by_id, closed_chokepoints, market_snapshot)
            feasible[(c["id"], v["id"])] = ok
            if ok:
                margin[(c["id"], v["id"])] = margin_usd
                destination[(c["id"], v["id"])] = dest_id
            else:
                reasons_by_cargo[c["id"]].append(f"{v['id']}: {reason}")

    x = {
        (c["id"], v["id"]): pulp.LpVariable(f"x_{c['id']}_{v['id']}", cat="Binary")
        for c in cargoes for v in vessels
    }

    prob = pulp.LpProblem("cargo_vessel_destination_assignment", pulp.LpMaximize)
    prob += pulp.lpSum(
        margin[(c["id"], v["id"])] * x[(c["id"], v["id"])]
        for c in cargoes for v in vessels
        if feasible[(c["id"], v["id"])]
    )

    for c in cargoes:
        prob += pulp.lpSum(x[(c["id"], v["id"])] for v in vessels) <= 1
    for v in vessels:
        prob += pulp.lpSum(x[(c["id"], v["id"])] for c in cargoes) <= 1
    for c in cargoes:
        for v in vessels:
            if not feasible[(c["id"], v["id"])]:
                prob += x[(c["id"], v["id"])] == 0

    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    assignments  = []
    unassigned   = []
    assigned_ids = set()

    for c in cargoes:
        assigned = False
        for v in vessels:
            if feasible[(c["id"], v["id"])] and pulp.value(x[(c["id"], v["id"])]) == 1:
                assignments.append({"cargo_id": c["id"], "vessel_id": v["id"]})
                assigned_ids.add(c["id"])
                assigned = True
                break
        if not assigned:
            feasible_vessels = [v["id"] for v in vessels if feasible[(c["id"], v["id"])]]
            if feasible_vessels:
                reason = (f"Not the most profitable use of the fleet today: {', '.join(feasible_vessels)} "
                          f"could carry this cargo, but the fleet earns more using them on higher-margin "
                          f"cargoes instead.")
            else:
                reason = "; ".join(reasons_by_cargo[c["id"]]) or "no vessels"
            unassigned.append({"cargo_id": c["id"], "reason": reason})

    return {"assignments": assignments, "unassigned": unassigned}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def assign_cargoes(cargoes, vessels, terminals, closed_chokepoints=None):
    """Uses the net-margin MILP if PuLP available, priority-based greedy otherwise."""
    try:
        import pulp
        return assign_cargoes_milp_margin(cargoes, vessels, terminals, closed_chokepoints)
    except ImportError:
        return assign_cargoes_greedy(cargoes, vessels, terminals, closed_chokepoints)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from data.cargoes    import CARGOES
    from data.vessels    import VESSELS
    from data.terminals  import TERMINALS
    from core.pnl        import enrich_assignments_with_pnl

    print("=== core/optimizer.py ===\n")

    cargoes_by_id = {c["id"]: c for c in CARGOES}

    # -- Phase 1 (priority-based) vs Phase 2 (margin-based), same data --
    result_priority = assign_cargoes_milp_priority(CARGOES, VESSELS, TERMINALS)
    result_margin   = assign_cargoes(CARGOES, VESSELS, TERMINALS)  # margin MILP (PuLP installed)

    enriched_priority = enrich_assignments_with_pnl(result_priority["assignments"], CARGOES, VESSELS, TERMINALS)
    enriched_margin    = enrich_assignments_with_pnl(result_margin["assignments"],    CARGOES, VESSELS, TERMINALS)

    margin_by_cargo_priority = {e["cargo_id"]: e for e in enriched_priority if e["feasible"]}
    margin_by_cargo_margin    = {e["cargo_id"]: e for e in enriched_margin    if e["feasible"]}

    print("-- Priority-based vs margin-based, per cargo --")
    print(f"  {'CARGO':<10} {'PRIORITY MILP':<38} {'MARGIN MILP':<38} {'CHANGED'}")
    for cargo in CARGOES:
        cid = cargo["id"]
        p = margin_by_cargo_priority.get(cid)
        m = margin_by_cargo_margin.get(cid)
        p_desc = f"{p['vessel_id']}->{p['discharge_terminal']} ${p['margin']['net_margin_usd']:,.0f}" if p else "UNASSIGNED"
        m_desc = f"{m['vessel_id']}->{m['discharge_terminal']} ${m['margin']['net_margin_usd']:,.0f}" if m else "UNASSIGNED"
        changed = "  <-- CHANGED" if (p is None) != (m is None) or (p and m and p["vessel_id"] != m["vessel_id"]) else ""
        print(f"  {cid:<10} {p_desc:<38} {m_desc:<38} {changed}")

    print("\n-- High-priority cargoes newly unassigned under margin objective --")
    newly_unassigned = [
        cid for cid in margin_by_cargo_priority
        if cid not in margin_by_cargo_margin and cargoes_by_id[cid]["priority"] >= 8
    ]
    if newly_unassigned:
        for cid in newly_unassigned:
            print(f"  ! WARNING: {cid} (priority={cargoes_by_id[cid]['priority']}) "
                  f"was assigned under priority MILP, unassigned under margin MILP")
    else:
        print("  none")

    total_priority = sum(e["margin"]["net_margin_usd"] for e in enriched_priority if e["feasible"])
    total_margin    = sum(e["margin"]["net_margin_usd"] for e in enriched_margin    if e["feasible"])
    gain = total_margin - total_priority
    gain_pct = (gain / total_priority * 100) if total_priority else 0.0

    print(f"\n  Total margin, priority-based MILP : ${total_priority:,.0f}")
    print(f"  Total margin, margin-based MILP   : ${total_margin:,.0f}")
    print(f"  Gain                              : ${gain:,.0f} ({gain_pct:+.1f}%)")

    print("\n-- Disruption: Suez closed (margin-based, default entry point) --")
    result_suez = assign_cargoes(CARGOES, VESSELS, TERMINALS, closed_chokepoints={"SUEZ"})
    for a in result_suez["assignments"]:
        print(f"  {a['cargo_id']:<10} -> {a['vessel_id']}")
    for u in result_suez["unassigned"]:
        print(f"  {u['cargo_id']:<10} UNASSIGNED: {u['reason']}")

    print("\nOK")
