# data/routes.py
# Distances and canal info between terminal pairs.
# Distances from historical AIS data (nautical miles).

ROUTES = [
    {
        "origin":              "RAS-LAFFAN",
        "destination":         "FUTTSU",
        "distance_nm":         7_015,
        "weather_delay_hours": 12.0,
        "canal":               None,
        "canal_delay_hours":   0.0,
    },
    {
        "origin":              "RAS-LAFFAN",
        "destination":         "AL-ZOUR",
        "distance_nm":         480,
        "weather_delay_hours": 2.0,
        "canal":               None,
        "canal_delay_hours":   0.0,
    },
    {
        "origin":              "RAS-LAFFAN",
        "destination":         "ZEEBRUGGE",
        "distance_nm":         11_600,
        "weather_delay_hours": 18.0,
        "canal":               "Suez",
        "canal_delay_hours":   16.0,
    },
    {
        "origin":              "RAS-LAFFAN",
        "destination":         "GATE-ROTTERDAM",
        "distance_nm":         11_500,
        "weather_delay_hours": 18.0,
        "canal":               "Suez",
        "canal_delay_hours":   16.0,
    },
    {
        "origin":              "SABINE-PASS",
        "destination":         "ZEEBRUGGE",
        "distance_nm":         5_400,
        "weather_delay_hours": 24.0,
        "canal":               None,
        "canal_delay_hours":   0.0,
    },
    {
        "origin":              "SABINE-PASS",
        "destination":         "GATE-ROTTERDAM",
        "distance_nm":         5_300,
        "weather_delay_hours": 24.0,
        "canal":               None,
        "canal_delay_hours":   0.0,
    },
    {
        "origin":              "SABINE-PASS",
        "destination":         "FUTTSU",
        "distance_nm":         9_000,
        "weather_delay_hours": 18.0,
        "canal":               "Panama",
        "canal_delay_hours":   24.0,
    },
]


if __name__ == "__main__":
    print("=== routes.py ===")
    print(f"  {len(ROUTES)} routes loaded\n")
    for r in ROUTES:
        canal_str = f" via {r['canal']}" if r["canal"] else ""
        print(f"  {r['origin']:<14} -> {r['destination']:<16} "
              f"{r['distance_nm']:>6,} nm{canal_str}")
    print("\nOK")
