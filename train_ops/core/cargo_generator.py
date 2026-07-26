# train_ops/core/cargo_generator.py
# Converts continuous production into discrete cargoes — the single
# integration point with the cargo-scheduling side of the project. Every
# cargo produced here has EXACTLY the shape data/cargoes.py's CARGOES
# already use, so core.optimizer.assign_cargoes() (and everything built on
# top of it — pnl, disruption, spot) can consume it completely unmodified.
#
# Mechanism: a train fills a virtual tank continuously; once the tank
# holds a full cargo-sized volume, a cargo "becomes available" that day —
# same real-world logic as an export terminal's storage draining into
# vessel loadings.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime, timedelta

from data.terminals import TERMINALS

from train_ops.config import CARGO_SIZE_MMBTU, LOADING_LEAD_TIME_DAYS, LAYCAN_WINDOW_DAYS, DEFAULT_CARGO_PRIORITY

DISCHARGE_TERMINAL_IDS = [t["id"] for t in TERMINALS if t["type"] == "discharge"]


def generate_cargoes_for_train(train, days, cargo_size_mmbtu=CARGO_SIZE_MMBTU):
    """
    `days`: one train's output from core.forecast.simulate_train_forecast().
    Emits one cargo each time cumulative production crosses another
    multiple of cargo_size_mmbtu.
    """
    cargoes  = []
    threshold = cargo_size_mmbtu
    cargo_n   = 1

    for d in days:
        if d["cumulative_mmbtu"] < threshold:
            continue

        available_date = datetime.strptime(d["date"], "%Y-%m-%d")
        laycan_start = available_date + timedelta(days=LOADING_LEAD_TIME_DAYS)
        laycan_end   = laycan_start + timedelta(days=LAYCAN_WINDOW_DAYS)
        delivery_start = laycan_end
        delivery_end   = laycan_end + timedelta(days=30)   # wide — actual delivery depends on the destination the scheduler picks

        cargoes.append({
            "id":                     f"{train['id']}-C{cargo_n:02d}",
            "volume_mmbtu":           cargo_size_mmbtu,
            "loading_terminal":       train["terminal_id"],
            "discharge_terminal":     None,                        # DES — destination resolved economically downstream
            "possible_destinations":  DISCHARGE_TERMINAL_IDS,
            "laycan_start":           laycan_start.isoformat(timespec="minutes"),
            "laycan_end":             laycan_end.isoformat(timespec="minutes"),
            "delivery_window_start":  delivery_start.isoformat(timespec="minutes"),
            "delivery_window_end":    delivery_end.isoformat(timespec="minutes"),
            "contract_type":          "DES",
            "priority":               DEFAULT_CARGO_PRIORITY,
            "notes": f"Generated from {train['id']} production — tank full on day {d['day']} ({d['date']})",
        })

        threshold += cargo_size_mmbtu
        cargo_n   += 1

    return cargoes


def generate_fleet_cargoes(trains, fleet_forecast, cargo_size_mmbtu=CARGO_SIZE_MMBTU):
    """One combined cargo stream across every train in `trains` — loops
    over whatever fleet_forecast['by_train'] contains, so this needs no
    changes when a 2nd or 3rd train is added to train_ops/data/trains.py."""
    trains_by_id = {t["id"]: t for t in trains}
    all_cargoes = []
    for train_id, days in fleet_forecast["by_train"].items():
        all_cargoes.extend(generate_cargoes_for_train(trains_by_id[train_id], days, cargo_size_mmbtu))
    return all_cargoes


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from train_ops.data.trains import TRAINS
    from train_ops.core.forecast import run_fleet_forecast

    print("=== train_ops/core/cargo_generator.py ===")

    fleet = run_fleet_forecast(TRAINS, horizon_days=90)
    cargoes = generate_fleet_cargoes(TRAINS, fleet)

    print(f"\n  {len(cargoes)} cargo(es) generated over 90 days\n")
    for c in cargoes[:5]:
        print(f"  [{c['id']:<20}] {c['volume_mmbtu']:>10,.0f} mmBtu  "
              f"{c['loading_terminal']:<12} laycan {c['laycan_start']} -> {c['laycan_end']}")
    if len(cargoes) > 5:
        print(f"  ... ({len(cargoes) - 5} more)")

    print("\n-- Shape check: every field data.cargoes.CARGOES's entries have --")
    required_keys = {"id", "volume_mmbtu", "loading_terminal", "discharge_terminal",
                      "possible_destinations", "laycan_start", "laycan_end",
                      "delivery_window_start", "delivery_window_end",
                      "contract_type", "priority", "notes"}
    for c in cargoes:
        missing = required_keys - c.keys()
        assert not missing, f"{c['id']} missing keys: {missing}"
    print(f"  OK, all {len(cargoes)} cargoes have every required key")

    print("\n-- Feasibility check: these cargoes actually work with the real scheduler --")
    from data.vessels   import VESSELS
    from data.terminals import TERMINALS as MAIN_TERMINALS
    from core.optimizer import assign_cargoes

    result = assign_cargoes(cargoes, VESSELS, MAIN_TERMINALS)
    print(f"  {len(result['assignments'])}/{len(cargoes)} assigned, "
          f"{len(result['unassigned'])} unassigned (expected: more cargoes than the 5-vessel "
          f"base fleet can carry at once, that's fine)")

    print("\nOK")
