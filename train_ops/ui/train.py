# train_ops/ui/train.py
# Train Performance page — demonstrates how a liquefaction train's output
# varies (ambient temperature derating, load-factor vs. breakeven,
# maintenance). Purely illustrative: fully independent from the rest of
# the app — no import of core.optimizer or any cargo-scheduling logic.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import plotly.graph_objects as go

from train_ops.data.trains          import TRAINS
from train_ops.config               import LNG_DENSITY_KG_PER_M3
from train_ops.core.forecast        import run_fleet_forecast, calculate_availability
from config                         import LNG_ENERGY_DENSITY_MMBTU_PER_M3
from ui.theme import (inject_theme, hero_metric, compact_metric, badge_html,
                       PAGE_BG, CHART_BG, BORDER, TEXT_MUTED, VESSEL_PALETTE)


def _mmbtu_to_tonnes(mmbtu):
    m3 = mmbtu / LNG_ENERGY_DENSITY_MMBTU_PER_M3
    kg = m3 * LNG_DENSITY_KG_PER_M3
    return kg / 1000.0


def _temperature_chart(fleet_forecast):
    """Ambient temperature per day — the direct input to the derating
    factor in core/performance.py. Same shape/style as _production_chart."""
    fig = go.Figure()
    for i, (train_id, days) in enumerate(fleet_forecast["by_train"].items()):
        color = VESSEL_PALETTE[i % len(VESSEL_PALETTE)]
        fig.add_trace(go.Scatter(
            x=[d["day"] for d in days], y=[d["ambient_temp_c"] for d in days],
            mode="lines", name=train_id,
            line=dict(color=color, width=2),
        ))
    fig.update_layout(
        paper_bgcolor=PAGE_BG, plot_bgcolor=CHART_BG,
        font=dict(color=TEXT_MUTED),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(l=10, r=10, t=30, b=10), height=260,
        xaxis=dict(title="Day", gridcolor=BORDER),
        yaxis=dict(title="Ambient temperature (°C)", gridcolor=BORDER),
    )
    return fig


def _production_chart(fleet_forecast):
    fig = go.Figure()
    for i, (train_id, days) in enumerate(fleet_forecast["by_train"].items()):
        color = VESSEL_PALETTE[i % len(VESSEL_PALETTE)]
        fig.add_trace(go.Scatter(
            x=[d["day"] for d in days], y=[d["produced_mmbtu"] for d in days],
            mode="lines", name=train_id,
            line=dict(color=color, width=2),
        ))
    fig.update_layout(
        paper_bgcolor=PAGE_BG, plot_bgcolor=CHART_BG,
        font=dict(color=TEXT_MUTED),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(l=10, r=10, t=30, b=10), height=320,
        xaxis=dict(title="Day", gridcolor=BORDER),
        yaxis=dict(title="mmBtu / day", gridcolor=BORDER),
    )
    return fig


def render_train():
    inject_theme()
    st.title("Train Performance")
    st.caption(
        "Upstream side of the chain: how much LNG a liquefaction train actually produces "
        "(ambient temperature derating, load-factor decision vs. breakeven, maintenance)."
    )
    st.caption(
        "This page is fully independent from the rest of the app — nothing here feeds "
        "into scheduling, P&L, or spot trading."
    )

    st.sidebar.subheader("Forecast settings")
    horizon_days = st.sidebar.slider("Horizon (days)", 30, 90, 90, step=15)
    use_live_weather = st.sidebar.checkbox("Live weather (Open-Meteo)", value=True)

    fleet = run_fleet_forecast(TRAINS, horizon_days=horizon_days, use_live_weather=use_live_weather)

    total_mmbtu = sum(days[-1]["cumulative_mmbtu"] for days in fleet["by_train"].values())
    total_tonnes = _mmbtu_to_tonnes(total_mmbtu)

    hero_metric(
        f"Forecast production ({horizon_days} days)",
        f"{total_mmbtu/1e6:,.1f}M mmBtu",
        sublabel=f"≈ {total_tonnes:,.0f} tonnes LNG",
    )

    avg_availability = sum(calculate_availability(days) for days in fleet["by_train"].values()) / len(TRAINS)
    downtime_days = sum(
        1 for days in fleet["by_train"].values() for d in days if d["produced_mmbtu"] == 0.0
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        compact_metric("Availability (fleet avg)", f"{avg_availability*100:.1f}%")
    with col2:
        compact_metric("Downtime days", str(downtime_days))
    with col3:
        compact_metric("Price anchor (day 0)", f"${fleet['price_usd_mmbtu']}/mmBtu")

    st.divider()
    st.subheader("Ambient temperature")
    st.caption("Drives the derating factor below.")
    st.plotly_chart(_temperature_chart(fleet), use_container_width=True)

    st.divider()
    st.subheader("Daily production")
    st.plotly_chart(_production_chart(fleet), use_container_width=True)

    for train in TRAINS:
        days = fleet["by_train"][train["id"]]
        real_days = sum(
            1 for d in days
            if "fallback" not in d["weather_source"] and "offline" not in d["weather_source"]
        )
        availability = calculate_availability(days)
        st.markdown(
            f"<div style='font-size:0.85rem;color:{TEXT_MUTED};margin-bottom:4px;'>"
            f"{badge_html(train['id'], TEXT_MUTED)} {train['name']} · "
            f"{train['capacity_mtpa']} MTPA nameplate · breakeven ${train['breakeven_usd_mmbtu']}/mmBtu · "
            f"availability {availability*100:.1f}% · "
            f"{real_days}/{len(days)} days on measured temperature (forecast + historical)</div>",
            unsafe_allow_html=True,
        )


if __name__ == "__main__":
    render_train()
