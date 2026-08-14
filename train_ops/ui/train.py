# train_ops/ui/train.py
# Train Performance page — the upstream side of the story: how much LNG
# does a train actually make, and what cargoes does that turn into.
#
# Only touches the main project for shared, non-business-logic pieces:
# ui.theme (visual system) and, on demand, core.optimizer.assign_cargoes
# to preview scheduling the generated cargoes — never automatic, never
# mutates anything on the cargo-scheduling side.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from train_ops.data.trains          import TRAINS
from train_ops.config               import LNG_DENSITY_KG_PER_M3, DAYS_PER_YEAR
from train_ops.core.forecast        import run_fleet_forecast, calculate_availability
from train_ops.core.cargo_generator import generate_fleet_cargoes
from config                         import LNG_ENERGY_DENSITY_MMBTU_PER_M3
from ui.theme import (inject_theme, hero_metric, badge_html, PAGE_BG, CHART_BG, BORDER,
                       TEXT_PRIMARY, TEXT_MUTED, VESSEL_PALETTE, STATUS_GOOD, STATUS_WARNING, STATUS_CRITICAL)


def _mmbtu_to_tonnes(mmbtu):
    m3 = mmbtu / LNG_ENERGY_DENSITY_MMBTU_PER_M3
    kg = m3 * LNG_DENSITY_KG_PER_M3
    return kg / 1000.0


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


def _cargo_rows(cargoes):
    return [{
        "Cargo":         c["id"],
        "Volume (mmBtu)": c["volume_mmbtu"],
        "Loading terminal": c["loading_terminal"],
        "Laycan start":  c["laycan_start"][:10],
        "Laycan end":    c["laycan_end"][:10],
    } for c in cargoes]


def render_train():
    inject_theme()
    st.title("Train Performance")
    st.caption(
        "Upstream side of the chain: how much LNG a liquefaction train actually produces "
        "(ambient temperature derating, load-factor decision vs. breakeven, maintenance), "
        "and the cargoes that production turns into — separate from the cargo-scheduling "
        "side of this app, on purpose. See the Fleet Map / Spot Trading pages for that."
    )

    st.sidebar.subheader("Forecast settings")
    horizon_days = st.sidebar.slider("Horizon (days)", 30, 90, 90, step=15)
    use_live_weather = st.sidebar.checkbox("Live weather (Open-Meteo)", value=True)
    use_live_price    = st.sidebar.checkbox("Live TTF price", value=False,
                                             help="No confirmed free TTF source — stays on the "
                                                  "config.py fallback unless a real feed is wired up.")

    fleet = run_fleet_forecast(TRAINS, horizon_days=horizon_days,
                                use_live_weather=use_live_weather, use_live_price=use_live_price)
    cargoes = generate_fleet_cargoes(TRAINS, fleet)

    total_mmbtu = sum(days[-1]["cumulative_mmbtu"] for days in fleet["by_train"].values())
    total_tonnes = _mmbtu_to_tonnes(total_mmbtu)

    hero_metric(
        f"Forecast production ({horizon_days} days)",
        f"{total_mmbtu/1e6:,.1f}M mmBtu",
        sublabel=f"≈ {total_tonnes:,.0f} tonnes LNG · {len(cargoes)} cargo(es) generated",
    )

    avg_availability = sum(calculate_availability(days) for days in fleet["by_train"].values()) / len(TRAINS)
    downtime_days = sum(
        1 for days in fleet["by_train"].values() for d in days if d["produced_mmbtu"] == 0.0
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Trains modeled", len(TRAINS))
    col2.metric("Availability (fleet avg)", f"{avg_availability*100:.1f}%")
    col3.metric("Downtime days (maint. + unplanned)", downtime_days)
    col4.metric("Price anchor (day 0)", f"${fleet['price_usd_mmbtu']}/mmBtu")
    st.caption(
        f"Price source: {fleet['price_source']} — the load-factor decision and planned-maintenance "
        f"timing below use a day-by-day price that mean-reverts around this anchor, not a flat value."
    )

    st.divider()
    st.subheader("Daily production")
    st.plotly_chart(_production_chart(fleet), use_container_width=True)

    for train in TRAINS:
        days = fleet["by_train"][train["id"]]
        live_days = sum(1 for d in days if "live" in d["weather_source"])
        availability = calculate_availability(days)
        st.markdown(
            f"<div style='font-size:0.85rem;color:{TEXT_MUTED};margin-bottom:4px;'>"
            f"{badge_html(train['id'], TEXT_MUTED)} {train['name']} · "
            f"{train['capacity_mtpa']} MTPA nameplate · breakeven ${train['breakeven_usd_mmbtu']}/mmBtu · "
            f"availability {availability*100:.1f}% · "
            f"{live_days}/{len(days)} days on real weather, rest on seasonal average</div>",
            unsafe_allow_html=True,
        )

        unplanned = [d for d in days if "Unplanned" in d["status"] and "started" in d["status"]]
        for d in unplanned:
            repair_detail = d["status"].split("—")[-1].strip()
            st.markdown(
                f"<div style='font-size:0.8rem;color:{STATUS_WARNING};margin:2px 0 2px 8px;'>"
                f"⚠ Unplanned trip — day {d['day']} ({d['date']}), {repair_detail}</div>",
                unsafe_allow_html=True,
            )
        for window in fleet["resolved_maintenance_by_train"][train["id"]]:
            st.markdown(
                f"<div style='font-size:0.8rem;color:{TEXT_MUTED};margin:2px 0 2px 8px;'>"
                f"🔧 Planned — day {window['start_day']}, {window['duration_days']}d, {window['label']} "
                f"(price/output-optimized — lost value ≈ ${window['lost_value_usd']/1e6:,.1f}M)</div>",
                unsafe_allow_html=True,
            )

    st.divider()
    st.subheader("Generated cargoes")
    st.caption("Same shape as data/cargoes.py — compatible with the existing scheduler unmodified.")

    if not cargoes:
        st.info("No full cargo accumulated over this horizon yet.")
    else:
        st.dataframe(pd.DataFrame(_cargo_rows(cargoes)), use_container_width=True, hide_index=True)

        with st.expander("Preview: schedule these cargoes with the existing fleet"):
            st.caption(
                "One-off preview only — never runs automatically, and never changes what "
                "the rest of the app sees. Reuses core.optimizer.assign_cargoes() exactly "
                "as-is, proving these cargoes need no special handling."
            )
            if st.button("Run preview"):
                from data.vessels   import VESSELS
                from data.terminals import TERMINALS as MAIN_TERMINALS
                from core.optimizer import assign_cargoes

                result = assign_cargoes(cargoes, VESSELS, MAIN_TERMINALS)
                covered = len(result["assignments"])
                st.markdown(
                    f"<div style='color:{STATUS_GOOD if covered else STATUS_CRITICAL};font-weight:600;'>"
                    f"{covered}/{len(cargoes)} covered by the base 5-vessel fleet</div>",
                    unsafe_allow_html=True,
                )
                if result["unassigned"]:
                    st.caption(f"{len(result['unassigned'])} left over — expected, a single train "
                               f"outproduces a 5-vessel fleet's simultaneous capacity; this is a "
                               f"fleet-sizing question, not a bug.")


if __name__ == "__main__":
    render_train()
