# ui/map.py
# Animated world map: vessel movements over N days.
# Uses dynamic routing — any terminal pair works automatically.
# Dashed lines show real maritime routes with correct chokepoints.
#
# Dark theme: each vessel gets its own color (fixed categorical order,
# cycled if the fleet is larger than the palette), its ship glyph glows
# via a soft halo marker, and its route is dashed in the same color — so a
# vessel is traceable by color alone across the map and the side panel.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import math

from data.vessels    import VESSELS
from data.terminals  import TERMINALS
from data.cargoes    import CARGOES
from core.optimizer  import assign_cargoes
from core.pnl        import enrich_assignments_with_pnl
from core.routing    import build_route
from core.physics    import calculate_boiloff
from config          import BOILOFF_RATE
from ui.fleet_state  import get_fleet
from ui.theme        import (inject_dark_theme, PAGE_BG, CHART_BG, VESSEL_PALETTE,
                              TERMINAL_LOAD_COLOR, TERMINAL_DISCHARGE_COLOR)


# ---------------------------------------------------------------------------
# Theme — map-specific colors (geo rendering only; generic colors live in
# ui/theme.py and are imported above)
# ---------------------------------------------------------------------------

LAND_COLOR   = "#1c1d22"
OCEAN_COLOR  = "#0a1220"
COAST_COLOR  = "#2c2f3a"
COUNTRY_COLOR = "#22242c"
MUTED_INK    = "#8a8d99"
TRACK_COLOR  = "#2c2c2a"   # unfilled portion of a fill bar

SHIP_GLYPH = "⛴"


