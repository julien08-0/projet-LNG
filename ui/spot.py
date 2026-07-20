# ui/spot.py
# Spot Trading page: regional price paths + the day-by-day dispatch log,
# expected margin (decision time) vs realized margin (settlement time).
# No business logic here — everything comes from core/spot.py.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from data.cargoes    import CARGOES
from data.terminals  import TERMINALS
from core.optimizer  import assign_cargoes
from core.pnl        import enrich_assignments_with_pnl
from core.spot       import simulate_spot_market
from ui.fleet_state  import get_fleet
from ui.theme        import (inject_dark_theme, PAGE_BG, CHART_BG, BORDER,
                              TEXT_MUTED, VESSEL_PALETTE)

MARKER_COLOR = {"JKM": VESSEL_PALETTE[2], "TTF": VESSEL_PALETTE[0], "HH": VESSEL_PALETTE[3]}

N_DAYS = 46   # same horizon as the Fleet Map's day slider


def _price_chart(price_paths, n_days):
    fig = go.Figure()
    for marker in ("JKM", "TTF", "HH"):
        fig.add_trace(go.Scatter(
            x=list(range(n_days)), y=price_paths[marker][:n_days],
            mode="lines", name=marker,
            line=dict(color=MARKER_COLOR[marker], width=2),
        ))
    fig.update_layout(
        paper_bgcolor=PAGE_BG, plot_bgcolor=CHART_BG,
        font=dict(color=TEXT_MUTED),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(l=10, r=10, t=30, b=10), height=320,
        xaxis=dict(title="Day", gridcolor=BORDER),
        yaxis=dict(title="$ / mmBtu", gridcolor=BORDER),
    )
    return fig


def _decision_rows(decisions):
    return [{
        "Day":                   d["dispatch_day"],
        "Vessel":                d["vessel_id"],
        "Buy":                   f"{d['load_terminal_id']} ({d['buy_marker']})",
        "Sell":                  f"{d['discharge_terminal_id']} ({d['sell_marker']})",
        "Volume (mmBtu)":        d["volume_mmbtu"],
        "Buy price":             d["buy_price_usd_mmbtu"],
        "Sell price (expected)": d["expected_sell_price_usd_mmbtu"],
        "Sell price (realized)": d["realized_sell_price_usd_mmbtu"],
        "Margin (expected)":     d["expected_margin_usd"],
        "Margin (realized)":     d["realized_margin_usd"],
        "Outcome":               d["outcome"].upper(),
        "Arrival day":           d["arrival_day"],
    } for d in decisions]


def render_spot():
    inject_dark_theme()
    st.title("Spot Trading")
    st.caption(
        "Opportunistic buy/sell for vessels not committed to a fixed contract. "
        "A dispatch decision can only use the price known on the day it's made — "
        "the sell price is a forecast until the vessel actually arrives, weeks "
        "later, and the market may have moved by then."
    )

    VESSELS = get_fleet()

    result   = assign_cargoes(CARGOES, VESSELS, TERMINALS)
    enriched = enrich_assignments_with_pnl(result["assignments"], CARGOES, VESSELS, TERMINALS)
    sim      = simulate_spot_market(VESSELS, TERMINALS, CARGOES, enriched, n_days=N_DAYS)
    summary  = sim["summary"]

    st.subheader("Regional spot prices")
    st.plotly_chart(_price_chart(sim["price_paths"], N_DAYS), use_container_width=True)

    st.divider()
    st.subheader("Spot book")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Voyages dispatched", summary["voyage_count"])
    col2.metric("Win / loss", f"{summary['wins']} / {summary['losses']}")
    col3.metric("Expected margin (at dispatch)",
                f"${summary['total_expected_margin_usd']/1e6:,.1f}M")
    col4.metric(
        "Realized margin (at settlement)",
        f"${summary['total_realized_margin_usd']/1e6:,.1f}M",
        delta=f"${summary['surprise_usd']/1e6:+,.1f}M vs expected",
        delta_color="normal" if summary["surprise_usd"] >= 0 else "inverse",
    )

    if summary["losses"] > 0:
        st.warning(
            f"{summary['losses']} voyage(s) were dispatched at a positive expected "
            f"margin but settled at a loss once the vessel actually arrived — the "
            f"destination market moved against the position during transit. "
            f"Expected behavior, not a bug: the sell price is unknown at dispatch time."
        )

    if not sim["decisions"]:
        st.info("No vessel was both free and profitable enough to dispatch on the spot market this month.")
        return

    df = pd.DataFrame(_decision_rows(sim["decisions"]))
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Buy price":             st.column_config.NumberColumn(format="$%.2f"),
            "Sell price (expected)": st.column_config.NumberColumn(format="$%.2f"),
            "Sell price (realized)": st.column_config.NumberColumn(format="$%.2f"),
            "Margin (expected)":     st.column_config.NumberColumn(format="$%,.0f"),
            "Margin (realized)":     st.column_config.NumberColumn(format="$%,.0f"),
            "Volume (mmBtu)":        st.column_config.NumberColumn(format="%,.0f"),
        },
    )


if __name__ == "__main__":
    render_spot()
