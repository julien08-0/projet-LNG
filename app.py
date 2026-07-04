# app.py
# Entry point for the Streamlit application.
# Run with: streamlit run app.py

import streamlit as st

st.set_page_config(
    page_title="LNG Ops Tool",
    page_icon="🚢",
    layout="wide",
)

from ui.gantt  import render_gantt
from ui.map    import render_map
from ui.alerts import render_alerts
from ui.kpi    import render_kpi

page = st.sidebar.selectbox("Navigation", [
    "Gantt Schedule",
    "Fleet Map",
    "Alerts",
    "KPI Dashboard",
])

if page == "Gantt Schedule":
    render_gantt()
elif page == "Fleet Map":
    render_map()
elif page == "Alerts":
    render_alerts()
elif page == "KPI Dashboard":
    render_kpi()