# ui/fleet_state.py
# Session-scoped fleet extension.
#
# data/vessels.py stays the static base fleet ("data/ = zero logic" rule) —
# vessels added from ui/fleet.py live in st.session_state for the duration
# of the browser session only, never written back to disk. Every other
# ui/*.py page calls get_fleet() instead of importing VESSELS directly, so
# an added vessel shows up everywhere immediately.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from data.vessels import VESSELS
from core.physics import calculate_heel_requirement
from config import MAX_DRAFT_M, DEFAULT_LADEN_SPEED_KNOTS, BALLAST_SPEED_BONUS_KNOTS

VALID_VESSEL_CLASSES = list(MAX_DRAFT_M.keys())


def get_fleet():
    """Base fleet + any vessels added this session."""
    return VESSELS + st.session_state.get("custom_vessels", [])


def add_vessel(vessel_class, capacity_m3, terminal, available_from_iso, laden_speed_knots=DEFAULT_LADEN_SPEED_KNOTS):
    """
    Add a vessel for the rest of this session (appended to
    st.session_state["custom_vessels"]). Starting position is the given
    terminal's coordinates — no raw lat/lon entry, always a valid position.
    Ballast speed is derived (laden + the standard empty-vs-loaded bonus,
    config.BALLAST_SPEED_BONUS_KNOTS) rather than asked for separately —
    the Fleet Management form stays a one-speed control.

    Returns the new vessel dict.
    """
    if "custom_vessels" not in st.session_state:
        st.session_state["custom_vessels"] = []

    n = len(st.session_state["custom_vessels"]) + 1
    vessel_id = f"VESSEL-CUSTOM-{n:02d}"
    required_heel = calculate_heel_requirement(capacity_m3, vessel_class)["required_heel_m3"]

    vessel = {
        "id":               vessel_id,
        "vessel_class":     vessel_class,
        "capacity_m3":      capacity_m3,
        "current_lat":      terminal["lat"],
        "current_lon":      terminal["lon"],
        "current_position": terminal["name"],
        "available_from":   available_from_iso,
        "laden_speed_knots":   laden_speed_knots,
        "ballast_speed_knots": laden_speed_knots + BALLAST_SPEED_BONUS_KNOTS,
        "current_heel_m3":  required_heel,
        "status":           "available",
    }
    st.session_state["custom_vessels"].append(vessel)
    return vessel


def remove_vessel(vessel_id):
    """Remove a custom vessel by id. No-op for base fleet vessels."""
    if "custom_vessels" in st.session_state:
        st.session_state["custom_vessels"] = [
            v for v in st.session_state["custom_vessels"] if v["id"] != vessel_id
        ]


def reset_fleet():
    """Drop every custom vessel, back to the base fleet only."""
    st.session_state["custom_vessels"] = []


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from data.terminals import TERMINALS

    print("=== ui/fleet_state.py ===")

    base_count = len(get_fleet())
    print(f"\n  Base fleet size : {base_count}")

    ras_laffan = next(t for t in TERMINALS if t["id"] == "RAS-LAFFAN")
    new_vessel = add_vessel("Q-Flex", 210_000, ras_laffan, "2025-03-01T00:00")
    print(f"  Added           : {new_vessel['id']} ({new_vessel['vessel_class']}, "
          f"{new_vessel['capacity_m3']:,} m3) @ {new_vessel['current_position']}")
    print(f"  Required heel   : {new_vessel['current_heel_m3']:,.0f} m3")

    fleet = get_fleet()
    print(f"  Fleet size now  : {len(fleet)}  (expected {base_count + 1})")
    assert len(fleet) == base_count + 1

    remove_vessel(new_vessel["id"])
    fleet = get_fleet()
    print(f"  After remove    : {len(fleet)}  (expected {base_count})")
    assert len(fleet) == base_count

    add_vessel("Q-Max", 265_000, ras_laffan, "2025-03-01T00:00")
    add_vessel("TFDE", 160_000, ras_laffan, "2025-03-01T00:00")
    reset_fleet()
    fleet = get_fleet()
    print(f"  After reset     : {len(fleet)}  (expected {base_count})")
    assert len(fleet) == base_count

    print(f"\n  Valid vessel classes: {VALID_VESSEL_CLASSES}")

    print("\nOK")
