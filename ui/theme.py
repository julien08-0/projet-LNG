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


def hero_metric(label, value, sublabel=None, accent=None):
    """
    The one number that matters most on a page — call at most once per page,
    near the top. Deliberately bigger and more isolated than st.metric() or
    badge_html(), so it's the first thing read, before any table or chart.
    """
    import streamlit as st
    color = accent or TEXT_PRIMARY
    sub_html = (f"<div style='color:{TEXT_MUTED};font-size:0.85rem;margin-top:6px;'>{sublabel}</div>"
                if sublabel else "")
    st.markdown(
        f"<div style='text-align:center;padding:20px 12px 22px;'>"
        f"<div style='color:{TEXT_MUTED};font-size:0.8rem;text-transform:uppercase;"
        f"letter-spacing:0.06em;margin-bottom:8px;'>{label}</div>"
        f"<div style='color:{color};font-size:2.7rem;font-weight:750;line-height:1.1;'>{value}</div>"
        f"{sub_html}"
        f"</div>",
        unsafe_allow_html=True,
    )


def badge_html(text, color=None):
    """
    Small pill for tertiary/technical detail (e.g. a BOG rate, a route
    rationale) — the opposite end of the hierarchy from hero_metric(). Never
    the main takeaway of a section; returns a string so it can be embedded
    inside a larger custom HTML block.
    """
    fg = color or TEXT_MUTED
    return (f"<span style='background:{SURFACE_ALT};color:{fg};font-size:0.72rem;"
            f"padding:2px 9px;border-radius:9px;font-weight:600;white-space:nowrap;'>{text}</span>")


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
