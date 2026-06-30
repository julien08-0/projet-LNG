# data/cargoes.py
# Cargoes to be scheduled: contractual obligations to deliver LNG
# from a loading terminal to a discharge terminal within set windows.

CARGOES = [
    {
        "id":                     "LNG-C01",
        "volume_mmbtu":           3_200_000,
        "loading_terminal":       "RAS-LAFFAN",
        "discharge_terminal":     "FUTTSU",
        "laycan_start":           "2025-03-01T06:00",
        "laycan_end":             "2025-03-03T06:00",
        "delivery_window_start":  "2025-03-19T00:00",
        "delivery_window_end":    "2025-03-22T00:00",
        "contract_type":          "DES",
        "demurrage_rate_usd_day": 120_000,
        "priority":               10,
        "notes":                  "TOP contract, Tokyo Electric Power",
    },
    {
        "id":                     "LNG-C02",
        "volume_mmbtu":           3_000_000,
        "loading_terminal":       "RAS-LAFFAN",
        "discharge_terminal":     "ZEEBRUGGE",
        "laycan_start":           "2025-03-02T00:00",
        "laycan_end":             "2025-03-04T00:00",
        "delivery_window_start":  "2025-03-24T00:00",
        "delivery_window_end":    "2025-03-27T00:00",
        "contract_type":          "DES",
        "demurrage_rate_usd_day": 110_000,
        "priority":               8,
        "notes":                  "Fluxys contract, TTF-indexed",
    },
    {
        "id":                     "LNG-C03",
        "volume_mmbtu":           2_200_000,
        "loading_terminal":       "SABINE-PASS",
        "discharge_terminal":     "ZEEBRUGGE",
        "laycan_start":           "2025-03-05T00:00",
        "laycan_end":             "2025-03-07T00:00",
        "delivery_window_start":  "2025-03-19T00:00",
        "delivery_window_end":    "2025-03-22T00:00",
        "contract_type":          "FOB",
        "demurrage_rate_usd_day": 95_000,
        "priority":               6,
        "notes":                  "FOB, buyer nominates vessel",
    },
    {
        "id":                     "LNG-C04",
        "volume_mmbtu":           3_500_000,
        "loading_terminal":       "RAS-LAFFAN",
        "discharge_terminal":     "AL-ZOUR",
        "laycan_start":           "2025-03-03T00:00",
        "laycan_end":             "2025-03-04T12:00",
        "delivery_window_start":  "2025-03-04T18:00",
        "delivery_window_end":    "2025-03-06T00:00",
        "contract_type":          "DES",
        "demurrage_rate_usd_day": 130_000,
        "priority":               9,
        "notes":                  "Tight laycan, short haul",
    },
    {
        "id":                     "LNG-C05",
        "volume_mmbtu":           2_800_000,
        "loading_terminal":       "RAS-LAFFAN",
        "discharge_terminal":     "GATE-ROTTERDAM",
        "laycan_start":           "2025-03-06T00:00",
        "laycan_end":             "2025-03-08T00:00",
        "delivery_window_start":  "2025-03-28T00:00",
        "delivery_window_end":    "2025-03-31T00:00",
        "contract_type":          "DES",
        "demurrage_rate_usd_day": 100_000,
        "priority":               5,
        "notes":                  "Spot cargo, flexible delivery window",
    },
    {
        "id":                     "LNG-C06",
        "volume_mmbtu":           2_100_000,
        "loading_terminal":       "SABINE-PASS",
        "discharge_terminal":     "FUTTSU",
        "laycan_start":           "2025-03-04T00:00",
        "laycan_end":             "2025-03-06T00:00",
        "delivery_window_start":  "2025-03-28T00:00",
        "delivery_window_end":    "2025-03-31T00:00",
        "contract_type":          "FOB",
        "demurrage_rate_usd_day": 90_000,
        "priority":               4,
        "notes":                  "Long haul via Panama",
    },
]


if __name__ == "__main__":
    print("=== cargoes.py ===")
    print(f"  {len(CARGOES)} cargoes loaded\n")
    for c in CARGOES:
        print(f"  [{c['id']:<10}] {c['volume_mmbtu']:>10,} mmBtu  "
              f"{c['loading_terminal']:<14} -> {c['discharge_terminal']:<16} "
              f"{c['contract_type']:<4} priority={c['priority']}")
    print("\nOK")
