# ui/map.py
# Animated world map: vessel movements over 30 days.
# Shows real maritime routes as dashed lines, vessel positions,
# cargo fill level (boil-off applied daily), and terminal volumes.

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
from data.routes    import ROUTES
from core.optimizer import assign_cargoes
from core.physics   import calculate_boiloff
from config         import BOILOFF_RATE, LNG_ENERGY_DENSITY_MMBTU_PER_M3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def interpolate_position(waypoints, fraction):
    """
    Given a list of [lat, lon] waypoints and a fraction [0,1],
    return the interpolated [lat, lon] position along the route.
    """
    if fraction <= 0:
        return waypoints[0]
    if fraction >= 1:
        return waypoints[-1]

    # Compute cumulative distances between waypoints
    def dist(a, b):
        dlat = b[0] - a[0]
        dlon = b[1] - a[1]
        return math.sqrt(dlat**2 + dlon**2)

    segments = [dist(waypoints[i], waypoints[i+1]) for i in range(len(waypoints)-1)]
    total    = sum(segments)
    target   = fraction * total

    cumulative = 0.0
    for i, seg_len in enumerate(segments):
        if cumulative + seg_len >= target:
            local_frac = (target - cumulative) / seg_len if seg_len > 0 else 0
            lat = waypoints[i][0] + local_frac * (waypoints[i+1][0] - waypoints[i][0])
            lon = waypoints[i][1] + local_frac * (waypoints[i+1][1] - waypoints[i][1])
            return [lat, lon]
        cumulative += seg_len

    return waypoints[-1]


def get_vessel_state(vessel, cargo, route, day, sim_start):
    """
    Compute vessel position and cargo fill on a given simulation day.

    Phases:
      - Before laycan_start : vessel at current position (waiting)
      - Loading             : vessel at loading terminal (24h)
      - In transit          : vessel moving along route
      - Discharging         : vessel at discharge terminal (24h)
    """
    laycan_start   = datetime.fromisoformat(cargo["laycan_start"])
    loading_end    = laycan_start + timedelta(hours=24)
    transit_days   = route["distance_nm"] / vessel["speed_knots"] / 24.0
    discharge_start = loading_end + timedelta(days=transit_days)
    discharge_end   = discharge_start + timedelta(hours=24)

    current_date = sim_start + timedelta(days=day)

    # Phase: waiting
    if current_date < laycan_start:
        return {
            "lat":    vessel["current_lat"],
            "lon":    vessel["current_lon"],
            "phase":  "waiting",
            "fill":   1.0,
            "volume": cargo["volume_mmbtu"],
        }

    # Phase: loading
    if current_date < loading_end:
        term = next(t for t in TERMINALS if t["id"] == cargo["loading_terminal"])
        return {
            "lat":    term["lat"],
            "lon":    term["lon"],
            "phase":  "loading",
            "fill":   1.0,
            "volume": cargo["volume_mmbtu"],
        }

    # Phase: in transit
    if current_date < discharge_start:
        days_at_sea = (current_date - loading_end).total_seconds() / 86400.0
        fraction    = min(days_at_sea / transit_days, 1.0)
        pos         = interpolate_position(route["waypoints"], fraction)

        bog = calculate_boiloff(
            cargo_volume_mmbtu=cargo["volume_mmbtu"],
            transit_days=days_at_sea,
            vessel_class=vessel["vessel_class"],
            ambient_temp_celsius=28.0,
        )
        remaining = bog["volume_delivered_mmbtu"]
        fill      = remaining / cargo["volume_mmbtu"]

        return {
            "lat":    pos[0],
            "lon":    pos[1],
            "phase":  "in_transit",
            "fill":   round(fill, 3),
            "volume": round(remaining, 0),
        }

    # Phase: discharging
    if current_date < discharge_end:
        term = next(t for t in TERMINALS if t["id"] == cargo["discharge_terminal"])
        return {
            "lat":    term["lat"],
            "lon":    term["lon"],
            "phase":  "discharging",
            "fill":   0.05,
            "volume": 0,
        }

    # Phase: completed — vessel at discharge terminal
    term = next(t for t in TERMINALS if t["id"] == cargo["discharge_terminal"])
    return {
        "lat":    term["lat"],
        "lon":    term["lon"],
        "phase":  "completed",
        "fill":   0.0,
        "volume": 0,
    }


# ---------------------------------------------------------------------------
# Build animation frames
# ---------------------------------------------------------------------------

