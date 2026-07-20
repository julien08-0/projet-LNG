# ui/disruption.py
# Disruption simulator: vessel delay / terminal offline / chokepoint closure.
# Shows the fleet-wide $ impact (baseline vs scenario). No business logic
# lives here — everything comes from core.disruption.simulate_disruption_impact.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime

import streamlit as st
import pandas as pd

from data.vessels   import VESSELS
from data.terminals import TERMINALS
from data.cargoes   import CARGOES
from core.disruption import (
    apply_terminal_offline_to_cargoes,
    apply_vessel_delay_to_vessels,
    simulate_disruption_impact,
)
from ui.fleet_state import get_fleet
from ui.theme       import inject_dark_theme


def _render_impact_summary(impact):
    col1, col2, col3 = st.columns(3)
    col1.metric("Baseline fleet margin", f"${impact['baseline']['total_margin_usd']:,.0f}")
    col2.metric("Scenario fleet margin", f"${impact['scenario']['total_margin_usd']:,.0f}",
                delta=f"${impact['delta_usd']:,.0f} ({impact['delta_pct']:+.1f}%)")
    changed_count = sum(1 for d in impact["cargo_diffs"] if d["changed"])
    col3.metric("Cargoes affected", changed_count)

    for cargo_id, priority in impact["newly_unassigned_with_priority"]:
        if priority >= 8:
            st.error(f"**HIGH PRIORITY** cargo **{cargo_id}** (priority={priority}) "
                     f"becomes UNASSIGNED under this scenario")
        else:
            st.warning(f"**{cargo_id}** (priority={priority}) becomes UNASSIGNED under this scenario")


def _render_cargo_diff_table(impact):
    rows = [d for d in impact["cargo_diffs"] if d["changed"]]
    if not rows:
        st.success("No change in assignment, destination or margin for this scenario.")
        return
    df = pd.DataFrame(rows)[[
        "cargo_id", "priority",
        "baseline_vessel", "baseline_destination", "baseline_margin_usd",
        "scenario_vessel", "scenario_destination", "scenario_margin_usd",
        "margin_delta_usd",
    ]]
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_disruption():
    inject_dark_theme()
    st.title("Disruption Simulator")
    st.caption("$ impact on fleet-wide net margin, before vs after the scenario.")

    VESSELS = get_fleet()

    tab_vessel, tab_terminal, tab_chokepoint = st.tabs(
        ["Vessel delay", "Terminal offline", "Chokepoint closure"])

    with tab_vessel:
        vessel_id = st.selectbox("Vessel", [v["id"] for v in VESSELS], key="disr_vessel")
        delay_hours = st.slider("Delay (hours)", 0, 240, 72, step=6, key="disr_vessel_delay")

        delayed_vessels = apply_vessel_delay_to_vessels(VESSELS, vessel_id, delay_hours)
        impact = simulate_disruption_impact(CARGOES, VESSELS, TERMINALS, scenario_vessels=delayed_vessels)
        _render_impact_summary(impact)
        _render_cargo_diff_table(impact)

    with tab_terminal:
        terminal_id = st.selectbox("Terminal", [t["id"] for t in TERMINALS], key="disr_terminal")
        col1, col2 = st.columns(2)
        offline_start = col1.date_input("Offline from", value=date(2025, 3, 1), key="disr_offline_start")
        offline_end   = col2.date_input("Offline until", value=date(2025, 3, 4), key="disr_offline_end")

        terminal = next(t for t in TERMINALS if t["id"] == terminal_id)
        offline_start_iso = datetime.combine(offline_start, datetime.min.time()).isoformat(timespec="minutes")
        offline_end_iso   = datetime.combine(offline_end,   datetime.min.time()).isoformat(timespec="minutes")

        transform = apply_terminal_offline_to_cargoes(terminal, CARGOES, offline_start_iso, offline_end_iso)
        if transform["dropped"]:
            st.error(f"{len(transform['dropped'])} cargo(es) entirely unservable: "
                     f"{', '.join(d['cargo_id'] for d in transform['dropped'])}")
        if transform["destination_removed"]:
            st.info(f"{len(transform['destination_removed'])} DES cargo(es) lost one destination "
                     f"option but remain servable: "
                     f"{', '.join(d['cargo_id'] for d in transform['destination_removed'])}")

        impact = simulate_disruption_impact(CARGOES, VESSELS, TERMINALS, scenario_cargoes=transform["cargoes"])
        _render_impact_summary(impact)
        _render_cargo_diff_table(impact)

    with tab_chokepoint:
        closed = set()
        if st.checkbox("🔴 Close Suez Canal", key="disr_suez"):
            closed.add("SUEZ")
        if st.checkbox("🔴 Close Strait of Hormuz", key="disr_hormuz"):
            closed.add("HORMUZ")
        if st.checkbox("🔴 Close Strait of Malacca", key="disr_malacca"):
            closed.add("MALACCA")
        if st.checkbox("🔴 Close Panama Canal", key="disr_panama"):
            closed.add("PANAMA")

        impact = simulate_disruption_impact(CARGOES, VESSELS, TERMINALS, scenario_closed_chokepoints=closed)
        _render_impact_summary(impact)
        _render_cargo_diff_table(impact)


if __name__ == "__main__":
    render_disruption()
