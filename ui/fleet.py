# ui/fleet.py
# Fleet Management: add vessels for this session (class, capacity, starting
# port) — they show up immediately on every other page. No business logic
# here beyond calling ui/fleet_state.py.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime

import streamlit as st

from data.vessels   import VESSELS
from data.terminals import TERMINALS
from ui.fleet_state import get_fleet, add_vessel, remove_vessel, reset_fleet, VALID_VESSEL_CLASSES
from ui.theme       import inject_dark_theme
from config import DEFAULT_SPEED_KNOTS


def render_fleet():
    inject_dark_theme()
    st.title("Fleet Management")
    st.caption("Add vessels for this session — they appear immediately on every other page.")

    with st.form("add_vessel_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        vessel_class = col1.selectbox("Vessel class", VALID_VESSEL_CLASSES)
        capacity_m3  = col2.number_input("Capacity (m³)", min_value=100_000, max_value=270_000,
                                          value=200_000, step=5_000)

        col3, col4 = st.columns(2)
        terminal_id = col3.selectbox("Starting port", [t["id"] for t in TERMINALS],
                                      format_func=lambda tid: next(t["name"] for t in TERMINALS if t["id"] == tid))
        speed_knots = col4.slider("Speed (knots)", 14.0, 20.0, DEFAULT_SPEED_KNOTS, step=0.5)

        available_date = st.date_input("Available from", value=date(2025, 3, 1))
        submitted = st.form_submit_button("Add vessel")

        if submitted:
            terminal = next(t for t in TERMINALS if t["id"] == terminal_id)
            available_from_iso = datetime.combine(available_date, datetime.min.time()).isoformat(timespec="minutes")
            new_vessel = add_vessel(vessel_class, capacity_m3, terminal, available_from_iso, speed_knots)
            st.success(f"Added **{new_vessel['id']}** ({vessel_class}, {capacity_m3:,} m³) "
                       f"at {terminal['name']}")

    st.divider()
    st.subheader("Current fleet")

    base_ids = {v["id"] for v in VESSELS}
    fleet = get_fleet()

    for v in fleet:
        is_custom = v["id"] not in base_ids
        cols = st.columns([2, 1.5, 1.5, 2.5, 2, 1])
        cols[0].write(v["id"] + (" 🆕" if is_custom else ""))
        cols[1].write(v["vessel_class"])
        cols[2].write(f"{v['capacity_m3']:,} m³")
        cols[3].write(v["current_position"])
        cols[4].write(v["available_from"])
        if is_custom:
            if cols[5].button("Remove", key=f"remove_{v['id']}"):
                remove_vessel(v["id"])
                st.rerun()

    if st.session_state.get("custom_vessels"):
        st.divider()
        if st.button("Reset to base fleet"):
            reset_fleet()
            st.rerun()


if __name__ == "__main__":
    render_fleet()
