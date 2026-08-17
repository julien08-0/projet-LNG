# ui/pnl.py
# P&L & KPIs page: economic destination decisions per cargo, schedule, and
# global fleet performance metrics — all built from the same assignments so
# every figure on the page agrees with every other.
# The bar chart carries the hierarchy (which cargo makes the most money,
# at a glance, by bar length) — the rows below are detail, not a second
# attempt at the same comparison.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from data.vessels    import VESSELS
from data.terminals  import TERMINALS
from data.cargoes    import CARGOES
from core.optimizer  import assign_cargoes
from core.pnl        import enrich_assignments_with_pnl, format_decision_text
from ui.alerts       import detect_alerts, render_alerts_section
from ui.gantt        import render_gantt_chart
from ui.fleet_state  import get_fleet
from ui.theme        import (inject_theme, hero_metric, badge_html, PAGE_BG, CHART_BG, BORDER,
                              TEXT_PRIMARY, TEXT_MUTED, STATUS_GOOD, STATUS_CRITICAL, STATUS_WARNING,
                              VESSEL_PALETTE, TERMINAL_LOAD_COLOR)


def compute_kpis(enriched_assignments, cargoes, vessels):
    """
    Aggregate fleet-level KPIs from assignments already enriched with P&L
    (core/pnl.py) — BOG/margin figures are reused as-is, not recomputed,
    so this page always agrees with the P&L page for the same fleet.
    """
    assigned_vessel_ids = {a["vessel_id"] for a in enriched_assignments}
    feasible             = [a for a in enriched_assignments if a["feasible"]]
    feasible_cargo_ids   = {a["cargo_id"] for a in feasible}

    total_volume      = sum(c["volume_mmbtu"] for c in cargoes if c["id"] in feasible_cargo_ids)

    total_bog_mmbtu   = sum(a["margin"]["gross_bog_mmbtu"]   for a in feasible)
    total_bog_usd     = sum(a["margin"]["bog_cost_usd"]      for a in feasible)
    total_bunker_usd  = sum(a["margin"]["bunker_saving_usd"] for a in feasible)
    total_net_margin  = sum(a["margin"]["net_margin_usd"]    for a in feasible)

    return {
        # Two different denominators on purpose: a vessel is "deployed" once
        # it's working a cargo; a cargo is "covered" once a vessel is working
        # it. With more cargoes than vessels, 100% vessel deployment can
        # still leave a cargo uncovered — that's not a contradiction, see
        # the caption in render_pnl().
        "vessels_deployed":        len(assigned_vessel_ids),
        "vessels_total":           len(vessels),
        "cargoes_covered":         len(feasible_cargo_ids),
        "cargoes_total":           len(cargoes),
        "total_volume_mmbtu":      round(total_volume, 0),
        "total_bog_mmbtu":         round(total_bog_mmbtu, 0),
        "total_bog_usd":           round(total_bog_usd, 0),
        "total_bunker_saving_usd": round(total_bunker_usd, 0),
        "total_net_margin_usd":    round(total_net_margin, 0),
        "unassigned_count":        len(cargoes) - len(feasible_cargo_ids),
    }


def candidates_to_dataframe(candidates):
    rows = []
    for c in candidates:
        rows.append({
            "Destination":    c["destination_id"],
            "Marker":         c["price_marker"],
            "Price $/mmBtu":  round(c["price_usd_mmbtu"], 2),
            "Revenue $":      round(c["revenue_usd"]),
            "Net BOG cost $": round(c["net_bog_cost_usd"]),
            "Transport $":    round(c["transport_cost_usd"]),
            "Canal toll $":   round(c["canal_toll_usd"]),
            "Demurrage $":    round(c["demurrage_usd"]),
            "Net margin $":   round(c["net_margin_usd"]),
        })
    return pd.DataFrame(rows)


def _margin_chart(feasible_sorted):
    """One bar per assigned cargo, sorted by margin — the ranking IS the point,
    so length does the work instead of asking the reader to compare numbers."""
    labels  = [f"{a['cargo_id']} · {a['vessel_id']}" for a in feasible_sorted]
    values  = [a["margin"]["net_margin_usd"] / 1e6 for a in feasible_sorted]
    colors  = [STATUS_GOOD if v >= 0 else STATUS_CRITICAL for v in values]

    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker=dict(color=colors, opacity=0.9, line=dict(width=0)),
        text=[f"${v:,.1f}M" for v in values],
        textposition="outside",
        hoverinfo="skip",
    ))
    fig.update_layout(
        bargap=0.5,
        paper_bgcolor=PAGE_BG, plot_bgcolor=CHART_BG,
        font=dict(color=TEXT_MUTED),
        margin=dict(l=10, r=50, t=10, b=10),
        height=70 + 38 * len(labels),
        xaxis=dict(title="Net margin ($M)", gridcolor=BORDER),
        yaxis=dict(autorange="reversed"),
    )
    return fig


