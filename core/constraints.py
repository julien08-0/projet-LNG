# core/constraints.py
# Constraint checks: draft, laycan, slot overlap.
# All parameters come from config.py.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import MAX_DRAFT_M


# ---------------------------------------------------------------------------
# Draft compatibility
# ---------------------------------------------------------------------------

def check_draft_compatibility(vessel_class, terminal_max_draft_m):
    """
    Check whether a vessel class can physically berth at a terminal.

    Returns a dict with:
      compatible      : True if vessel draft <= terminal max draft
      vessel_draft_m   : draft of the vessel class
      shortfall_m      : how much over the limit (0 if compatible)
    """
    vessel_draft = MAX_DRAFT_M[vessel_class]
    compatible = vessel_draft <= terminal_max_draft_m
    shortfall = max(0.0, vessel_draft - terminal_max_draft_m)

    return {
        "compatible":            compatible,
        "vessel_class":          vessel_class,
        "vessel_draft_m":        vessel_draft,
        "terminal_max_draft_m":  terminal_max_draft_m,
        "shortfall_m":           round(shortfall, 2),
    }


# ---------------------------------------------------------------------------
# Laycan compliance
# ---------------------------------------------------------------------------

def check_laycan_compliance(eta_iso, laycan_start_iso, laycan_end_iso):
    """
    Check whether a vessel ETA falls within the contractual laycan window.

    Returns a dict with:
      status         : "ON_TIME" | "EARLY" | "LATE"
      waiting_hours  : hours waiting at anchor (0 if not early)
      delay_hours    : hours late (0 if not late)
    """
    from datetime import datetime

    eta = datetime.fromisoformat(eta_iso)
    lc_start = datetime.fromisoformat(laycan_start_iso)
    lc_end = datetime.fromisoformat(laycan_end_iso)

    if eta < lc_start:
        status = "EARLY"
        waiting_hours = (lc_start - eta).total_seconds() / 3600.0
        delay_hours = 0.0
    elif eta > lc_end:
        status = "LATE"
        waiting_hours = 0.0
        delay_hours = (eta - lc_end).total_seconds() / 3600.0
    else:
        status = "ON_TIME"
        waiting_hours = 0.0
        delay_hours = 0.0

    return {
        "status":          status,
        "waiting_hours":   round(waiting_hours, 2),
        "delay_hours":     round(delay_hours, 2),
        "demurrage_risk":  status == "LATE",
    }


# ---------------------------------------------------------------------------
# Slot overlap
# ---------------------------------------------------------------------------

def check_slot_overlap(slot_a, slot_b):
    """
    Check whether two terminal slots overlap.

    A slot is a dict with: terminal_id, start_iso, end_iso

    Two slots overlap if they are at the same terminal AND
    neither one ends before the other starts.

    Returns a dict with:
      overlaps : True if conflict
    """
    from datetime import datetime

    if slot_a["terminal_id"] != slot_b["terminal_id"]:
        return {"overlaps": False}

    start_a = datetime.fromisoformat(slot_a["start_iso"])
    end_a   = datetime.fromisoformat(slot_a["end_iso"])
    start_b = datetime.fromisoformat(slot_b["start_iso"])
    end_b   = datetime.fromisoformat(slot_b["end_iso"])

    overlaps = start_a < end_b and start_b < end_a

    return {"overlaps": overlaps}


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from data.vessels import VESSELS
    from data.terminals import TERMINALS

    print("=== core/constraints.py ===")
    print("\n-- Draft compatibility --\n")

    # Test every vessel against every terminal
    for v in VESSELS:
        for t in TERMINALS:
            result = check_draft_compatibility(v["vessel_class"], t["max_draft_m"])
            status = "OK" if result["compatible"] else "BLOCKED"
            print(f"  {v['id']:<16} ({v['vessel_class']:<7}) -> {t['id']:<16} "
                  f"draft {result['vessel_draft_m']}m / max {t['max_draft_m']}m  [{status}]")

    print("\n-- Laycan compliance --\n")

    on_time = check_laycan_compliance(
        "2025-03-18T14:00", "2025-03-18T00:00", "2025-03-19T00:00")
    early = check_laycan_compliance(
        "2025-03-17T06:00", "2025-03-18T00:00", "2025-03-19T00:00")
    late = check_laycan_compliance(
        "2025-03-19T06:00", "2025-03-18T00:00", "2025-03-19T00:00")

    print(f"  ETA 14:00 in [00:00-19:00] -> {on_time['status']}")
    print(f"  ETA 18h before window      -> {early['status']}  "
          f"waiting={early['waiting_hours']}h")
    print(f"  ETA 6h after window        -> {late['status']}  "
          f"delay={late['delay_hours']}h")

    print("\n-- Slot overlap --\n")

    slot_1 = {"terminal_id": "RAS-LAFFAN", "start_iso": "2025-03-01T06:00", "end_iso": "2025-03-02T06:00"}
    slot_2 = {"terminal_id": "RAS-LAFFAN", "start_iso": "2025-03-01T18:00", "end_iso": "2025-03-02T18:00"}
    slot_3 = {"terminal_id": "RAS-LAFFAN", "start_iso": "2025-03-02T08:00", "end_iso": "2025-03-03T08:00"}
    slot_4 = {"terminal_id": "FUTTSU",     "start_iso": "2025-03-01T06:00", "end_iso": "2025-03-02T06:00"}

    r12 = check_slot_overlap(slot_1, slot_2)
    r13 = check_slot_overlap(slot_1, slot_3)
    r14 = check_slot_overlap(slot_1, slot_4)

    print(f"  Slot1 vs Slot2 (overlapping times, same terminal)     -> overlaps={r12['overlaps']}")
    print(f"  Slot1 vs Slot3 (non-overlapping times, same terminal) -> overlaps={r13['overlaps']}")
    print(f"  Slot1 vs Slot4 (overlapping times, different terminal)-> overlaps={r14['overlaps']}")

    print("\nOK")
