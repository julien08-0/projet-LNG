# train_ops/data/trains.py
# Individual liquefaction trains — static specs, zero logic (same rule as
# the main project's data/vessels.py: config.py holds generic defaults,
# this file holds per-instance data).
#
# TRAINS is a LIST from day one, even with a single entry: every function
# in train_ops/core/ takes one train dict and is meant to be called in a
# loop over this list — adding a second or third train later is purely a
# data change here, no core logic changes.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from train_ops.config import (
    REFERENCE_TEMP_C, DERATING_PCT_PER_C, MIN_LOAD_FACTOR, MAX_LOAD_FACTOR,
    DEFAULT_BREAKEVEN_USD_MMBTU,
)

TRAINS = [
    {
        "id":                 "TRAIN-QATAR-01",
        "name":               "Ras Laffan Train 1",
        "terminal_id":        "RAS-LAFFAN",   # must match an id in the main project's data/terminals.py
        "capacity_mtpa":      7.8,            # Qatar mega-train class (real-world reference scale)
        "reference_temp_c":   REFERENCE_TEMP_C,
        "derating_pct_per_c": DERATING_PCT_PER_C,
        "min_load_factor":    MIN_LOAD_FACTOR,
        "max_load_factor":    MAX_LOAD_FACTOR,
        "breakeven_usd_mmbtu": DEFAULT_BREAKEVEN_USD_MMBTU,
        "maintenance_windows": [
            {"start_day": 45, "duration_days": 6, "label": "Planned turnaround"},
        ],
    },
]


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== train_ops/data/trains.py ===")
    print(f"\n  {len(TRAINS)} train(s) loaded\n")
    for t in TRAINS:
        print(f"  [{t['id']:<16}] {t['name']:<20} @ {t['terminal_id']:<12} "
              f"{t['capacity_mtpa']} MTPA  breakeven=${t['breakeven_usd_mmbtu']}/mmBtu")
        for m in t["maintenance_windows"]:
            print(f"      maintenance: day {m['start_day']} for {m['duration_days']}d — {m['label']}")

    print("\nOK")
