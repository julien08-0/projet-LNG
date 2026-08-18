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

ACCENT = "#3987e5"

VESSEL_PALETTE = [
    "#3987e5", "#d95926", "#199e70", "#c98500",
    "#d55181", "#008300", "#9085e9", "#e66767",
]

STATUS_GOOD     = "#0ca30c"
STATUS_WARNING  = "#fab219"
STATUS_CRITICAL = "#d03b3b"

TERMINAL_LOAD_COLOR      = "#3987e5"
TERMINAL_DISCHARGE_COLOR = "#199e70"

# Map-specific geo colors (ui/map.py choropleth). Derived from the palette
# above so land/ocean/coast stay coherent with the rest of the UI.
MAP_LAND_COLOR    = "#1c1d22"
MAP_OCEAN_COLOR   = "#0a1220"
MAP_COAST_COLOR   = "#2c2f3a"
MAP_COUNTRY_COLOR = SURFACE_ALT


def hero_metric(label, value, sublabel=None, accent=None,
                 label_size="0.8rem", label_weight=400, label_color=None, label_uppercase=True):
    """
    The one number that matters most on a page — call at most once per page,
    near the top. Deliberately bigger and more isolated than st.metric() or
    badge_html(), so it's the first thing read, before any table or chart.

    label_size/label_weight/label_color/label_uppercase let a caller promote
    the small kicker label into a bigger, bolder page subtitle (e.g. the
    Fleet Map's "Total net P&L") — defaults reproduce the original compact
    kicker used everywhere else, so existing callers are unaffected.
    """
    import streamlit as st
    color = accent or TEXT_PRIMARY
    lbl_color = label_color or TEXT_MUTED
    text_transform = "uppercase" if label_uppercase else "none"
    letter_spacing = "0.06em" if label_uppercase else "normal"
    sub_html = (f"<div style='color:{TEXT_MUTED};font-size:0.85rem;margin-top:6px;'>{sublabel}</div>"
                if sublabel else "")
    st.markdown(
        f"<div style='text-align:center;padding:20px 12px 22px;'>"
        f"<div style='color:{lbl_color};font-size:{label_size};font-weight:{label_weight};"
        f"text-transform:{text_transform};letter-spacing:{letter_spacing};margin-bottom:8px;'>{label}</div>"
        f"<div style='color:{color};font-size:2.7rem;font-weight:750;line-height:1.1;'>{value}</div>"
        f"{sub_html}"
        f"</div>",
        unsafe_allow_html=True,
    )


def compact_metric(label, value, accent=None):
    """
    A smaller stat than st.metric()'s default — for a dense row of secondary
    figures (e.g. Volumes & Costs) where st.metric()'s ~2.25rem value wraps
    or overlaps its neighbor at narrow column widths. Text wraps naturally
    (no white-space:nowrap) so a long value never gets clipped or hidden
    behind the next column.
    """
    import streamlit as st
    color = accent or TEXT_PRIMARY
    st.markdown(
        f"<div style='padding:4px 0 10px;'>"
        f"<div style='color:{TEXT_MUTED};font-size:0.72rem;margin-bottom:3px;'>{label}</div>"
        f"<div style='color:{color};font-size:1.15rem;font-weight:700;line-height:1.25;'>{value}</div>"
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
    the app body, the top toolbar, and the sidebar — so there's no light
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
       it doesn't inherit .stApp's color, so on a forced-dark background it
       renders as near-invisible dark grey without these overrides. */
    [data-testid="stMetricValue"] {{ color: {TEXT_PRIMARY} !important; }}
    [data-testid="stMetricLabel"] {{ color: {TEXT_MUTED} !important; }}
    [data-testid="stMetricDelta"] {{ color: inherit !important; }}

    /* Expander header keeps a light chrome by default; match the rest of
       the dark surfaces so it doesn't read as an unstyled foreign widget. */
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