def assign_vessel_colors(vessel_ids):
    """Fixed-order categorical palette, cycled if the fleet outgrows it."""
    return {vid: VESSEL_PALETTE[i % len(VESSEL_PALETTE)] for i, vid in enumerate(vessel_ids)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _shortest_lon_delta(lon1, lon2):
    """Signed shortest longitude delta (in [-180, 180]) — avoids tracing the
    long way around through Europe/Africa for routes crossing the
    antimeridian (e.g. Panama -> Asia-Pacific)."""
    return (lon2 - lon1 + 180) % 360 - 180


def interpolate_position(waypoints, fraction):
    """Interpolate position along a waypoint list (fraction 0→1)."""
    if fraction <= 0: return waypoints[0]
    if fraction >= 1: return waypoints[-1]

    def dist(a, b):
        dlon = _shortest_lon_delta(a[1], b[1])
        dlat = b[0] - a[0]
        return math.sqrt(dlat**2 + dlon**2)

    segments = [dist(waypoints[i], waypoints[i+1]) for i in range(len(waypoints)-1)]
    total    = sum(segments)
    target   = fraction * total
    cumul    = 0.0

    for i, seg in enumerate(segments):
        if cumul + seg >= target:
            f = (target - cumul) / seg if seg > 0 else 0
            lat = waypoints[i][0] + f * (waypoints[i+1][0] - waypoints[i][0])
            lon = waypoints[i][1] + f * _shortest_lon_delta(waypoints[i][1], waypoints[i+1][1])
            lon = ((lon + 180) % 360) - 180
            return [lat, lon]
        cumul += seg

    return waypoints[-1]


def get_vessel_state(vessel, cargo, route, day, sim_start, discharge_terminal_id):
    """Compute vessel position, phase, and cargo fill on simulation day."""
    laycan_start    = datetime.fromisoformat(cargo["laycan_start"])
    loading_end     = laycan_start + timedelta(hours=24)
    transit_days    = route["distance_nm"] / vessel["speed_knots"] / 24.0
    discharge_start = loading_end + timedelta(days=transit_days)
    discharge_end   = discharge_start + timedelta(hours=24)
    current         = sim_start + timedelta(days=day)

    # Heel — minimum LNG always retained on board (keeps tanks cryogenic,
    # fuels boil-off during ballast). Never simulated to zero.
    heel_fraction = vessel["current_heel_m3"] / vessel["capacity_m3"]

    if current < laycan_start:
        # Ballast leg — no commercial cargo, but heel is maintained.
        commercial_fraction = 0.0
        fill = heel_fraction + commercial_fraction * (1.0 - heel_fraction)
        return {"lat": vessel["current_lat"], "lon": vessel["current_lon"],
                "phase": "waiting", "fill": round(fill, 3), "volume": 0}

    if current < loading_end:
        term = next(t for t in TERMINALS if t["id"] == cargo["loading_terminal"])
        progress = (current - laycan_start).total_seconds() / (loading_end - laycan_start).total_seconds()
        commercial_fraction = max(0.0, min(progress, 1.0))
        fill = heel_fraction + commercial_fraction * (1.0 - heel_fraction)
        return {"lat": term["lat"], "lon": term["lon"],
                "phase": "loading", "fill": round(fill, 3),
                "volume": round(commercial_fraction * cargo["volume_mmbtu"], 0)}

    if current < discharge_start:
        days_at_sea = (current - loading_end).total_seconds() / 86400.0
        fraction    = min(days_at_sea / transit_days, 1.0)
        pos         = interpolate_position(route["waypoints"], fraction)
        bog = calculate_boiloff(cargo["volume_mmbtu"], days_at_sea, vessel["vessel_class"], 28.0)
        commercial_fraction = bog["volume_delivered_mmbtu"] / cargo["volume_mmbtu"]
        fill = heel_fraction + commercial_fraction * (1.0 - heel_fraction)
        return {"lat": pos[0], "lon": pos[1], "phase": "in_transit",
                "fill": round(fill, 3), "volume": round(bog["volume_delivered_mmbtu"], 0)}

    term = next(t for t in TERMINALS if t["id"] == discharge_terminal_id)

    # Fill at the end of transit — the starting point of the discharge ramp.
    end_transit_bog  = calculate_boiloff(cargo["volume_mmbtu"], transit_days, vessel["vessel_class"], 28.0)
    end_transit_fill = end_transit_bog["volume_delivered_mmbtu"] / cargo["volume_mmbtu"]

    if current < discharge_end:
        progress = (current - discharge_start).total_seconds() / (discharge_end - discharge_start).total_seconds()
        commercial_fraction = end_transit_fill * (1.0 - max(0.0, min(progress, 1.0)))
        fill = heel_fraction + commercial_fraction * (1.0 - heel_fraction)
        return {"lat": term["lat"], "lon": term["lon"], "phase": "discharging",
                "fill": round(max(fill, heel_fraction), 3),
                "volume": round(max(commercial_fraction, 0.0) * cargo["volume_mmbtu"], 0)}

    commercial_fraction = 0.0
    fill = heel_fraction + commercial_fraction * (1.0 - heel_fraction)
    return {"lat": term["lat"], "lon": term["lon"], "phase": "completed",
            "fill": round(fill, 3), "volume": 0}


# ---------------------------------------------------------------------------
# Build map data for a single day
# ---------------------------------------------------------------------------

def build_day_data(enriched_assignments, vessels, cargoes, terminals, day, vessel_colors, closed_chokepoints=None):
    """Build the Plotly traces for a single simulation day.

    Single-clock design: the same `day` value drives both the map (this
    function) and the side panel (`get_vessel_state` calls in
    `render_map`), so they can never drift apart the way the old
    Plotly-animation-frame + separate-Streamlit-slider setup could.
    """
    if closed_chokepoints is None:
        closed_chokepoints = set()

    sim_start       = datetime(2025, 3, 1)
    cargoes_by_id   = {c["id"]: c for c in cargoes}
    vessels_by_id   = {v["id"]: v for v in vessels}
    terminals_by_id = {t["id"]: t for t in terminals}

    # Pre-compute routes for all assignments
    routes_cache = {}
    for a in enriched_assignments:
        cargo  = cargoes_by_id[a["cargo_id"]]
        origin = terminals_by_id[cargo["loading_terminal"]]
        dest   = terminals_by_id[a["discharge_terminal"]]
        key    = f"{origin['id']}->{dest['id']}"
        if key not in routes_cache:
            routes_cache[key] = build_route(origin, dest, closed_chokepoints)

    frame_data = []

    # Dashed route lines — one per vessel, in that vessel's own color
    for a in enriched_assignments:
        cargo     = cargoes_by_id[a["cargo_id"]]
        route_key = f"{cargo['loading_terminal']}->{a['discharge_terminal']}"
        route     = routes_cache[route_key]
        color     = vessel_colors[a["vessel_id"]]
        lats  = [wp[0] for wp in route["waypoints"]]
        lons  = [wp[1] for wp in route["waypoints"]]
        frame_data.append(go.Scattergeo(
            lat=lats, lon=lons,
            mode="lines",
            line=dict(width=2, color=color, dash="dot"),
            opacity=0.55,
            showlegend=False, hoverinfo="skip",
        ))

    # Terminals
    for t in terminals:
        color  = TERMINAL_LOAD_COLOR if t["type"] == "loading" else TERMINAL_DISCHARGE_COLOR
        symbol = "square" if t["type"] == "loading" else "circle"
        frame_data.append(go.Scattergeo(
            lat=[t["lat"]], lon=[t["lon"]],
            mode="markers+text",
            marker=dict(size=9, color=color, symbol=symbol, opacity=0.85),
            text=[t["id"]], textposition="top center",
            textfont=dict(size=9, color=MUTED_INK),
            showlegend=False,
            hovertemplate=f"<b>{t['name']}</b><br>{t['type']}<br>Berths: {t['berth_count']}<extra></extra>",
        ))

    # Vessels — glow halo + ship glyph, both in the vessel's own color
    for a in enriched_assignments:
        vessel    = vessels_by_id[a["vessel_id"]]
        cargo     = cargoes_by_id[a["cargo_id"]]
        route_key = f"{cargo['loading_terminal']}->{a['discharge_terminal']}"
        route     = routes_cache[route_key]
        state     = get_vessel_state(vessel, cargo, route, day, sim_start, a["discharge_terminal"])
        color     = vessel_colors[a["vessel_id"]]

        hover = (
            f"<b>{vessel['id']}</b><br>"
            f"Class: {vessel['vessel_class']}<br>"
            f"Cargo: {cargo['id']}<br>"
            f"Phase: {state['phase']}<br>"
            f"Fill: {round(state['fill']*100,1)}%<br>"
            f"Volume: {state['volume']:,.0f} mmBtu<extra></extra>"
        )

        # Soft glow halo behind the glyph
        frame_data.append(go.Scattergeo(
            lat=[state["lat"]], lon=[state["lon"]],
            mode="markers",
            marker=dict(size=26, color=color, opacity=0.28, line=dict(width=0)),
            showlegend=False, hovertemplate=hover,
        ))
        # Ship glyph
        frame_data.append(go.Scattergeo(
            lat=[state["lat"]], lon=[state["lon"]],
            mode="text",
            text=[SHIP_GLYPH],
            textfont=dict(size=20, color=color),
            showlegend=False, hoverinfo="skip",
        ))

    return frame_data, routes_cache


# ---------------------------------------------------------------------------
# Side panel — vessel identity, fill reservoir, BOG rate
# ---------------------------------------------------------------------------

def _fill_bar_html(color, fill_pct):
    return f"""
    <div style="background:{TRACK_COLOR};border-radius:5px;height:10px;width:100%;overflow:hidden;">
      <div style="background:{color};width:{fill_pct:.0f}%;height:100%;border-radius:5px;"></div>
    </div>
    """


def _why_this_route(cargo, candidates):
    """One compact line explaining why this destination was chosen.

    FOB cargoes have a fixed destination — there's no real choice. DES
    cargoes are flexible: if a second candidate destination existed, the
    winning margin delta over it is the explanation. `candidates` is the
    list already computed by core.pnl.enrich_assignments_with_pnl — reused
    here rather than recomputed, so the panel always agrees with the price
    the rest of the app used.
    """
    if cargo.get("discharge_terminal"):
        return "Fixed destination (FOB contract)"

    if len(candidates) > 1:
        best, second = candidates[0], candidates[1]
        delta = (best["net_margin_usd"] - second["net_margin_usd"]) / 1e6
        return f"{best['destination_id']} chosen (+{delta:.1f}M$ vs {second['destination_id']})"

    return None


def _render_vessel_card(vessel, color, state, why=None):
    bog_rate_pct = BOILOFF_RATE[vessel["vessel_class"]] * 100
    fill_pct = max(0.0, min(100.0, state["fill"] * 100))

    st.markdown(
        f"<div style='font-weight:600;color:{color};font-size:0.95rem;'>{vessel['id']}</div>"
        f"<div style='color:{MUTED_INK};font-size:0.75rem;margin-bottom:4px;'>"
        f"{vessel['vessel_class']} · {state['phase']}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(_fill_bar_html(color, fill_pct), unsafe_allow_html=True)
    st.markdown(
        f"<div style='display:flex;justify-content:space-between;margin-top:2px;'>"
        f"<span style='color:{MUTED_INK};font-size:0.75rem;'>{fill_pct:.0f}% full</span>"
        f"<span style='background:{TRACK_COLOR};color:{color};font-size:0.72rem;"
        f"padding:1px 7px;border-radius:9px;font-weight:600;'>BOG {bog_rate_pct:.2f}%/day</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
    if why:
        st.markdown(
            f"<div style='color:{MUTED_INK};font-size:0.68rem;margin-top:3px;'>{why}</div>",
            unsafe_allow_html=True,
        )
    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Contracts panel — same `day` clock as the map, so scrubbing the slider
# updates both at once. Shows every cargo (assigned, blocked, or
# unassigned), not just the ones matching the vessel-class filter above.
# ---------------------------------------------------------------------------

PHASE_LABEL = {
    "waiting":     "Awaiting loading",
    "loading":     "Loading",
    "in_transit":  "In transit",
    "discharging": "Discharging",
    "completed":   "Delivered",
}


def _contract_rows(day, enriched, unassigned, vessels, cargoes, terminals, closed_chokepoints):
    cargoes_by_id   = {c["id"]: c for c in cargoes}
    vessels_by_id   = {v["id"]: v for v in vessels}
    terminals_by_id = {t["id"]: t for t in terminals}
    sim_start       = datetime(2025, 3, 1)

    rows = []
    for e in enriched:
        cargo = cargoes_by_id[e["cargo_id"]]
        if not e["feasible"]:
            rows.append({
                "Cargo": e["cargo_id"], "Priority": cargo["priority"],
                "Type": cargo["contract_type"], "Vessel": e["vessel_id"],
                "Destination": "—", "Status": "Blocked (no feasible destination)",
                "Net margin ($)": None,
            })
            continue

        vessel = vessels_by_id[e["vessel_id"]]
        origin = terminals_by_id[cargo["loading_terminal"]]
        dest   = terminals_by_id[e["discharge_terminal"]]
        route  = build_route(origin, dest, closed_chokepoints)
        state  = get_vessel_state(vessel, cargo, route, day, sim_start, e["discharge_terminal"])

        rows.append({
            "Cargo": e["cargo_id"], "Priority": cargo["priority"],
            "Type": cargo["contract_type"], "Vessel": e["vessel_id"],
            "Destination": e["discharge_terminal"], "Status": PHASE_LABEL[state["phase"]],
            "Net margin ($)": e["margin"]["net_margin_usd"],
        })

    for u in unassigned:
        cargo = cargoes_by_id[u["cargo_id"]]
        rows.append({
            "Cargo": u["cargo_id"], "Priority": cargo["priority"],
            "Type": cargo["contract_type"], "Vessel": "—",
            "Destination": "—", "Status": "Unassigned",
            "Net margin ($)": None,
        })

    rows.sort(key=lambda r: -r["Priority"])
    return rows


def _render_contracts_panel(day, enriched, unassigned, vessels, cargoes, terminals, closed_chokepoints):
    st.divider()
    st.subheader("Contracts")
    st.caption(f"Status as of Day {day} — same clock as the map above.")

    rows = _contract_rows(day, enriched, unassigned, vessels, cargoes, terminals, closed_chokepoints)
    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Net margin ($)": st.column_config.NumberColumn(format="$%,.0f"),
        },
    )


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render_map():
    inject_dark_theme()
    st.title("Fleet Map — Animation")

    VESSELS = get_fleet()

    # Sidebar controls
    st.sidebar.subheader("Simulation")

    if "fleet_playing" not in st.session_state:
        st.session_state.fleet_playing = False
    if "fleet_day_slider" not in st.session_state:
        st.session_state.fleet_day_slider = 0

    # Advance the slider's own widget state BEFORE the slider is instantiated
    # this run — Streamlit forbids writing to a widget's session_state key
    # after that widget has been created in the same run, so this must
    # happen up here, not in the end-of-function auto-advance block.
    if st.session_state.fleet_playing:
        current  = st.session_state.get("fleet_day_slider", 0)
        next_day = min(current + 1, 45)
        st.session_state.fleet_day_slider = next_day
        if next_day >= 45:
            st.session_state.fleet_playing = False

    col_play, col_pause = st.sidebar.columns(2)
    if col_play.button("▶ Play", use_container_width=True):
        st.session_state.fleet_playing = True
    if col_pause.button("⏸ Pause", use_container_width=True):
        st.session_state.fleet_playing = False

    day = st.sidebar.slider("Day", 0, 45, key="fleet_day_slider")

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
    enriched    = enrich_assignments_with_pnl(result["assignments"], CARGOES, VESSELS, TERMINALS, closed)
    assignments = [a for a in enriched
                   if a["feasible"] and any(v["id"] == a["vessel_id"] and v["vessel_class"] in filter_class
                          for v in VESSELS)]

    if not assignments:
        st.warning("No assignments to display.")
        return

    vessel_colors = assign_vessel_colors([a["vessel_id"] for a in assignments])

    frame_data, routes_cache = build_day_data(
        assignments, VESSELS, CARGOES, TERMINALS, day, vessel_colors, closed)

    current_date = datetime(2025, 3, 1) + timedelta(days=day)

    fig = go.Figure(
        data=frame_data,
        layout=go.Layout(
            paper_bgcolor=PAGE_BG,
            plot_bgcolor=PAGE_BG,
            font=dict(color=MUTED_INK),
            title_text=f"Day {day} — {current_date.strftime('%B %d, 2025')}",
            geo=dict(
                showland=True, landcolor=LAND_COLOR,
                showocean=True, oceancolor=OCEAN_COLOR,
                showcoastlines=True, coastlinecolor=COAST_COLOR,
                showcountries=True, countrycolor=COUNTRY_COLOR,
                bgcolor=CHART_BG,
                projection_type="natural earth",
            ),
            height=580,
            margin=dict(l=0, r=0, t=40, b=0),
        ),
    )

    col_map, col_panel = st.columns([3, 1])

    with col_map:
        st.plotly_chart(fig, use_container_width=True)

    with col_panel:
        st.markdown("**Fleet**")

        sim_start = datetime(2025, 3, 1)
        cargoes_by_id   = {c["id"]: c for c in CARGOES}
        vessels_by_id   = {v["id"]: v for v in VESSELS}

        for a in assignments:
            vessel = vessels_by_id[a["vessel_id"]]
            cargo  = cargoes_by_id[a["cargo_id"]]
            route_key = f"{cargo['loading_terminal']}->{a['discharge_terminal']}"
            route = routes_cache[route_key]
            state = get_vessel_state(vessel, cargo, route, day, sim_start, a["discharge_terminal"])
            why = _why_this_route(cargo, a["candidates"])
            _render_vessel_card(vessel, vessel_colors[a["vessel_id"]], state, why)

    # Disruption impact
    if closed:
        st.warning(f"Closed chokepoints: {', '.join(closed)}")
        for u in result["unassigned"]:
            st.error(f"{u['cargo_id']} unassigned — {u['reason']}")
        for e in enriched:
            if not e["feasible"]:
                st.error(f"{e['cargo_id']} assigned to {e['vessel_id']} but no feasible "
                         f"destination given closed chokepoints")

    _render_contracts_panel(day, enriched, result["unassigned"], VESSELS, CARGOES, TERMINALS, closed)

    # Play/Pause auto-advance — a full Streamlit rerun per tick keeps the map
    # and side panel on the same `day` clock (no Plotly-side animation, so no
    # risk of the two drifting apart). The actual increment happens above,
    # before the slider widget is instantiated; here we just pace the ticks
    # and trigger the next rerun.
    if st.session_state.fleet_playing:
        time.sleep(0.5)
        st.rerun()


if __name__ == "__main__":
    render_map()
