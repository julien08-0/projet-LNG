# core/optimizer.py
# Cargo -> vessel assignment.
#
# Two solvers available:
#   - assign_cargoes_greedy : simple greedy, no dependency, always works
#   - assign_cargoes_milp   : Mixed Integer Linear Programming (PuLP)
#                             maximises total priority delivered
#                             subject to all physical constraints
#
# assign_cargoes() is the public entry point — uses MILP if PuLP is available,
# falls back to greedy otherwise.

import sys
import os
import math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from core.constraints import check_draft_compatibility


def haversine_nm(lat1, lon1, lat2, lon2):
    R = 3440.065
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Shared: compatibility check
# ---------------------------------------------------------------------------

def _is_compatible(vessel, cargo, terminals_by_id):
    """
    Return (compatible: bool, reason: str).
    Checks capacity, draft, and availability against laycan_start.
    """
    LNG_ENERGY_DENSITY = 21.0

    # Capacity
    vessel_capacity_mmbtu = vessel["capacity_m3"] * LNG_ENERGY_DENSITY
    if vessel_capacity_mmbtu < cargo["volume_mmbtu"]:
        return False, "capacity too small"

    # Draft
    loading_terminal = terminals_by_id[cargo["loading_terminal"]]
    draft = check_draft_compatibility(vessel["vessel_class"], loading_terminal["max_draft_m"])
    if not draft["compatible"]:
        return False, "draft incompatible"

    # Availability + reachability
    # Vessel must reach the loading terminal before laycan_end
    vessel_available = datetime.fromisoformat(vessel["available_from"])
    laycan_end       = datetime.fromisoformat(cargo["laycan_end"])
    loading_term     = terminals_by_id[cargo["loading_terminal"]]
    dist_nm          = haversine_nm(
        vessel["current_lat"], vessel["current_lon"],
        loading_term["lat"],   loading_term["lon"],
    )
    transit_days     = dist_nm / vessel["speed_knots"] / 24.0
    earliest_arrival = vessel_available + timedelta(days=transit_days)
    if earliest_arrival > laycan_end:
        return False, f"cannot reach {cargo['loading_terminal']} before laycan end"

    return True, "ok"


# ---------------------------------------------------------------------------
# Solver 1 — Greedy (baseline, no dependencies)
# ---------------------------------------------------------------------------

def assign_cargoes_greedy(cargoes, vessels, terminals):
    """
    Greedy assignment: process cargoes by priority (highest first),
    pick the first compatible vessel available.

    O(C × V) — fast but suboptimal.
    """
    terminals_by_id   = {t["id"]: t for t in terminals}
    sorted_cargoes    = sorted(cargoes, key=lambda c: c["priority"], reverse=True)
    assigned_vessel_ids = set()
    assignments = []
    unassigned  = []

    for cargo in sorted_cargoes:
        chosen = None
        reasons = []

        for vessel in vessels:
            if vessel["id"] in assigned_vessel_ids:
                reasons.append(f"{vessel['id']}: already assigned")
                continue
            ok, reason = _is_compatible(vessel, cargo, terminals_by_id)
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
                               "reason": "; ".join(reasons) or "no vessels in fleet"})

    return {"assignments": assignments, "unassigned": unassigned}


# ---------------------------------------------------------------------------
# Solver 2 — MILP with PuLP (optimal)
# ---------------------------------------------------------------------------

