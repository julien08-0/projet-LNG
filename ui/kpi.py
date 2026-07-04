# ui/kpi.py
# KPI dashboard: global fleet performance metrics.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from datetime import datetime, timedelta

from data.vessels   import VESSELS
from data.terminals import TERMINALS
from data.cargoes   import CARGOES
from core.optimizer import assign_cargoes
from core.routing   import build_route
from core.physics   import calculate_eta, calculate_boiloff
from config         import PRICE_JKM


def compute_kpis(assignments, cargoes, vessels, terminals):
    cargoes_by_id   = {c["id"]: c for c in cargoes}
    vessels_by_id   = {v["id"]: v for v in vessels}
    terminals_by_id = {t["id"]: t for t in terminals}

    assigned_vessel_ids = {a["vessel_id"] for a in assignments}
    assigned_cargo_ids  = {a["cargo_id"]  for a in assignments}

    fleet_utilization = len(assigned_vessel_ids) / len(vessels) * 100
    total_volume      = sum(c["volume_mmbtu"] for c in cargoes if c["id"] in assigned_cargo_ids)
    total_bog         = 0.0
    total_bunker      = 0.0

    for a in assignments:
        cargo  = cargoes_by_id[a["cargo_id"]]
        vessel = vessels_by_id[a["vessel_id"]]

        origin = terminals_by_id[cargo["loading_terminal"]]
        dest   = terminals_by_id[cargo["discharge_terminal"]]
        route  = build_route(origin, dest)

        loading_end = datetime.fromisoformat(cargo["laycan_start"]) + timedelta(hours=24)
        eta = calculate_eta(
            departure_date_iso=loading_end.isoformat(timespec="minutes"),
            distance_nm=route["distance_nm"],
            speed_knots=vessel["speed_knots"],
            weather_delay_hours=route["weather_delay_hours"],
            canal_delay_hours=route["canal_delay_hours"],
        )
        bog = calculate_boiloff(
            cargo_volume_mmbtu=cargo["volume_mmbtu"],
            transit_days=eta["transit_days"],
            vessel_class=vessel["vessel_class"],
            ambient_temp_celsius=28.0,
        )
        total_bog    += bog["gross_bog_mmbtu"]
        total_bunker += bog["bunker_saving_usd"]

    return {
        "fleet_utilization_pct":   round(fleet_utilization, 1),
        "total_volume_mmbtu":      round(total_volume, 0),
        "total_bog_mmbtu":         round(total_bog, 0),
        "total_bog_usd":           round(total_bog * PRICE_JKM, 0),
        "total_bunker_saving_usd": round(total_bunker, 0),
        "unassigned_count":        len(cargoes) - len(assigned_cargo_ids),
    }


def render_kpi():
    st.title("KPI Dashboard")

    result = assign_cargoes(CARGOES, VESSELS, TERMINALS)
    kpis   = compute_kpis(result["assignments"], CARGOES, VESSELS, TERMINALS)

    st.subheader("Fleet")
    col1, col2, col3 = st.columns(3)
    col1.metric("Fleet utilization",  f"{kpis['fleet_utilization_pct']}%")
    col2.metric("Cargoes assigned",   f"{len(result['assignments'])} / {len(CARGOES)}")
    col3.metric("Unassigned cargoes", kpis["unassigned_count"])

    st.divider()

    st.subheader("Volumes")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total volume contracted", f"{kpis['total_volume_mmbtu']:,.0f} mmBtu")
    col2.metric("Total BOG loss",          f"{kpis['total_bog_mmbtu']:,.0f} mmBtu")
    col3.metric("BOG value lost",          f"${kpis['total_bog_usd']:,.0f}")

    st.divider()

    st.subheader("Costs")
    col1, col2 = st.columns(2)
    col1.metric("Bunker saving (BOG as fuel)", f"${kpis['total_bunker_saving_usd']:,.0f}")
    col2.metric("Net BOG cost",
                f"${kpis['total_bog_usd'] - kpis['total_bunker_saving_usd']:,.0f}")

    if result["unassigned"]:
        st.divider()
        st.subheader("Unassigned cargoes")
        for u in result["unassigned"]:
            st.warning(f"**{u['cargo_id']}** — {u['reason']}")
