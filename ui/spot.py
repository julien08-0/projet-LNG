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

from config          import SPOT_HORIZON_DAYS
from data.cargoes    import CARGOES
from data.terminals  import TERMINALS
from core.optimizer  import assign_cargoes
from core.pnl        import enrich_assignments_with_pnl
from core.spot       import simulate_spot_market
from ui.fleet_state  import get_fleet
from ui.theme        import (inject_theme, hero_metric, badge_html, PAGE_BG, CHART_BG, BORDER,
                              TEXT_PRIMARY, TEXT_MUTED, VESSEL_PALETTE, STATUS_GOOD, STATUS_CRITICAL)

MARKER_COLOR = {"JKM": VESSEL_PALETTE[2], "TTF": VESSEL_PALETTE[0], "HH": VESSEL_PALETTE[3]}

N_DAYS = SPOT_HORIZON_DAYS   # same horizon as the Fleet Map's day slider — config.py, not a local guess


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


def _summary_rows(decisions):
    """Compact blotter — the columns that answer 'did this trade work'.
    A voyage that hasn't arrived by the last simulated day (settled=False)
    has no known outcome yet — showing a GAIN/LOSS for it would claim a
    delivery that hasn't happened, same bug as a Fleet Map vessel drawn as
    already discharged while still at sea."""
    # "Margin (realized)" mixes real numbers (settled) with a "—" placeholder
    # (pending) on purpose, pre-formatted to a string rather than left as a
    # numeric NaN — a NumberColumn with a custom format renders a missing
    # numeric value as the literal text "None" in this Streamlit version,
    # which is worse than what it's meant to fix.
    return [{
        "Day":               d["dispatch_day"],
        "Vessel":            d["vessel_id"],
        "Route":             f"{d['load_terminal_id']} → {d['discharge_terminal_id']}",
        "Volume (mmBtu)":    d["volume_mmbtu"],
        "Margin (expected)": d["expected_margin_usd"],
        "Margin (realized)": f"${d['realized_margin_usd']:,.0f}" if d["settled"] else "—",
        "Outcome":           d["outcome"].upper() if d["settled"] else "PENDING",
    } for d in decisions]


def _detail_rows(decisions):
    """Full blotter — prices, markers, arrival day. Behind an expander."""
    return [{
        "Day":                   d["dispatch_day"],
        "Vessel":                d["vessel_id"],
        "Buy":                   f"{d['load_terminal_id']} ({d['buy_marker']})",
        "Sell":                  f"{d['discharge_terminal_id']} ({d['sell_marker']})",
        "Volume (mmBtu)":        d["volume_mmbtu"],
        "Buy price":             d["buy_price_usd_mmbtu"],
        "Sell price (expected)": d["expected_sell_price_usd_mmbtu"],
        "Sell price (realized)": f"${d['realized_sell_price_usd_mmbtu']:.2f}" if d["settled"] else "—",
        "Margin (expected)":     d["expected_margin_usd"],
        "Margin (realized)":     f"${d['realized_margin_usd']:,.0f}" if d["settled"] else "—",
        "Outcome":               d["outcome"].upper() if d["settled"] else "PENDING",
        "Arrival day":           d["arrival_day"],
    } for d in decisions]


def render_spot():
    inject_theme()
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

    # -- Hero: what the book actually made, not what it hoped to make --
    hero_metric(
        "Realized spot margin",
        f"${summary['total_realized_margin_usd']/1e6:,.1f}M",
        sublabel=(f"Expected at dispatch: ${summary['total_expected_margin_usd']/1e6:,.1f}M · "
                  f"Surprise: ${summary['surprise_usd']/1e6:+,.1f}M"),
        accent=STATUS_GOOD if summary["total_realized_margin_usd"] >= 0 else STATUS_CRITICAL,
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("Voyages dispatched", summary["voyage_count"])
    col2.metric("Win / loss", f"{summary['wins']} / {summary['losses']}")
    col3.metric("Still in transit (pending)", summary["pending_count"])

    if summary["pending_count"] > 0:
        st.caption(
            f"{summary['pending_count']} voyage(s) dispatched too close to the end of the "
            f"{N_DAYS}-day window to have arrived yet — expected margin shown, no realized "
            f"outcome until settlement (see the Fleet Map to watch them still in transit)."
        )

    if summary["losses"] > 0:
        st.warning(
            f"{summary['losses']} voyage(s) were dispatched at a positive expected "
            f"margin but settled at a loss once the vessel actually arrived — the "
            f"destination market moved against the position during transit. "
            f"Expected behavior, not a bug: the sell price is unknown at dispatch time."
        )

    st.divider()
    st.subheader("Regional spot prices")
    st.plotly_chart(_price_chart(sim["price_paths"], N_DAYS), use_container_width=True)

    st.divider()
    st.subheader("Trade log")

    if not sim["decisions"]:
        st.info("No vessel was both free and profitable enough to dispatch on the spot market this month.")
        return

    summary_df = pd.DataFrame(_summary_rows(sim["decisions"]))
    st.dataframe(
        summary_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Margin (expected)":  st.column_config.NumberColumn(format="$%,.0f"),
            # Margin (realized) is pre-formatted (settled rows) or "—"
            # (pending) in _summary_rows — plain text, no NumberColumn here.
            "Volume (mmBtu)":     st.column_config.NumberColumn(format="%,.0f"),
        },
    )

    with st.expander("Full trade detail (prices, markers, arrival day)"):
        detail_df = pd.DataFrame(_detail_rows(sim["decisions"]))
        st.dataframe(
            detail_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Buy price":             st.column_config.NumberColumn(format="$%.2f"),
                "Sell price (expected)": st.column_config.NumberColumn(format="$%.2f"),
                # Sell price (realized) / Margin (realized): pre-formatted
                # string ("—" when pending) in _detail_rows, not a NumberColumn.
                "Margin (expected)":     st.column_config.NumberColumn(format="$%,.0f"),
                "Volume (mmBtu)":        st.column_config.NumberColumn(format="%,.0f"),
            },
        )


if __name__ == "__main__":
    render_spot()