def assign_cargoes_milp(cargoes, vessels, terminals):
    """
    MILP assignment: maximise total priority of assigned cargoes
    subject to:
      - each cargo assigned to at most one vessel
      - each vessel assigned to at most one cargo
      - only compatible (cargo, vessel) pairs allowed

    Decision variables:
      x[c][v] ∈ {0, 1}  — 1 if cargo c is assigned to vessel v

    Objective:
      maximise Σ priority[c] × x[c][v]

    This is the classic assignment problem, solvable in polynomial time
    via the Hungarian algorithm, but we use MILP here because we will
    add non-linear constraints later (boil-off, demurrage penalties).
    """
    import pulp

    terminals_by_id = {t["id"]: t for t in terminals}

    # Build compatibility matrix
    compatible = {}
    for cargo in cargoes:
        for vessel in vessels:
            ok, _ = _is_compatible(vessel, cargo, terminals_by_id)
            compatible[(cargo["id"], vessel["id"])] = ok

    # Decision variables
    x = {
        (c["id"], v["id"]): pulp.LpVariable(f"x_{c['id']}_{v['id']}", cat="Binary")
        for c in cargoes
        for v in vessels
    }

    # Problem
    prob = pulp.LpProblem("cargo_vessel_assignment", pulp.LpMaximize)

    # Objective: maximise total priority delivered
    prob += pulp.lpSum(
        c["priority"] * x[(c["id"], v["id"])]
        for c in cargoes
        for v in vessels
        if compatible[(c["id"], v["id"])]
    )

    # Constraint 1: each cargo assigned to at most one vessel
    for c in cargoes:
        prob += pulp.lpSum(x[(c["id"], v["id"])] for v in vessels) <= 1

    # Constraint 2: each vessel assigned to at most one cargo
    for v in vessels:
        prob += pulp.lpSum(x[(c["id"], v["id"])] for c in cargoes) <= 1

    # Constraint 3: incompatible pairs forced to 0
    for c in cargoes:
        for v in vessels:
            if not compatible[(c["id"], v["id"])]:
                prob += x[(c["id"], v["id"])] == 0

    # Solve (suppress PuLP output)
    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    assignments = []
    unassigned  = []
    assigned_cargo_ids = set()

    for c in cargoes:
        assigned = False
        for v in vessels:
            if pulp.value(x[(c["id"], v["id"])]) == 1:
                assignments.append({"cargo_id": c["id"], "vessel_id": v["id"]})
                assigned_cargo_ids.add(c["id"])
                assigned = True
                break
        if not assigned:
            unassigned.append({"cargo_id": c["id"], "reason": "no feasible assignment (MILP)"})

    return {"assignments": assignments, "unassigned": unassigned}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def assign_cargoes(cargoes, vessels, terminals):
    """
    Public entry point. Uses MILP if PuLP is available, greedy otherwise.
    """
    try:
        import pulp
        return assign_cargoes_milp(cargoes, vessels, terminals)
    except ImportError:
        return assign_cargoes_greedy(cargoes, vessels, terminals)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from data.cargoes   import CARGOES
    from data.vessels   import VESSELS
    from data.terminals import TERMINALS

    print("=== core/optimizer.py ===")

    print("\n-- Greedy --")
    r1 = assign_cargoes_greedy(CARGOES, VESSELS, TERMINALS)
    for a in r1["assignments"]:
        print(f"  {a['cargo_id']:<10} -> {a['vessel_id']}")
    for u in r1["unassigned"]:
        print(f"  {u['cargo_id']:<10} UNASSIGNED: {u['reason']}")

    try:
        import pulp
        print("\n-- MILP (PuLP) --")
        r2 = assign_cargoes_milp(CARGOES, VESSELS, TERMINALS)
        for a in r2["assignments"]:
            print(f"  {a['cargo_id']:<10} -> {a['vessel_id']}")
        for u in r2["unassigned"]:
            print(f"  {u['cargo_id']:<10} UNASSIGNED")
        greedy_score = sum(c["priority"] for c in CARGOES
                           if c["id"] in {a["cargo_id"] for a in r1["assignments"]})
        milp_score   = sum(c["priority"] for c in CARGOES
                           if c["id"] in {a["cargo_id"] for a in r2["assignments"]})
        print(f"\n  Greedy total priority: {greedy_score}")
        print(f"  MILP   total priority: {milp_score}")
    except ImportError:
        print("\n-- MILP skipped (pip install pulp) --")

    print("\nOK")