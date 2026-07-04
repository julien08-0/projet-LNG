# ui/alerts.py
# Alerts panel: detected conflicts across all assignments.
# Severity: CRITICAL (red), WARNING (orange), INFO (blue).

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from datetime import datetime, timedelta

from data.vessels   import VESSELS
from data.terminals import TERMINALS
from data.cargoes   import CARGOES

from core.optimizer  import assign_cargoes
from core.physics    import calculate_eta
from core.routing    import build_route, haversine_nm
from core.constraints import check_draft_compatibility, check_laycan_compliance, check_slot_overlap


def detect_alerts(assignments, cargoes, vessels, terminals):
    """
    Run all constraint checks on current assignments.
    """
    alerts = []

    cargoes_by_id   = {c["id"]: c for c in cargoes}
    vessels_by_id   = {v["id"]: v for v in vessels}
    terminals_by_id = {t["id"]: t for t in terminals}

    slots = []

    for a in assignments:
        cargo  = cargoes_by_id[a["cargo_id"]]
        vessel = vessels_by_id[a["vessel_id"]]
        loading_terminal = terminals_by_id[cargo["loading_terminal"]]

        # 1. Draft check
        draft = check_draft_compatibility(vessel["vessel_class"], loading_terminal["max_draft_m"])
        if not draft["compatible"]:
            alerts.append({
                "severity": "CRITICAL",
                "cargo_id":  cargo["id"],
                "vessel_id": vessel["id"],
                "message":  f"Draft incompatible: {vessel['vessel_class']} "
                            f"({draft['vessel_draft_m']}m) > {loading_terminal['id']} "
                            f"max ({draft['terminal_max_draft_m']}m)",
            })

        # 2. Laycan compliance
        # Calculate real ETA: from current vessel position to loading terminal
        dist_to_load = haversine_nm(
            vessel["current_lat"], vessel["current_lon"],
            loading_terminal["lat"], loading_terminal["lon"],
        )
        eta_to_load = calculate_eta(
            departure_date_iso=vessel["available_from"],
            distance_nm=max(dist_to_load, 1.0),  # avoid 0nm edge case
            speed_knots=vessel["speed_knots"],
        )
        laycan = check_laycan_compliance(
            eta_iso=eta_to_load["eta_iso"],
            laycan_start_iso=cargo["laycan_start"],
            laycan_end_iso=cargo["laycan_end"],
        )
        if laycan["status"] == "LATE":
            alerts.append({
                "severity": "CRITICAL",
                "cargo_id":  cargo["id"],
                "vessel_id": vessel["id"],
                "message":  f"Laycan breach: vessel arrives {laycan['delay_hours']:.1f}h "
                            f"after laycan end — demurrage risk",
            })
        elif laycan["status"] == "EARLY":
            alerts.append({
                "severity": "WARNING",
                "cargo_id":  cargo["id"],
                "vessel_id": vessel["id"],
                "message":  f"Early arrival: vessel waits {laycan['waiting_hours']:.1f}h "
                            f"at anchor — extra BOG loss",
            })

        # 3. Build slot for overlap check
        loading_start = datetime.fromisoformat(cargo["laycan_start"])
        loading_end   = loading_start + timedelta(hours=loading_terminal["avg_turnaround_hours"])
        slots.append({
            "cargo_id":    cargo["id"],
            "vessel_id":   vessel["id"],
            "terminal_id": cargo["loading_terminal"],
            "start_iso":   loading_start.isoformat(timespec="minutes"),
            "end_iso":     loading_end.isoformat(timespec="minutes"),
        })

    # 4. Slot overlap check (all pairs)
    for i in range(len(slots)):
        for j in range(i + 1, len(slots)):
            overlap = check_slot_overlap(slots[i], slots[j])
            if overlap["overlaps"]:
                alerts.append({
                    "severity": "CRITICAL",
                    "cargo_id":  f"{slots[i]['cargo_id']} & {slots[j]['cargo_id']}",
                    "vessel_id": f"{slots[i]['vessel_id']} & {slots[j]['vessel_id']}",
                    "message":  f"Slot conflict at {slots[i]['terminal_id']}: "
                                f"{slots[i]['cargo_id']} and {slots[j]['cargo_id']} "
                                f"overlap on the same berth",
                })

    # 5. Unassigned cargoes
    assigned_ids = {a["cargo_id"] for a in assignments}
    for cargo in cargoes:
        if cargo["id"] not in assigned_ids:
            alerts.append({
                "severity": "WARNING",
                "cargo_id":  cargo["id"],
                "vessel_id": "—",
                "message":  f"No vessel assigned to {cargo['id']} (priority={cargo['priority']})",
            })

    return alerts


def render_alerts():
    st.title("Alerts & Conflicts")

    result = assign_cargoes(CARGOES, VESSELS, TERMINALS)
    alerts = detect_alerts(result["assignments"], CARGOES, VESSELS, TERMINALS)

    critical = [a for a in alerts if a["severity"] == "CRITICAL"]
    warnings = [a for a in alerts if a["severity"] == "WARNING"]
    infos    = [a for a in alerts if a["severity"] == "INFO"]

    col1, col2, col3 = st.columns(3)
    col1.metric("🔴 Critical", len(critical))
    col2.metric("🟠 Warnings", len(warnings))
    col3.metric("🔵 Info",     len(infos))

    st.divider()

    if not alerts:
        st.success("No alerts detected — all assignments are valid.")
        return

    for a in critical:
        st.error(f"**CRITICAL** | {a['cargo_id']} / {a['vessel_id']}\n\n{a['message']}")
    for a in warnings:
        st.warning(f"**WARNING** | {a['cargo_id']} / {a['vessel_id']}\n\n{a['message']}")
    for a in infos:
        st.info(f"**INFO** | {a['cargo_id']} / {a['vessel_id']}\n\n{a['message']}")


if __name__ == "__main__":
    render_alerts()
