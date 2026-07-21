# ui/overview.py
# Command center — the one page that has to be read in 5 seconds. Answers,
# at a glance: what's the fleet doing (under contract or free), what's the
# state of the contract book, what's the spot market saying today, and what
# is the whole thing worth. Everything else (per-cargo detail, the full
# animated map, the trade blotter) lives one click away on its own page —
# this page is the summary, not the detail.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd

from data.cargoes    import CARGOES
from data.terminals  import TERMINALS
from core.optimizer  import assign_cargoes
from core.pnl        import enrich_assignments_with_pnl
from core.spot       import simulate_spot_market
from ui.fleet_state  import get_fleet
from ui.theme        import (inject_dark_theme, hero_metric, badge_html, SURFACE, BORDER,
                              TEXT_PRIMARY, TEXT_MUTED, STATUS_GOOD, STATUS_WARNING, STATUS_CRITICAL)

MARKER_ACCENT = {"JKM": "#f5b400", "TTF": "#3987e5", "HH": "#39e639"}


def _panel_open():
    st.markdown(
        f"<div style='background:{SURFACE};border:1px solid {BORDER};border-radius:10px;"
        f"padding:14px 16px;height:100%;'>",
        unsafe_allow_html=True,
    )


def _panel_close():
    st.markdown("</div>", unsafe_allow_html=True)


def _panel_title(text):
    st.markdown(
        f"<div style='color:{TEXT_PRIMARY};font-weight:700;font-size:0.95rem;"
        f"margin-bottom:10px;'>{text}</div>",
        unsafe_allow_html=True,
    )


def render_overview():
    inject_dark_theme()

    st.title("LNG Scheduler & Asset Optimizer")
    st.markdown(
        f"<div style='color:{TEXT_MUTED};font-size:0.95rem;margin-top:-8px;margin-bottom:18px;'>"
        f"Fleet scheduling and economic optimization — one glance for the headline, "
        f"one click into any page for the detail.</div>",
        unsafe_allow_html=True,
    )

    vessels  = get_fleet()
    result   = assign_cargoes(CARGOES, vessels, TERMINALS)
    enriched = enrich_assignments_with_pnl(result["assignments"], CARGOES, vessels, TERMINALS)
    spot     = simulate_spot_market(vessels, TERMINALS, CARGOES, enriched, n_days=46)

    contract_margin = sum(a["margin"]["net_margin_usd"] for a in enriched if a["feasible"])
    spot_realized   = spot["summary"]["total_realized_margin_usd"]
    total_pnl       = contract_margin + spot_realized

    # -- Hero: the one number that matters most --
    hero_metric(
        "Total net P&L",
        f"${total_pnl/1e6:,.1f}M",
        sublabel=f"Contracts ${contract_margin/1e6:,.1f}M  +  Spot (realized) ${spot_realized/1e6:,.1f}M",
        accent=STATUS_GOOD if total_pnl >= 0 else STATUS_CRITICAL,
    )

    col_fleet, col_contracts, col_spot = st.columns(3)

    # -- Fleet: under contract or free --
    with col_fleet:
        _panel_open()
        committed_ids = {a["vessel_id"] for a in enriched if a["feasible"]}
        _panel_title(f"Fleet — {len(committed_ids)}/{len(vessels)} under contract")

        rows = []
        for v in vessels:
            match = next((a for a in enriched if a["feasible"] and a["vessel_id"] == v["id"]), None)
            status = f"→ {match['cargo_id']}" if match else "Free"
            rows.append({"Vessel": v["id"], "Class": v["vessel_class"], "Status": status})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=210)
        _panel_close()

    # -- Contracts: book health --
    with col_contracts:
        _panel_open()
        covered    = len(CARGOES) - len(result["unassigned"])
        unassigned = result["unassigned"]
        critical_unassigned = [
            u for u in unassigned
            if next(c["priority"] for c in CARGOES if c["id"] == u["cargo_id"]) >= 8
        ]
        _panel_title(f"Contracts — {covered}/{len(CARGOES)} covered")

        if not unassigned:
            st.markdown(badge_html("All cargoes covered", STATUS_GOOD), unsafe_allow_html=True)
        else:
            for u in unassigned:
                priority = next(c["priority"] for c in CARGOES if c["id"] == u["cargo_id"])
                color = STATUS_CRITICAL if priority >= 8 else STATUS_WARNING
                st.markdown(
                    f"<div style='margin-bottom:6px;font-size:0.85rem;'>"
                    f"{badge_html(u['cargo_id'], color)} unassigned (priority {priority})</div>",
                    unsafe_allow_html=True,
                )
        st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)
        st.caption("Live cargo-by-cargo status on the Fleet Map page.")
        _panel_close()

    # -- Spot market: today's prices + the latest signal --
    with col_spot:
        _panel_open()
        _panel_title("Spot market — today")

        price_badges = "  ".join(
            badge_html(f"{marker} ${spot['price_paths'][marker][0]:.2f}", MARKER_ACCENT[marker])
            for marker in ("JKM", "TTF", "HH")
        )
        st.markdown(price_badges, unsafe_allow_html=True)
        st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

        if spot["decisions"]:
            latest = spot["decisions"][0]
            outcome_color = STATUS_GOOD if latest["outcome"] == "gain" else STATUS_CRITICAL
            expected_label = f"expected +${latest['expected_margin_usd']/1e6:,.1f}M"
            realized_sign  = "+" if latest["realized_margin_usd"] >= 0 else ""
            realized_label = f"realized {realized_sign}${latest['realized_margin_usd']/1e6:,.1f}M"
            st.markdown(
                f"<div style='font-size:0.85rem;color:{TEXT_PRIMARY};'>"
                f"Day {latest['dispatch_day']}: <b>{latest['vessel_id']}</b> dispatched "
                f"{latest['load_terminal_id']} → {latest['discharge_terminal_id']}</div>"
                f"<div style='margin-top:4px;'>{badge_html(expected_label, TEXT_MUTED)} "
                f"{badge_html(realized_label, outcome_color)}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(badge_html("No profitable spot move today", TEXT_MUTED), unsafe_allow_html=True)

        st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)
        st.caption(f"{spot['summary']['wins']} wins / {spot['summary']['losses']} losses this month — full book on Spot Trading.")
        _panel_close()
