# ui/overview.py
# Landing page — has to read in five seconds. One hero number, three
# supporting facts, and nothing else. Every detail behind these numbers
# (which vessel, which cargo, which trade) lives one click away on its
# own page — this page states the headline, it doesn't re-explain it.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from data.cargoes    import CARGOES
from data.terminals  import TERMINALS
from core.optimizer  import assign_cargoes
from core.pnl        import enrich_assignments_with_pnl
from core.spot       import simulate_spot_market
from ui.fleet_state  import get_fleet
from ui.theme        import inject_dark_theme, hero_metric, STATUS_GOOD, STATUS_CRITICAL


def render_overview():
    inject_dark_theme()

    st.title("LNG Scheduler & Asset Optimizer")

    vessels  = get_fleet()
    result   = assign_cargoes(CARGOES, vessels, TERMINALS)
    enriched = enrich_assignments_with_pnl(result["assignments"], CARGOES, vessels, TERMINALS)
    spot     = simulate_spot_market(vessels, TERMINALS, CARGOES, enriched, n_days=46)

    contract_margin = sum(a["margin"]["net_margin_usd"] for a in enriched if a["feasible"])
    spot_realized   = spot["summary"]["total_realized_margin_usd"]
    total_pnl       = contract_margin + spot_realized

    hero_metric(
        "Total net P&L",
        f"${total_pnl/1e6:,.1f}M",
        sublabel=f"Contracts ${contract_margin/1e6:,.1f}M + Spot (realized) ${spot_realized/1e6:,.1f}M",
        accent=STATUS_GOOD if total_pnl >= 0 else STATUS_CRITICAL,
    )

    vessels_deployed = len({a["vessel_id"] for a in enriched if a["feasible"]})
    cargoes_covered  = len(CARGOES) - len(result["unassigned"])
    wins, losses     = spot["summary"]["wins"], spot["summary"]["losses"]

    col1, col2, col3 = st.columns(3)
    col1.metric("Vessels deployed", f"{vessels_deployed} / {len(vessels)}")
    col2.metric("Cargoes covered",  f"{cargoes_covered} / {len(CARGOES)}")
    col3.metric("Spot trades this month", f"{wins}W / {losses}L")

    critical_unassigned = [
        u for u in result["unassigned"]
        if next(c["priority"] for c in CARGOES if c["id"] == u["cargo_id"]) >= 8
    ]
    if critical_unassigned:
        ids = ", ".join(u["cargo_id"] for u in critical_unassigned)
        st.error(f"High-priority cargo unassigned: {ids} — see KPI Dashboard for why.")


if __name__ == "__main__":
    render_overview()
