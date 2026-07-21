# ui/pnl.py
# P&L page: economic destination decisions per cargo.
# One clean result line per cargo (vessel -> destination -> margin), the
# full destination comparison only shown on demand — the comparison is the
# reasoning, not the headline.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd

from data.vessels    import VESSELS
from data.terminals  import TERMINALS
from data.cargoes    import CARGOES
from core.optimizer  import assign_cargoes
from core.pnl        import enrich_assignments_with_pnl, format_decision_text
from ui.fleet_state  import get_fleet
from ui.theme        import (inject_dark_theme, hero_metric, badge_html, SURFACE, BORDER,
                              TEXT_PRIMARY, TEXT_MUTED, STATUS_GOOD, STATUS_CRITICAL, STATUS_WARNING)


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


def _result_row(cargo, a):
    flexible = cargo["discharge_terminal"] is None
    type_color = "#a99bff" if flexible else "#7fd4ff"
    type_label = "DES" if flexible else "FOB"

    if not a["feasible"]:
        st.markdown(
            f"<div style='background:{SURFACE};border:1px solid {BORDER};border-radius:10px;"
            f"padding:12px 16px;margin-bottom:8px;'>"
            f"{badge_html(a['cargo_id'], type_color)} {badge_html(type_label, TEXT_MUTED)} "
            f"<span style='color:{STATUS_CRITICAL};margin-left:8px;'>No feasible destination "
            f"(draft incompatible or route blocked at every candidate)</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        return

    margin = a["margin"]["net_margin_usd"]
    margin_color = STATUS_GOOD if margin >= 0 else STATUS_CRITICAL

    st.markdown(
        f"<div style='background:{SURFACE};border:1px solid {BORDER};border-radius:10px;"
        f"padding:12px 16px;margin-bottom:8px;display:flex;align-items:center;"
        f"justify-content:space-between;flex-wrap:wrap;gap:8px;'>"
        f"<div>{badge_html(a['cargo_id'], type_color)} {badge_html(type_label, TEXT_MUTED)} "
        f"<span style='color:{TEXT_PRIMARY};margin-left:6px;'>{a['vessel_id']} → "
        f"<b>{a['discharge_terminal']}</b></span></div>"
        f"<div style='color:{margin_color};font-weight:700;font-size:1.1rem;'>"
        f"${margin/1e6:,.1f}M</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    if len(a["candidates"]) > 1:
        with st.expander(f"Compare {len(a['candidates'])} candidate destinations"):
            st.dataframe(candidates_to_dataframe(a["candidates"]), use_container_width=True, hide_index=True)
            st.code(format_decision_text(a["cargo_id"], {"chosen": a["margin"], "candidates": a["candidates"]}))


def render_pnl():
    inject_dark_theme()
    st.title("P&L — Destination Decisions")
    st.caption("DES cargoes: destination chosen to maximize net margin. FOB cargoes: fixed destination.")

    VESSELS = get_fleet()
    result   = assign_cargoes(CARGOES, VESSELS, TERMINALS)
    enriched = enrich_assignments_with_pnl(result["assignments"], CARGOES, VESSELS, TERMINALS)
    cargoes_by_id = {c["id"]: c for c in CARGOES}

    total_margin = sum(a["margin"]["net_margin_usd"] for a in enriched if a["feasible"])
    hero_metric("Total fleet net margin", f"${total_margin/1e6:,.1f}M",
                accent=STATUS_GOOD if total_margin >= 0 else STATUS_CRITICAL)

    st.divider()

    for a in enriched:
        cargo = cargoes_by_id[a["cargo_id"]]
        _result_row(cargo, a)

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


if __name__ == "__main__":
    render_pnl()
