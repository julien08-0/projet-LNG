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
from ui.gantt      import render_gantt
from ui.map        import render_map
from ui.alerts     import render_alerts
from ui.kpi        import render_kpi
from ui.pnl        import render_pnl
from ui.disruption import render_disruption
from ui.fleet      import render_fleet

page = st.sidebar.selectbox("Navigation", [
    "Overview",
    "Gantt Schedule",
    "Fleet Map",
    "Alerts",
    "KPI Dashboard",
    "P&L",
    "Disruption Simulator",
    "Fleet Management",
])

if page == "Overview":
    render_overview()
elif page == "Gantt Schedule":
    render_gantt()
elif page == "Fleet Map":
    render_map()
elif page == "Alerts":
    render_alerts()
elif page == "KPI Dashboard":
    render_kpi()
elif page == "P&L":
    render_pnl()
elif page == "Disruption Simulator":
    render_disruption()
elif page == "Fleet Management":
    render_fleet()