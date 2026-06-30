# data/vessels.py
# Fleet of LNG vessels with their current position and status.
# Physical characteristics (boil-off, heel, draft) live in config.py,
# keyed by vessel_class — not repeated here.

VESSELS = [
    {
        "id":               "VESSEL-QF-01",
        "vessel_class":     "Q-Flex",
        "capacity_m3":      216_000,
        "current_lat":      25.90,
        "current_lon":      51.55,
        "current_position": "Ras Laffan",
        "available_from":   "2025-03-01T00:00",
        "speed_knots":      17.0,
        "current_heel_m3":  6_480,
        "status":           "available",
    },
    {
        "id":               "VESSEL-QF-02",
        "vessel_class":     "Q-Flex",
        "capacity_m3":      210_000,
        "current_lat":      51.33,
        "current_lon":       3.20,
        "current_position": "Zeebrugge",
        "available_from":   "2025-03-03T12:00",
        "speed_knots":      17.0,
        "current_heel_m3":  6_300,
        "status":           "available",
    },
    {
        "id":               "VESSEL-TFDE-01",
        "vessel_class":     "TFDE",
        "capacity_m3":      160_000,
        "current_lat":      12.50,
        "current_lon":      44.00,
        "current_position": "Gulf of Aden",
        "available_from":   "2025-03-02T06:00",
        "speed_knots":      18.0,
        "current_heel_m3":  6_400,
        "status":           "available",
    },
    {
        "id":               "VESSEL-TFDE-02",
        "vessel_class":     "TFDE",
        "capacity_m3":      155_000,
        "current_lat":      29.73,
        "current_lon":     -93.87,
        "current_position": "Sabine Pass",
        "available_from":   "2025-03-05T00:00",
        "speed_knots":      18.0,
        "current_heel_m3":  7_750,
        "status":           "available",
    },
    {
        "id":               "VESSEL-QM-01",
        "vessel_class":     "Q-Max",
        "capacity_m3":      265_000,
        "current_lat":      25.90,
        "current_lon":      51.55,
        "current_position": "Ras Laffan",
        "available_from":   "2025-03-01T18:00",
        "speed_knots":      16.5,
        "current_heel_m3":  7_950,
        "status":           "available",
    },
]


if __name__ == "__main__":
    print("=== vessels.py ===")
    print(f"  {len(VESSELS)} vessels loaded\n")
    for v in VESSELS:
        print(f"  [{v['id']:<16}] {v['vessel_class']:<8} {v['capacity_m3']:>7,} m³  "
              f"@ {v['current_position']:<14} status={v['status']}")
    print("\nOK")
