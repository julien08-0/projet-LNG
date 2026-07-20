# ui/pnl.py
# P&L page: economic destination decisions per cargo.
# Shows, for each assigned cargo, the margin comparison across every
# candidate destination and the reasoning behind the chosen one.

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
from ui.theme        import inject_dark_theme


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


def render_pnl():
    inject_dark_theme()
    st.title("P&L — Destination Decisions")
    st.caption("DES cargoes: destination chosen to maximize net margin. FOB cargoes: fixed destination.")

    VESSELS = get_fleet()
    result   = assign_cargoes(CARGOES, VESSELS, TERMINALS)
    enriched = enrich_assignments_with_pnl(result["assignments"], CARGOES, VESSELS, TERMINALS)
    cargoes_by_id = {c["id"]: c for c in CARGOES}

    total_margin = sum(a["margin"]["net_margin_usd"] for a in enriched if a["feasible"])
    st.metric("Total fleet net margin", f"${total_margin:,.0f}")

    st.divider()

    for a in enriched:
        cargo    = cargoes_by_id[a["cargo_id"]]
        flexible = cargo["discharge_terminal"] is None
        label    = "DES — flexible destination" if flexible else "FOB — fixed destination"

        st.subheader(f"{a['cargo_id']} · {label} · {a['vessel_id']}")

        if not a["feasible"]:
            st.error("No feasible destination (draft incompatible or route blocked "
                     "by closed chokepoint at every candidate).")
            st.divider()
            continue

        st.dataframe(candidates_to_dataframe(a["candidates"]), use_container_width=True, hide_index=True)
        with st.expander("Decision detail"):
            st.code(format_decision_text(a["cargo_id"], {"chosen": a["margin"], "candidates": a["candidates"]}))

        st.divider()

    if result["unassigned"]:
        st.subheader("Unassigned cargoes")
        for u in result["unassigned"]:
            st.warning(f"**{u['cargo_id']}** — {u['reason']}")


if __name__ == "__main__":
    render_pnl()
