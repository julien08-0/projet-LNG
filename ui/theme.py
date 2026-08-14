# ui/theme.py
# Shared light visual identity — colors and a CSS injection helper.
# Every ui/*.py page uses these instead of page-local hex values.

PAGE_BG      = "#f9f9f7"
CHART_BG     = "#fcfcfb"
SURFACE      = "#fcfcfb"
SURFACE_ALT  = "#f0efec"
BORDER       = "#e1e0d9"
TEXT_PRIMARY = "#0b0b0b"
TEXT_MUTED   = "#898781"

ACCENT = "#2a78d6"

VESSEL_PALETTE = [
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100",
    "#e87ba4", "#008300", "#4a3aa7", "#e34948",
]

STATUS_GOOD     = "#0ca30c"
STATUS_WARNING  = "#fab219"
STATUS_CRITICAL = "#d03b3b"

TERMINAL_LOAD_COLOR      = "#2a78d6"
TERMINAL_DISCHARGE_COLOR = "#1baf7a"

# Map-specific geo colors (ui/map.py choropleth). Derived from the palette
# above so land/ocean/coast stay coherent with the rest of the UI; ocean is
# the one new tint (a pale wash of ACCENT) since nothing above covers it.
MAP_LAND_COLOR    = SURFACE_ALT
MAP_OCEAN_COLOR   = "#dce8f5"
MAP_COAST_COLOR   = TEXT_MUTED
MAP_COUNTRY_COLOR = BORDER


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


def inject_theme():
    """Call once near the top of each render_*() page function.

    Covers the three surfaces Streamlit renders outside our own markup —
    the app body, the top toolbar, and the sidebar — so there's no dark
    seam left over from the default theme. Uses Streamlit's stable
    data-testid hooks rather than generated class names.
    """
    import streamlit as st
    st.markdown(f"""
    <style>
    .stApp {{
        background-color: {PAGE_BG}; color: {TEXT_PRIMARY};
        font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    }}
    header[data-testid="stHeader"] {{ background-color: {PAGE_BG}; }}
    section[data-testid="stSidebar"] {{ background-color: {SURFACE}; }}
    section[data-testid="stSidebar"] * {{ color: {TEXT_PRIMARY}; }}

    /* st.metric ships its own text color tuned for Streamlit's light theme —
       it doesn't always inherit .stApp's color, so pin it explicitly to keep
       values legible against the light background. */
    [data-testid="stMetricValue"] {{ color: {TEXT_PRIMARY} !important; }}
    [data-testid="stMetricLabel"] {{ color: {TEXT_MUTED} !important; }}
    [data-testid="stMetricDelta"] {{ color: inherit !important; }}

    /* Expander header keeps its own chrome by default; match the rest of
       the light surfaces so it doesn't read as an unstyled foreign widget. */
    [data-testid="stExpander"] summary {{
        background-color: {SURFACE}; color: {TEXT_PRIMARY};
        border: 1px solid {BORDER}; border-radius: 8px;
    }}
    [data-testid="stExpander"] summary:hover {{ color: {TEXT_PRIMARY}; }}
    [data-testid="stExpander"] div[data-testid="stExpanderDetails"] {{
        background-color: {PAGE_BG};
    }}

    /* Primary buttons: solid accent fill, distinct from any informational
       text/labels elsewhere on the page. */
    [data-testid="stButton"] button, [data-testid="stDownloadButton"] button {{
        background-color: {ACCENT}; color: #ffffff; border: 1px solid {ACCENT};
        border-radius: 8px; cursor: pointer; font-weight: 600;
        transition: opacity 0.15s ease;
    }}
    [data-testid="stButton"] button:hover, [data-testid="stDownloadButton"] button:hover {{
        background-color: {ACCENT}; color: #ffffff; opacity: 0.85;
    }}
    [data-testid="stButton"] button:focus, [data-testid="stDownloadButton"] button:focus {{
        color: #ffffff;
    }}
    </style>
    """, unsafe_allow_html=True)
