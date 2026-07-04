# ui/map.py
# Animated world map: vessel movements over N days.
# Uses dynamic routing — any terminal pair works automatically.
# Dashed lines show real maritime routes with correct chokepoints.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import plotly.graph_objects as go
from datetime import datetime, timedelta
import math

from data.vessels   import VESSELS
from data.terminals import TERMINALS
from data.cargoes   import CARGOES
from core.optimizer import assign_cargoes
from core.routing   import build_route
from core.physics   import calculate_boiloff


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def interpolate_position(waypoints, fraction):
    """Interpolate position along a waypoint list (fraction 0→1)."""
    if fraction <= 0: return waypoints[0]
    if fraction >= 1: return waypoints[-1]

    def dist(a, b):
        return math.sqrt((b[0]-a[0])**2 + (b[1]-a[1])**2)

    segments = [dist(waypoints[i], waypoints[i+1]) for i in range(len(waypoints)-1)]
    total    = sum(segments)
    target   = fraction * total
    cumul    = 0.0

    for i, seg in enumerate(segments):
        if cumul + seg >= target:
            f = (target - cumul) / seg if seg > 0 else 0
            lat = waypoints[i][0] + f * (waypoints[i+1][0] - waypoints[i][0])
            lon = waypoints[i][1] + f * (waypoints[i+1][1] - waypoints[i][1])
            return [lat, lon]
        cumul += seg

    return waypoints[-1]


def get_vessel_state(vessel, cargo, route, day, sim_start):
    """Compute vessel position, phase, and cargo fill on simulation day."""
    laycan_start    = datetime.fromisoformat(cargo["laycan_start"])
    loading_end     = laycan_start + timedelta(hours=24)
    transit_days    = route["distance_nm"] / vessel["speed_knots"] / 24.0
    discharge_start = loading_end + timedelta(days=transit_days)
    discharge_end   = discharge_start + timedelta(hours=24)
    current         = sim_start + timedelta(days=day)

    if current < laycan_start:
        return {"lat": vessel["current_lat"], "lon": vessel["current_lon"],
                "phase": "waiting", "fill": 1.0, "volume": cargo["volume_mmbtu"]}

    if current < loading_end:
        term = next(t for t in TERMINALS if t["id"] == cargo["loading_terminal"])
        return {"lat": term["lat"], "lon": term["lon"],
                "phase": "loading", "fill": 1.0, "volume": cargo["volume_mmbtu"]}

    if current < discharge_start:
        days_at_sea = (current - loading_end).total_seconds() / 86400.0
        fraction    = min(days_at_sea / transit_days, 1.0)
        pos         = interpolate_position(route["waypoints"], fraction)
        bog = calculate_boiloff(cargo["volume_mmbtu"], days_at_sea, vessel["vessel_class"], 28.0)
        fill = bog["volume_delivered_mmbtu"] / cargo["volume_mmbtu"]
        return {"lat": pos[0], "lon": pos[1], "phase": "in_transit",
                "fill": round(fill, 3), "volume": round(bog["volume_delivered_mmbtu"], 0)}

    term = next(t for t in TERMINALS if t["id"] == cargo["discharge_terminal"])
    return {"lat": term["lat"], "lon": term["lon"],
            "phase": "discharging" if current < discharge_end else "completed",
            "fill": 0.05, "volume": 0}


# ---------------------------------------------------------------------------
# Build animation frames
# ---------------------------------------------------------------------------

