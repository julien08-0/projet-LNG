# ui/fleet.py
# Fleet Management: add vessels for this session (class, capacity, starting
# port). No business logic here beyond calling ui/fleet_state.py.
# Also hosts the Disruption Simulator (ui/disruption.py) underneath, in the
# same nav entry — see render_disruption() call at the bottom of render_fleet().

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime

import streamlit as st

from data.vessels   import VESSELS
from data.terminals import TERMINALS
from ui.fleet_state import get_fleet, add_vessel, remove_vessel, reset_fleet, VALID_VESSEL_CLASSES
from ui.disruption  import render_disruption
from ui.theme       import inject_theme, TEXT_PRIMARY, TEXT_MUTED
from config import DEFAULT_LADEN_SPEED_KNOTS, BALLAST_SPEED_BONUS_KNOTS


def render_fleet():
    inject_theme()
    st.title("Fleet Management")
    st.caption("Add vessels for this session.")

    with st.form("add_vessel_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        vessel_class = col1.selectbox("Vessel class", VALID_VESSEL_CLASSES)
        capacity_m3  = col2.number_input("Capacity (m³)", min_value=100_000, max_value=270_000,
                                          value=200_000, step=5_000)

        col3, col4 = st.columns(2)
        terminal_id = col3.selectbox("Starting port", [t["id"] for t in TERMINALS],
                                      format_func=lambda tid: next(t["name"] for t in TERMINALS if t["id"] == tid))
        laden_speed_knots = col4.slider("Speed, laden (knots)", 14.0, 20.0, DEFAULT_LADEN_SPEED_KNOTS, step=0.5,
                                         help=f"Ballast (empty) speed is derived automatically: "
                                              f"laden + {BALLAST_SPEED_BONUS_KNOTS} knots.")

        available_date = st.date_input("Available from", value=date(2025, 3, 1))
        submitted = st.form_submit_button("Add vessel")

        if submitted:
            terminal = next(t for t in TERMINALS if t["id"] == terminal_id)
            available_from_iso = datetime.combine(available_date, datetime.min.time()).isoformat(timespec="minutes")
            new_vessel = add_vessel(vessel_class, capacity_m3, terminal, available_from_iso, laden_speed_knots)
            st.success(f"Added **{new_vessel['id']}** ({vessel_class}, {capacity_m3:,} m³) "
                       f"at {terminal['name']}")

    st.divider()
    st.subheader("Current fleet")

    st.markdown(
        f"<div style='color:{TEXT_MUTED};font-size:0.72rem;text-transform:uppercase;"
        f"letter-spacing:0.04em;margin-bottom:12px;'>"
        f"Vessel · Class · Capacity · Position · Speed (laden/ballast) · Available from</div>",
        unsafe_allow_html=True,
    )

    base_ids = {v["id"] for v in VESSELS}
    fleet = get_fleet()

    for v in fleet:
        is_custom = v["id"] not in base_ids
        badge = " 🆕" if is_custom else ""
        st.markdown(
            f"<div style='font-size:0.92rem;'>"
            f"<b style='color:{TEXT_PRIMARY};'>{v['id']}</b>{badge} "
            f"<span style='color:{TEXT_MUTED};'>· {v['vessel_class']} · {v['capacity_m3']:,} m³ · "
            f"at {v['current_position']} · {v['laden_speed_knots']}/{v['ballast_speed_knots']}kt · "
            f"available {v['available_from']}</span></div>",
            unsafe_allow_html=True,
        )
        if is_custom:
            if st.button("Remove", key=f"remove_{v['id']}"):
                remove_vessel(v["id"])
                st.rerun()
        st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

    if st.session_state.get("custom_vessels"):
        st.divider()
        if st.button("Reset to base fleet"):
            reset_fleet()
            st.rerun()

    st.divider()
    st.subheader("Disruption Simulator")
    render_disruption()


if __name__ == "__main__":
    render_fleet()
