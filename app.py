# app.py
# Entry point for the Streamlit application.
# Run with: streamlit run app.py

import streamlit as st

st.set_page_config(
    page_title="LNG Ops Tool",
    page_icon="🚢",
    layout="wide",
)

from ui.overview   import render_overview
from ui.map        import render_map
from ui.kpi        import render_kpi
from ui.pnl        import render_pnl
from ui.disruption import render_disruption
from ui.fleet      import render_fleet
from ui.spot       import render_spot

from train_ops.ui.train import render_train

page = st.sidebar.selectbox("Navigation", [
    "Overview",
    "Fleet Map",
    "KPI Dashboard",
    "P&L",
    "Disruption Simulator",
    "Fleet Management",
    "Spot Trading",
    "Train Performance (upstream)",
])

if page == "Overview":
    render_overview()
elif page == "Fleet Map":
    render_map()
elif page == "KPI Dashboard":
    render_kpi()
elif page == "P&L":
    render_pnl()
elif page == "Disruption Simulator":
    render_disruption()
elif page == "Fleet Management":
    render_fleet()
elif page == "Spot Trading":
    render_spot()
elif page == "Train Performance (upstream)":
    render_train()