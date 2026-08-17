# ui/alerts.py
# Alerts: detected conflicts across all assignments.
# Severity: CRITICAL (red), WARNING (orange), INFO (blue).
#
# Doesn't carry enough on its own to justify a standalone nav page — it's
# a diagnostic on the same assignments the "P&L & KPIs" page already computes.
# Embedded there (bottom of the page) via render_alerts_section(), which
# takes the alert list already detected by the caller.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from core.physics    import calculate_eta
from core.routing    import build_route
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
        # Real routed ETA (not straight-line) from current vessel position
        # to loading terminal, ballast speed since no cargo is aboard yet —
        # same method core.optimizer's reachability check uses, so an
        # alert here can never contradict what the scheduler itself decided.
        vessel_position = {"id": "VESSEL_POSITION", "lat": vessel["current_lat"], "lon": vessel["current_lon"]}
        route_to_load = build_route(vessel_position, loading_terminal)
        eta_to_load = calculate_eta(
            departure_date_iso=vessel["available_from"],
            distance_nm=max(route_to_load["distance_nm"], 1.0),  # avoid 0nm edge case
            speed_knots=vessel["ballast_speed_knots"],
            weather_delay_hours=route_to_load["weather_delay_hours"],
            canal_delay_hours=route_to_load["canal_delay_hours"],
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
            severity = "CRITICAL" if cargo["priority"] >= 8 else "WARNING"
            alerts.append({
                "severity": severity,
                "cargo_id":  cargo["id"],
                "vessel_id": "—",
                "message":  f"No vessel assigned to {cargo['id']} (priority={cargo['priority']})",
            })

    return alerts


def render_alerts_section(alerts):
    """Compact alerts block — embedded at the bottom of the "P&L & KPIs" page,
    not a standalone page. No title/hero: the parent page already has one."""
    critical = [a for a in alerts if a["severity"] == "CRITICAL"]
    warnings = [a for a in alerts if a["severity"] == "WARNING"]
    infos    = [a for a in alerts if a["severity"] == "INFO"]

    st.subheader("Alerts & Conflicts")

    if not alerts:
        st.success("No alerts detected — all assignments are valid.")
        return

    st.caption(f"{len(critical)} critical · {len(warnings)} warnings · {len(infos)} info")

    def _table(rows):
        return pd.DataFrame([{"Cargo": a["cargo_id"], "Vessel": a["vessel_id"], "Message": a["message"]}
                              for a in rows])

    for a in critical:
        st.error(f"**{a['cargo_id']} / {a['vessel_id']}** — {a['message']}")

    if warnings:
        st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)
        with st.expander(f"⚠️ {len(warnings)} warning(s)", expanded=len(warnings) <= 3):
            st.dataframe(_table(warnings), use_container_width=True, hide_index=True)

    if infos:
        with st.expander(f"ℹ️ {len(infos)} info"):
            st.dataframe(_table(infos), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    from data.vessels   import VESSELS
    from data.terminals import TERMINALS
    from data.cargoes   import CARGOES
    from core.optimizer import assign_cargoes
    from ui.theme       import inject_theme

    inject_theme()
    st.title("Alerts (standalone preview)")
    result = assign_cargoes(CARGOES, VESSELS, TERMINALS)
    alerts = detect_alerts(result["assignments"], CARGOES, VESSELS, TERMINALS)
    render_alerts_section(alerts)