def build_frames(assignments, vessels, cargoes, terminals, sim_days, closed_chokepoints=None):
    if closed_chokepoints is None:
        closed_chokepoints = set()

    sim_start       = datetime(2025, 3, 1)
    cargoes_by_id   = {c["id"]: c for c in cargoes}
    vessels_by_id   = {v["id"]: v for v in vessels}
    terminals_by_id = {t["id"]: t for t in terminals}

    vessel_colors = {
        "Q-Max":  "#D85A30",
        "Q-Flex": "#378ADD",
        "TFDE":   "#5DCAA5",
        "STEAM":  "#EF9F27",
    }

    # Pre-compute routes for all assignments
    routes_cache = {}
    for a in assignments:
        cargo  = cargoes_by_id[a["cargo_id"]]
        origin = terminals_by_id[cargo["loading_terminal"]]
        dest   = terminals_by_id[cargo["discharge_terminal"]]
        key    = f"{origin['id']}->{dest['id']}"
        if key not in routes_cache:
            routes_cache[key] = build_route(origin, dest, closed_chokepoints)

    frames = []

    for day in range(sim_days + 1):
        current_date = sim_start + timedelta(days=day)
        frame_data   = []

        # Dashed route lines
        drawn_routes = set()
        for a in assignments:
            cargo     = cargoes_by_id[a["cargo_id"]]
            route_key = f"{cargo['loading_terminal']}->{cargo['discharge_terminal']}"
            if route_key in drawn_routes:
                continue
            drawn_routes.add(route_key)
            route = routes_cache[route_key]
            lats  = [wp[0] for wp in route["waypoints"]]
            lons  = [wp[1] for wp in route["waypoints"]]
            frame_data.append(go.Scattergeo(
                lat=lats, lon=lons,
                mode="lines",
                line=dict(width=1, color="#B4B2A9", dash="dot"),
                showlegend=False, hoverinfo="skip",
            ))

        # Terminals
        for t in terminals:
            color  = "#378ADD" if t["type"] == "loading" else "#5DCAA5"
            symbol = "square" if t["type"] == "loading" else "circle"
            frame_data.append(go.Scattergeo(
                lat=[t["lat"]], lon=[t["lon"]],
                mode="markers+text",
                marker=dict(size=10, color=color, symbol=symbol),
                text=[t["id"]], textposition="top center",
                textfont=dict(size=8),
                showlegend=False,
                hovertemplate=f"<b>{t['name']}</b><br>{t['type']}<br>Berths: {t['berth_count']}<extra></extra>",
            ))

        # Vessels
        for a in assignments:
            vessel    = vessels_by_id[a["vessel_id"]]
            cargo     = cargoes_by_id[a["cargo_id"]]
            route_key = f"{cargo['loading_terminal']}->{cargo['discharge_terminal']}"
            route     = routes_cache[route_key]
            state     = get_vessel_state(vessel, cargo, route, day, sim_start)
            color     = vessel_colors.get(vessel["vessel_class"], "#888780")

            frame_data.append(go.Scattergeo(
                lat=[state["lat"]], lon=[state["lon"]],
                mode="markers",
                marker=dict(size=14, color=color, symbol="triangle-up",
                            line=dict(width=1, color="white")),
                showlegend=False,
                hovertemplate=(
                    f"<b>{vessel['id']}</b><br>"
                    f"Class: {vessel['vessel_class']}<br>"
                    f"Cargo: {cargo['id']}<br>"
                    f"Phase: {state['phase']}<br>"
                    f"Fill: {round(state['fill']*100,1)}%<br>"
                    f"Volume: {state['volume']:,.0f} mmBtu<extra></extra>"
                ),
            ))

        frames.append(go.Frame(
            data=frame_data,
            name=str(day),
            layout=go.Layout(title_text=f"Day {day} — {current_date.strftime('%B %d, 2025')}"),
        ))

    return frames, routes_cache


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render_map():
    st.title("Fleet Map — Animation")

    # Sidebar controls
    st.sidebar.subheader("Simulation")
    sim_days     = st.sidebar.slider("Days", 10, 45, 30)
    filter_class = st.sidebar.multiselect(
        "Vessel class",
        ["Q-Max", "Q-Flex", "TFDE", "STEAM"],
        default=["Q-Max", "Q-Flex", "TFDE", "STEAM"],
    )

    st.sidebar.subheader("Disruptions")
    closed = set()
    if st.sidebar.checkbox("🔴 Close Suez Canal"):
        closed.add("SUEZ")
    if st.sidebar.checkbox("🔴 Close Strait of Hormuz"):
        closed.add("HORMUZ")
    if st.sidebar.checkbox("🔴 Close Strait of Malacca"):
        closed.add("MALACCA")
    if st.sidebar.checkbox("🔴 Close Panama Canal"):
        closed.add("PANAMA")

    result      = assign_cargoes(CARGOES, VESSELS, TERMINALS, closed_chokepoints=closed)
    assignments = [a for a in result["assignments"]
                   if any(v["id"] == a["vessel_id"] and v["vessel_class"] in filter_class
                          for v in VESSELS)]

    if not assignments:
        st.warning("No assignments to display.")
        return

    frames, routes_cache = build_frames(
        assignments, VESSELS, CARGOES, TERMINALS, sim_days, closed)

    fig = go.Figure(
        data=frames[0].data,
        frames=frames,
        layout=go.Layout(
            geo=dict(
                showland=True, landcolor="#F1EFE8",
                showocean=True, oceancolor="#E6F1FB",
                showcoastlines=True, coastlinecolor="#B4B2A9",
                showcountries=True, countrycolor="#D3D1C7",
                projection_type="natural earth",
            ),
            height=580,
            margin=dict(l=0, r=0, t=40, b=0),
            updatemenus=[dict(
                type="buttons", showactive=False, y=1.05, x=0.1,
                buttons=[
                    dict(label="▶ Play", method="animate",
                         args=[None, dict(frame=dict(duration=300, redraw=True), fromcurrent=True)]),
                    dict(label="⏸ Pause", method="animate",
                         args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")]),
                ],
            )],
            sliders=[dict(
                steps=[dict(method="animate",
                            args=[[str(d)], dict(mode="immediate", frame=dict(duration=300, redraw=True))],
                            label=str(d)) for d in range(sim_days + 1)],
                x=0.1, y=0, len=0.9,
                currentvalue=dict(prefix="Day: ", visible=True),
            )],
        ),
    )

    st.plotly_chart(fig, use_container_width=True)

    # Disruption impact
    if closed:
        st.warning(f"Closed chokepoints: {', '.join(closed)}")
        for u in result["unassigned"]:
            st.error(f"{u['cargo_id']} unassigned — {u['reason']}")

    # Legend
    col1, col2, col3, col4 = st.columns(4)
    col1.markdown("🔴 Q-Max")
    col2.markdown("🔵 Q-Flex")
    col3.markdown("🟢 TFDE")
    col4.markdown("🟠 STEAM")