def build_frames(assignments, vessels, cargoes, routes, terminals, sim_days):
    sim_start     = datetime(2025, 3, 1)
    cargoes_by_id = {c["id"]: c for c in cargoes}
    vessels_by_id = {v["id"]: v for v in vessels}
    routes_by_key = {f"{r['origin']}->{r['destination']}": r for r in routes}

    vessel_colors = {
        "Q-Max":  "#D85A30",
        "Q-Flex": "#378ADD",
        "TFDE":   "#5DCAA5",
        "STEAM":  "#EF9F27",
    }

    frames = []

    for day in range(sim_days + 1):
        current_date = sim_start + timedelta(days=day)
        frame_data   = []

        # --- Routes as dashed lines ---
        for route in routes:
            lats = [wp[0] for wp in route["waypoints"]]
        lons = [wp[1] for wp in route["waypoints"]]
        frame_data.append(go.Scattergeo(
            lat=lats, lon=lons,
            mode="lines",
            line=dict(width=1, color="#B4B2A9", dash="dot"),
            showlegend=False,
            hoverinfo="skip",
        ))

        # --- Terminals ---
        for t in terminals:
            color  = "#378ADD" if t["type"] == "loading" else "#5DCAA5"
            symbol = "square" if t["type"] == "loading" else "circle"
            frame_data.append(go.Scattergeo(
                lat=[t["lat"]], lon=[t["lon"]],
                mode="markers+text",
                marker=dict(size=10, color=color, symbol=symbol),
                text=[t["id"]],
                textposition="top center",
                textfont=dict(size=8),
                showlegend=False,
                hovertemplate=f"<b>{t['name']}</b><br>Type: {t['type']}<br>Berths: {t['berth_count']}<extra></extra>",
            ))

        # --- Vessels ---
        for a in assignments:
            vessel = vessels_by_id[a["vessel_id"]]
            cargo  = cargoes_by_id[a["cargo_id"]]
            route_key = f"{cargo['loading_terminal']}->{cargo['discharge_terminal']}"
            route  = routes_by_key.get(route_key)
            if not route:
                continue

            state = get_vessel_state(vessel, cargo, route, day, sim_start)
            color = vessel_colors.get(vessel["vessel_class"], "#888780")
            fill_pct = round(state["fill"] * 100, 1)

            frame_data.append(go.Scattergeo(
                lat=[state["lat"]], lon=[state["lon"]],
                mode="markers",
                marker=dict(
                    size=14,
                    color=color,
                    symbol="triangle-up",
                    line=dict(width=1, color="white"),
                ),
                showlegend=False,
                hovertemplate=(
                    f"<b>{vessel['id']}</b><br>"
                    f"Class: {vessel['vessel_class']}<br>"
                    f"Cargo: {cargo['id']}<br>"
                    f"Phase: {state['phase']}<br>"
                    f"Fill: {fill_pct}%<br>"
                    f"Volume: {state['volume']:,.0f} mmBtu"
                    f"<extra></extra>"
                ),
            ))

        frames.append(go.Frame(
            data=frame_data,
            name=str(day),
            layout=go.Layout(
                title_text=f"Day {day} — {current_date.strftime('%B %d, 2025')}"
            ),
        ))

    return frames


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render_map():
    st.title("Fleet Map — 30-Day Animation")

    # Sidebar controls
    st.sidebar.subheader("Simulation controls")
    sim_days      = st.sidebar.slider("Simulation days", 10, 45, 30)
    filter_class  = st.sidebar.multiselect(
        "Vessel class filter",
        ["Q-Max", "Q-Flex", "TFDE", "STEAM"],
        default=["Q-Max", "Q-Flex", "TFDE", "STEAM"],
    )

    result      = assign_cargoes(CARGOES, VESSELS, TERMINALS)
    assignments = result["assignments"]

    # Apply vessel class filter
    vessels_filtered = [v for v in VESSELS if v["vessel_class"] in filter_class]
    assignments      = [a for a in assignments
                        if any(v["id"] == a["vessel_id"] for v in vessels_filtered)]

    frames = build_frames(assignments, VESSELS, CARGOES, ROUTES, TERMINALS, sim_days)

    if not frames:
        st.warning("No assignments to display.")
        return

    fig = go.Figure(
        data=frames[0].data,
        frames=frames,
        layout=go.Layout(
            geo=dict(
                showland=True,
                landcolor="#F1EFE8",
                showocean=True,
                oceancolor="#E6F1FB",
                showcoastlines=True,
                coastlinecolor="#B4B2A9",
                showcountries=True,
                countrycolor="#D3D1C7",
                projection_type="natural earth",
            ),
            height=580,
            margin=dict(l=0, r=0, t=40, b=0),
            updatemenus=[dict(
                type="buttons",
                showactive=False,
                y=1.05, x=0.1,
                buttons=[
                    dict(label="▶ Play",
                         method="animate",
                         args=[None, dict(frame=dict(duration=300, redraw=True),
                                          fromcurrent=True)]),
                    dict(label="⏸ Pause",
                         method="animate",
                         args=[[None], dict(frame=dict(duration=0, redraw=False),
                                             mode="immediate")]),
                ],
            )],
            sliders=[dict(
                steps=[dict(method="animate",
                            args=[[str(d)], dict(mode="immediate",
                                                  frame=dict(duration=300, redraw=True))],
                            label=str(d)) for d in range(sim_days + 1)],
                x=0.1, y=0,
                len=0.9,
                currentvalue=dict(prefix="Day: ", visible=True),
            )],
        ),
    )

    st.plotly_chart(fig, use_container_width=True)

    # Legend
    st.markdown("**Vessel classes:**")
    col1, col2, col3, col4 = st.columns(4)
    col1.markdown("🔴 Q-Max")
    col2.markdown("🔵 Q-Flex")
    col3.markdown("🟢 TFDE")
    col4.markdown("🟠 STEAM")

    col1, col2 = st.columns(2)
    col1.markdown("■ Loading terminal")
    col2.markdown("● Discharge terminal")


if __name__ == "__main__":
    render_map()
