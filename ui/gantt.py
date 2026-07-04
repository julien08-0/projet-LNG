# ui/gantt.py
# Gantt chart: 30-day vessel schedule.
# Green = on time, Orange = tight window, Red = delivery window breached.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import plotly.graph_objects as go
from datetime import datetime, timedelta

from data.vessels   import VESSELS
from data.cargoes   import CARGOES
from data.routes    import ROUTES
from data.terminals import TERMINALS
from core.optimizer import assign_cargoes
from core.physics   import calculate_eta


def build_gantt_data(assignments, cargoes, vessels, routes):
    """
    Build the list of bars for the Gantt chart.
    Each bar = one cargo on one vessel, from loading start to discharge end.
    Color = delivery status.
    """
    cargoes_by_id = {c["id"]: c for c in cargoes}
    vessels_by_id = {v["id"]: v for v in vessels}
    routes_by_key = {f"{r['origin']}->{r['destination']}": r for r in routes}

    bars = []

    for a in assignments:
        cargo  = cargoes_by_id[a["cargo_id"]]
        vessel = vessels_by_id[a["vessel_id"]]

        loading_start = datetime.fromisoformat(cargo["laycan_start"])
        loading_end   = loading_start + timedelta(hours=24)

        route_key = f"{cargo['loading_terminal']}->{cargo['discharge_terminal']}"
        route = routes_by_key.get(route_key)
        if not route:
            continue

        eta = calculate_eta(
            departure_date_iso=loading_end.isoformat(timespec="minutes"),
            distance_nm=route["distance_nm"],
            speed_knots=vessel["speed_knots"],
            weather_delay_hours=route["weather_delay_hours"],
            canal_delay_hours=route["canal_delay_hours"],
        )

        discharge_start = datetime.fromisoformat(eta["eta_iso"])
        discharge_end   = discharge_start + timedelta(hours=24)

        delivery_window_start = datetime.fromisoformat(cargo["delivery_window_start"])
        delivery_window_end   = datetime.fromisoformat(cargo["delivery_window_end"])
        if discharge_start > delivery_window_end:
            color = "red"      # arrives after delivery window
        elif discharge_start < delivery_window_start:
            color = "orange"   # arrives before delivery window opens
        else:
            color = "green"    # on time

        bars.append({
            "vessel":          vessel["id"],
            "cargo":           cargo["id"],
            "loading_start":   loading_start,
            "loading_end":     loading_end,
            "discharge_start": discharge_start,
            "discharge_end":   discharge_end,
            "color":           color,
        })

    return bars


def render_gantt():
    st.title("Cargo Schedule — Gantt View")

    result = assign_cargoes(CARGOES, VESSELS, TERMINALS)
    bars   = build_gantt_data(result["assignments"], CARGOES, VESSELS, ROUTES)

    fig = go.Figure()

    for bar in bars:
        # Loading phase
        fig.add_trace(go.Bar(
            name=bar["cargo"],
            x=[(bar["loading_end"] - bar["loading_start"]).total_seconds() / 86400],
            y=[bar["vessel"]],
            base=[(bar["loading_start"] - datetime(2025, 3, 1)).total_seconds() / 86400],
            orientation="h",
            marker_color="#378ADD",
            hovertemplate=(
                f"<b>{bar['cargo']}</b><br>"
                f"Loading: {bar['loading_start'].strftime('%b %d %H:%M')} → "
                f"{bar['loading_end'].strftime('%b %d %H:%M')}<extra></extra>"
            ),
            showlegend=False,
        ))

        # Transit + discharge phase
        color_map = {"green": "#5DCAA5", "orange": "#EF9F27", "red": "#D85A30"}
        fig.add_trace(go.Bar(
            name=bar["cargo"],
            x=[(bar["discharge_end"] - bar["loading_end"]).total_seconds() / 86400],
            y=[bar["vessel"]],
            base=[(bar["loading_end"] - datetime(2025, 3, 1)).total_seconds() / 86400],
            orientation="h",
            marker_color=color_map[bar["color"]],
            hovertemplate=(
                f"<b>{bar['cargo']}</b><br>"
                f"Discharge: {bar['discharge_start'].strftime('%b %d %H:%M')} → "
                f"{bar['discharge_end'].strftime('%b %d %H:%M')}<extra></extra>"
            ),
            showlegend=False,
        ))

    fig.update_layout(
        barmode="stack",
        xaxis=dict(
            title="Days from March 1, 2025",
            range=[0, 35],
        ),
        yaxis=dict(title="Vessel"),
        height=400,
        plot_bgcolor="white",
    )

    st.plotly_chart(fig, use_container_width=True)

    # Legend
    col1, col2, col3 = st.columns(3)
    col1.success("🟢 On time")
    col2.warning("🟠 Early / tight")
    col3.error("🔴 Delivery window breached")

    # Unassigned cargoes
    if result["unassigned"]:
        st.subheader("Unassigned cargoes")
        for u in result["unassigned"]:
            st.error(f"**{u['cargo_id']}** — {u['reason']}")


if __name__ == "__main__":
    render_gantt()
