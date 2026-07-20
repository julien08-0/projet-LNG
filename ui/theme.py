# ui/theme.py
# Shared dark visual identity — colors and a CSS injection helper.
# Every ui/*.py page uses these instead of page-local hex values.

PAGE_BG      = "#0d0d0d"
CHART_BG     = "#14151a"
SURFACE      = "#1a1b21"
SURFACE_ALT  = "#22242c"
BORDER       = "#2c2c2a"
TEXT_PRIMARY = "#e8e8ec"
TEXT_MUTED   = "#8a8d99"

VESSEL_PALETTE = [
    "#3987e5", "#19e0a0", "#f5b400", "#39e639",
    "#a99bff", "#ff6b6b", "#ff6fb0", "#ff8a3d",
]

STATUS_GOOD     = "#0ca30c"
STATUS_WARNING  = "#fab219"
STATUS_CRITICAL = "#d03b3b"

TERMINAL_LOAD_COLOR      = "#7fd4ff"
TERMINAL_DISCHARGE_COLOR = "#5ce6a6"


def inject_dark_theme():
    """Call once near the top of each render_*() page function.

    Covers the three surfaces Streamlit renders outside our own markup —
    the app body, the top toolbar, and the sidebar — so there's no light
    seam left over from the default theme. Uses Streamlit's stable
    data-testid hooks rather than generated class names.
    """
    import streamlit as st
    st.markdown(f"""
    <style>
    .stApp {{ background-color: {PAGE_BG}; color: {TEXT_PRIMARY}; }}
    header[data-testid="stHeader"] {{ background-color: {PAGE_BG}; }}
    section[data-testid="stSidebar"] {{ background-color: {SURFACE}; }}
    section[data-testid="stSidebar"] * {{ color: {TEXT_PRIMARY}; }}
    </style>
    """, unsafe_allow_html=True)
