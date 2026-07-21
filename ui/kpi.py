# ui/kpi.py
# KPI dashboard: global fleet performance metrics.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from data.vessels    import VESSELS
from data.terminals  import TERMINALS
from data.cargoes    import CARGOES
from core.optimizer  import assign_cargoes
from core.pnl        import enrich_assignments_with_pnl
from ui.fleet_state  import get_fleet
from ui.theme        import inject_dark_theme, hero_metric, STATUS_GOOD, STATUS_CRITICAL


def compute_kpis(enriched_assignments, cargoes, vessels):
    """
    Aggregate fleet-level KPIs from assignments already enriched with P&L
    (core/pnl.py) — BOG/margin figures are reused as-is, not recomputed,
    so this page always agrees with the P&L page for the same fleet.
    """
    assigned_vessel_ids = {a["vessel_id"] for a in enriched_assignments}
    feasible             = [a for a in enriched_assignments if a["feasible"]]
    feasible_cargo_ids   = {a["cargo_id"] for a in feasible}

    fleet_utilization = len(assigned_vessel_ids) / len(vessels) * 100
    total_volume      = sum(c["volume_mmbtu"] for c in cargoes if c["id"] in feasible_cargo_ids)

    total_bog_mmbtu   = sum(a["margin"]["gross_bog_mmbtu"]   for a in feasible)
    total_bog_usd     = sum(a["margin"]["bog_cost_usd"]      for a in feasible)
    total_bunker_usd  = sum(a["margin"]["bunker_saving_usd"] for a in feasible)
    total_net_margin  = sum(a["margin"]["net_margin_usd"]    for a in feasible)

    return {
        "fleet_utilization_pct":   round(fleet_utilization, 1),
        "total_volume_mmbtu":      round(total_volume, 0),
        "total_bog_mmbtu":         round(total_bog_mmbtu, 0),
        "total_bog_usd":           round(total_bog_usd, 0),
        "total_bunker_saving_usd": round(total_bunker_usd, 0),
        "total_net_margin_usd":    round(total_net_margin, 0),
        "unassigned_count":        len(cargoes) - len(feasible_cargo_ids),
    }


def render_kpi():
    inject_dark_theme()
    st.title("KPI Dashboard")

    VESSELS = get_fleet()
    result   = assign_cargoes(CARGOES, VESSELS, TERMINALS)
    enriched = enrich_assignments_with_pnl(result["assignments"], CARGOES, VESSELS, TERMINALS)
    kpis     = compute_kpis(enriched, CARGOES, VESSELS)

    hero_metric("Total fleet net margin", f"${kpis['total_net_margin_usd']/1e6:,.1f}M",
                accent=STATUS_GOOD if kpis["total_net_margin_usd"] >= 0 else STATUS_CRITICAL)

    st.divider()
    st.subheader("Fleet")
    col1, col2, col3 = st.columns(3)
    col1.metric("Fleet utilization",  f"{kpis['fleet_utilization_pct']}%")
    col2.metric("Cargoes deliverable", f"{len(CARGOES) - kpis['unassigned_count']} / {len(CARGOES)}")
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

    if result["unassigned"] or any(not a["feasible"] for a in enriched):
        st.divider()
        st.subheader("Unassigned / infeasible cargoes")
        for u in result["unassigned"]:
            st.warning(f"**{u['cargo_id']}** — {u['reason']}")
        for a in enriched:
            if not a["feasible"]:
                st.warning(f"**{a['cargo_id']}** — assigned to {a['vessel_id']} "
                           f"but no feasible destination (draft/route)")
