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


# ---------------------------------------------------------------------------
# Vessel delay
# ---------------------------------------------------------------------------

def apply_vessel_delay(vessel, cargo, route, delay_hours):
    """
    Apply a delay to a vessel and recalculate the impact on its cargo.

    Returns a dict with:
      new_eta_iso       : recalculated ETA at loading terminal
      laycan_status     : ON_TIME / EARLY / LATE after delay
      delay_hours       : hours late on laycan (0 if not late)
      demurrage_risk    : True if vessel will arrive after laycan_end
    """
    original_departure = datetime.fromisoformat(cargo["laycan_start"])
    delayed_departure  = original_departure + timedelta(hours=delay_hours)

    eta = calculate_eta(
        departure_date_iso=delayed_departure.isoformat(timespec="minutes"),
        distance_nm=route["distance_nm"],
        speed_knots=vessel["speed_knots"],
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
        is_loading_terminal   = cargo["loading_terminal"]   == terminal["id"]
        is_discharge_terminal = cargo["discharge_terminal"] == terminal["id"]

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
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from data.vessels   import VESSELS
    from data.cargoes   import CARGOES
    from data.routes    import ROUTES
    from data.terminals import TERMINALS

    print("=== core/disruption.py ===")

    # --- Vessel delay ---
    vessel = next(v for v in VESSELS  if v["id"] == "VESSEL-QF-01")
    cargo  = next(c for c in CARGOES  if c["id"] == "LNG-C01")
    route  = next(r for r in ROUTES
                  if r["origin"] == cargo["loading_terminal"]
                  and r["destination"] == cargo["discharge_terminal"])

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

    print("\nOK")
