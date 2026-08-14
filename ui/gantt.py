# ui/gantt.py
# Gantt chart: vessel schedule over the horizon.
# Green = on time, Orange = tight window, Red = delivery window breached.
#
# Doesn't carry enough on its own to justify a standalone nav page — it's
# the same fleet/contracts as the Fleet Map, just viewed on a time axis
# instead of a geographic one. Embedded there (in an expander) via
# render_gantt_chart(), which takes the assignments already computed by
# the caller so it reflects the same disruption scenario, not a fresh one.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import plotly.graph_objects as go
from datetime import datetime, timedelta

from core.routing    import build_route
from core.physics    import calculate_eta
from ui.theme        import PAGE_BG, TEXT_MUTED, BORDER, ACCENT, STATUS_GOOD, STATUS_WARNING, STATUS_CRITICAL


def build_gantt_data(enriched_assignments, cargoes, vessels, terminals):
    cargoes_by_id   = {c["id"]: c for c in cargoes}
    vessels_by_id   = {v["id"]: v for v in vessels}
    terminals_by_id = {t["id"]: t for t in terminals}
    bars = []

    for a in enriched_assignments:
        if not a["feasible"]:
            continue

        cargo  = cargoes_by_id[a["cargo_id"]]
        vessel = vessels_by_id[a["vessel_id"]]

        loading_start = datetime.fromisoformat(cargo["laycan_start"])
        loading_end   = loading_start + timedelta(hours=24)

        origin = terminals_by_id[cargo["loading_terminal"]]
        dest   = terminals_by_id[a["discharge_terminal"]]
        route  = build_route(origin, dest)

        eta = calculate_eta(
            departure_date_iso=loading_end.isoformat(timespec="minutes"),
            distance_nm=route["distance_nm"],
            speed_knots=vessel["laden_speed_knots"],
            weather_delay_hours=route["weather_delay_hours"],
            canal_delay_hours=route["canal_delay_hours"],
        )

        discharge_start = datetime.fromisoformat(eta["eta_iso"])
        discharge_end   = discharge_start + timedelta(hours=24)

        dw_start = datetime.fromisoformat(cargo["delivery_window_start"])
        dw_end   = datetime.fromisoformat(cargo["delivery_window_end"])

        if discharge_start > dw_end:
            color = "red"
        elif discharge_start < dw_start:
            color = "orange"
        else:
            color = "green"

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


def render_gantt_chart(enriched, cargoes, vessels, terminals, unassigned):
    """Draws the Gantt figure + legend + unassigned list. No title/theme
    injection — meant to be embedded inside another page's layout (e.g.
    inside an expander on the Fleet Map)."""
    bars = build_gantt_data(enriched, cargoes, vessels, terminals)

    fig = go.Figure()

    for bar in bars:
        fig.add_trace(go.Bar(
            name=bar["cargo"],
            x=[(bar["loading_end"] - bar["loading_start"]).total_seconds() / 86400],
            y=[bar["vessel"]],
            base=[(bar["loading_start"] - datetime(2025, 3, 1)).total_seconds() / 86400],
            orientation="h",
            marker=dict(color=ACCENT, opacity=0.75, line=dict(width=0)),
            hovertemplate=(
                f"<b>{bar['cargo']}</b><br>"
                f"Loading: {bar['loading_start'].strftime('%b %d %H:%M')} → "
                f"{bar['loading_end'].strftime('%b %d %H:%M')}<extra></extra>"
            ),
            showlegend=False,
        ))

        color_map = {"green": STATUS_GOOD, "orange": STATUS_WARNING, "red": STATUS_CRITICAL}
        fig.add_trace(go.Bar(
            name=bar["cargo"],
            x=[(bar["discharge_end"] - bar["loading_end"]).total_seconds() / 86400],
            y=[bar["vessel"]],
            base=[(bar["loading_end"] - datetime(2025, 3, 1)).total_seconds() / 86400],
            orientation="h",
            marker=dict(color=color_map[bar["color"]], opacity=0.9, line=dict(width=0)),
            hovertemplate=(
                f"<b>{bar['cargo']}</b><br>"
                f"Discharge: {bar['discharge_start'].strftime('%b %d %H:%M')} → "
                f"{bar['discharge_end'].strftime('%b %d %H:%M')}<extra></extra>"
            ),
            showlegend=False,
        ))

    fig.update_layout(
        barmode="stack",
        bargap=0.55,
        xaxis=dict(title="Days from March 1, 2025", range=[0, 45], gridcolor=BORDER),
        yaxis=dict(title=None),
        height=70 + 42 * len({bar["vessel"] for bar in bars}),
        margin=dict(l=10, r=10, t=10, b=40),
        plot_bgcolor=PAGE_BG,
        paper_bgcolor=PAGE_BG,
        font=dict(color=TEXT_MUTED, size=12),
    )

    st.plotly_chart(fig, use_container_width=True)

    col1, col2, col3 = st.columns(3)
    col1.success("🟢 On time")
    col2.warning("🟠 Early / tight")
    col3.error("🔴 Delivery window breached")

    if unassigned:
        st.subheader("Unassigned cargoes")
        for u in unassigned:
            st.error(f"**{u['cargo_id']}** — {u['reason']}")


if __name__ == "__main__":
    from data.vessels    import VESSELS
    from data.cargoes    import CARGOES
    from data.terminals  import TERMINALS
    from core.optimizer  import assign_cargoes
    from core.pnl        import enrich_assignments_with_pnl
    from ui.theme        import inject_theme

    inject_theme()
    st.title("Gantt (standalone preview)")
    result   = assign_cargoes(CARGOES, VESSELS, TERMINALS)
    enriched = enrich_assignments_with_pnl(result["assignments"], CARGOES, VESSELS, TERMINALS)
    render_gantt_chart(enriched, CARGOES, VESSELS, TERMINALS, result["unassigned"])
