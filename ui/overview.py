# ui/overview.py
# Landing page — first thing a visitor sees. Answers "what is this tool"
# in a few seconds: headline, live fleet metrics, capability grid, nav guide.
# No paragraphs — stat tiles and short cards only.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from data.cargoes    import CARGOES
from data.terminals  import TERMINALS
from core.optimizer  import assign_cargoes
from core.pnl        import enrich_assignments_with_pnl
from ui.fleet_state  import get_fleet
from ui.kpi          import compute_kpis
from ui.theme        import (inject_dark_theme, SURFACE, BORDER,
                              TEXT_PRIMARY, TEXT_MUTED, STATUS_GOOD)


CAPABILITIES = [
    ("🧭", "Dynamic routing", "Suez / Panama / Hormuz, auto reroute if closed"),
    ("📊", "MILP net margin", "Vessel + destination optimized together"),
    ("💵", "P&L per destination", "JKM vs TTF, decision explained"),
    ("⚠️", "Disruption simulator", "$ impact of a delay or closure"),
    ("🚢", "Fleet management", "Add vessels on the fly"),
    ("🌡️", "Real physics", "Boil-off, heel, demurrage"),
]

NAV_GUIDE = [
    ("Fleet Map",            "Animated fleet on world map"),
    ("Gantt Schedule",       "Cargo / vessel scheduling"),
    ("Alerts",               "Violated constraints, at-risk cargoes"),
    ("KPI Dashboard",        "Margin, utilization, volumes"),
    ("P&L",                  "Margin detail per cargo and destination"),
    ("Disruption Simulator", "Simulate closure / delay, see the impact"),
    ("Fleet Management",     "Add or remove vessels"),
]


def _metric_card(label, value, accent=TEXT_PRIMARY):
    st.markdown(
        f"<div style='background:{SURFACE};border:1px solid {BORDER};"
        f"border-radius:10px;padding:16px 18px;text-align:center;'>"
        f"<div style='color:{TEXT_MUTED};font-size:0.78rem;text-transform:uppercase;"
        f"letter-spacing:0.04em;margin-bottom:6px;'>{label}</div>"
        f"<div style='color:{accent};font-size:1.6rem;font-weight:700;'>{value}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _capability_card(icon, title, detail):
    st.markdown(
        f"<div style='background:{SURFACE};border:1px solid {BORDER};"
        f"border-radius:10px;padding:12px 16px;white-space:nowrap;overflow:hidden;"
        f"text-overflow:ellipsis;'>"
        f"<span style='font-size:1.1rem;margin-right:8px;'>{icon}</span>"
        f"<span style='color:{TEXT_PRIMARY};font-weight:600;font-size:0.88rem;'>{title}</span>"
        f"<span style='color:{TEXT_MUTED};font-size:0.8rem;'> — {detail}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _nav_row(name, detail):
    st.markdown(
        f"<div style='padding:6px 0;border-bottom:1px solid {BORDER};'>"
        f"<span style='color:{TEXT_PRIMARY};font-weight:600;font-size:0.88rem;'>{name}</span>"
        f"<span style='color:{TEXT_MUTED};font-size:0.85rem;'> — {detail}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_overview():
    inject_dark_theme()

    st.title("LNG Scheduler & Asset Optimizer")
    st.markdown(
        f"<div style='color:{TEXT_MUTED};font-size:1rem;margin-top:-8px;margin-bottom:20px;'>"
        f"LNG fleet scheduling & economic optimization — assignment, routing, "
        f"P&amp;L, disruption simulation, all in one.</div>",
        unsafe_allow_html=True,
    )

    # -- Live metrics, computed exactly like ui/kpi.py (same fleet, no disruption) --
    vessels  = get_fleet()
    result   = assign_cargoes(CARGOES, vessels, TERMINALS)
    enriched = enrich_assignments_with_pnl(result["assignments"], CARGOES, vessels, TERMINALS)
    kpis     = compute_kpis(enriched, CARGOES, vessels)

    delivered = len(CARGOES) - kpis["unassigned_count"]

    col1, col2, col3 = st.columns(3)
    with col1:
        _metric_card("Fleet net margin", f"${kpis['total_net_margin_usd']/1e6:,.1f}M", STATUS_GOOD)
    with col2:
        _metric_card("Cargoes delivered", f"{delivered} / {len(CARGOES)}")
    with col3:
        _metric_card("Fleet utilization", f"{kpis['fleet_utilization_pct']}%")

    st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)

    # -- Capabilities grid --
    st.subheader("What it does")
    cap_cols = st.columns(3)
    for i, (icon, title, detail) in enumerate(CAPABILITIES):
        with cap_cols[i % 3]:
            _capability_card(icon, title, detail)
            st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

    # -- Navigation guide --
    st.subheader("Pages")
    for name, detail in NAV_GUIDE:
        _nav_row(name, detail)
