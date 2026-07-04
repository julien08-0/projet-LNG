# core/optimizer.py
# Cargo -> vessel assignment.
#
# Uses dynamic routing (core/routing.py) — no hardcoded routes.
# Any terminal pair is valid. The optimizer picks the best assignment
# across all possible cargo/vessel/destination combinations.
#
# Two solvers:
#   assign_cargoes_greedy : greedy baseline, no dependencies
#   assign_cargoes_milp   : MILP via PuLP (pip install pulp)
#
# assign_cargoes() uses MILP if available, greedy otherwise.

import sys
import os
import math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from core.constraints import check_draft_compatibility
from core.routing import build_route, haversine_nm


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
    if closed_chokepoints:
        discharge_term = terminals_by_id[cargo["discharge_terminal"]]
        route = build_route(loading_term, discharge_term, closed_chokepoints)
        if route["blocked"]:
            return False, "route blocked by closed chokepoint"

    return True, "ok"


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
# Solver 2 — MILP
# ---------------------------------------------------------------------------

def assign_cargoes_milp(cargoes, vessels, terminals, closed_chokepoints=None):
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
# Public entry point
# ---------------------------------------------------------------------------

def assign_cargoes(cargoes, vessels, terminals, closed_chokepoints=None):
    """Uses MILP if PuLP available, greedy otherwise."""
    try:
        import pulp
        return assign_cargoes_milp(cargoes, vessels, terminals, closed_chokepoints)
    except ImportError:
        return assign_cargoes_greedy(cargoes, vessels, terminals, closed_chokepoints)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from data.cargoes   import CARGOES
    from data.vessels   import VESSELS
    from data.terminals import TERMINALS

    print("=== core/optimizer.py ===\n")

    result = assign_cargoes(CARGOES, VESSELS, TERMINALS)

    print("-- Assignments --")
    for a in result["assignments"]:
        print(f"  {a['cargo_id']:<10} -> {a['vessel_id']}")
    for u in result["unassigned"]:
        print(f"  {u['cargo_id']:<10} UNASSIGNED: {u['reason']}")

    print("\n-- Disruption: Suez closed --")
    result_suez = assign_cargoes(CARGOES, VESSELS, TERMINALS, closed_chokepoints={"SUEZ"})
    for a in result_suez["assignments"]:
        print(f"  {a['cargo_id']:<10} -> {a['vessel_id']}")
    for u in result_suez["unassigned"]:
        print(f"  {u['cargo_id']:<10} UNASSIGNED")

    print("\nOK")