def _detail_row(cargo, a):
    flexible = cargo["discharge_terminal"] is None
    type_color = VESSEL_PALETTE[6] if flexible else TERMINAL_LOAD_COLOR
    type_label = "DES" if flexible else "FOB"

    st.markdown(
        f"<div style='font-size:0.85rem;color:{TEXT_MUTED};margin-bottom:2px;'>"
        f"{badge_html(a['cargo_id'], type_color)} {badge_html(type_label, TEXT_MUTED)} "
        f"<span style='color:{TEXT_PRIMARY};margin-left:4px;'>{a['vessel_id']} → "
        f"{a['discharge_terminal']}</span></div>",
        unsafe_allow_html=True,
    )
    if len(a["candidates"]) > 1:
        with st.expander(f"{a['cargo_id']}: compare {len(a['candidates'])} candidate destinations"):
            st.dataframe(candidates_to_dataframe(a["candidates"]), use_container_width=True, hide_index=True)
            st.code(format_decision_text(a["cargo_id"], {"chosen": a["margin"], "candidates": a["candidates"]}))
    st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)


def render_pnl():
    inject_theme()
    st.title("P&L & KPIs")
    st.caption("Destination decisions, schedule, and fleet performance.")

    VESSELS = get_fleet()
    result   = assign_cargoes(CARGOES, VESSELS, TERMINALS)
    enriched = enrich_assignments_with_pnl(result["assignments"], CARGOES, VESSELS, TERMINALS)
    cargoes_by_id = {c["id"]: c for c in CARGOES}

    feasible = [a for a in enriched if a["feasible"]]
    infeasible = [a for a in enriched if not a["feasible"]]
    total_margin = sum(a["margin"]["net_margin_usd"] for a in feasible)

    hero_metric("Total fleet net margin", f"${total_margin/1e6:,.1f}M",
                accent=STATUS_GOOD if total_margin >= 0 else STATUS_CRITICAL)

    feasible_sorted = sorted(feasible, key=lambda a: a["margin"]["net_margin_usd"], reverse=True)
    st.plotly_chart(_margin_chart(feasible_sorted), use_container_width=True)

    st.divider()
    st.subheader("Schedule (Gantt)")
    render_gantt_chart(enriched, CARGOES, VESSELS, TERMINALS, result["unassigned"])

    st.divider()
    st.subheader("Detail")

    for a in feasible_sorted:
        _detail_row(cargoes_by_id[a["cargo_id"]], a)

    for a in infeasible:
        st.markdown(
            f"<div style='font-size:0.85rem;margin-bottom:6px;'>"
            f"{badge_html(a['cargo_id'], STATUS_CRITICAL)} "
            f"<span style='color:{STATUS_CRITICAL};'>No feasible destination "
            f"(draft incompatible or route blocked at every candidate)</span></div>",
            unsafe_allow_html=True,
        )

    if result["unassigned"]:
        st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
        st.subheader("Unassigned cargoes")
        for u in result["unassigned"]:
            priority = cargoes_by_id[u["cargo_id"]]["priority"]
            color = STATUS_CRITICAL if priority >= 8 else STATUS_WARNING
            st.markdown(
                f"<div style='margin-bottom:6px;font-size:0.88rem;'>"
                f"{badge_html(u['cargo_id'], color)} <span style='color:{TEXT_MUTED};'>{u['reason']}</span></div>",
                unsafe_allow_html=True,
            )

    st.divider()

    kpis = compute_kpis(enriched, CARGOES, VESSELS)

    st.subheader("Fleet")
    col1, col2, col3 = st.columns(3)
    col1.metric("Vessels deployed", f"{kpis['vessels_deployed']} / {kpis['vessels_total']}")
    col2.metric("Cargoes covered",  f"{kpis['cargoes_covered']} / {kpis['cargoes_total']}")
    col3.metric("Unassigned cargoes", kpis["unassigned_count"])
    if kpis["vessels_deployed"] == kpis["vessels_total"] and kpis["unassigned_count"] > 0:
        st.caption(
            "Every vessel is deployed (100% of the fleet) and a cargo is still "
            "unassigned — not a contradiction: there are more cargoes than "
            "vessels this month, so full fleet deployment is the ceiling, not "
            "full cargo coverage. See the alert below for which one and why."
        )

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
    col2.metric("Net BOG cost", f"${kpis['total_bog_usd'] - kpis['total_bunker_saving_usd']:,.0f}")

    st.divider()
    alerts = detect_alerts(result["assignments"], CARGOES, VESSELS, TERMINALS)
    render_alerts_section(alerts)


if __name__ == "__main__":
    render_pnl()
