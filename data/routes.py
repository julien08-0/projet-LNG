# data/routes.py
# Routes between terminals with real maritime waypoints.
# Waypoints avoid land masses and follow real shipping lanes.
# Distances recalculated from waypoint chains (nautical miles).

ROUTES = [
    {
        "origin":              "RAS-LAFFAN",
        "destination":         "FUTTSU",
        "distance_nm":         6_900,
        "weather_delay_hours": 12.0,
        "canal":               None,
        "canal_delay_hours":   0.0,
        "waypoints": [
            [25.90,  51.55],   # Ras Laffan
            [24.00,  57.00],   # Gulf of Oman exit
            [12.50,  44.00],   # Gulf of Aden
            [ 1.20,  73.00],   # Indian Ocean
            [ 1.35, 104.00],   # Strait of Malacca (north)
            [ 3.00, 108.00],   # South China Sea
            [20.00, 122.00],   # Philippine Sea
            [35.31, 139.84],   # Futtsu
        ],
    },
    {
        "origin":              "RAS-LAFFAN",
        "destination":         "AL-ZOUR",
        "distance_nm":         480,
        "weather_delay_hours": 2.0,
        "canal":               None,
        "canal_delay_hours":   0.0,
        "waypoints": [
            [25.90,  51.55],   # Ras Laffan
            [26.50,  50.50],   # Arabian Gulf north
            [28.75,  48.20],   # Al Zour
        ],
    },
    {
        "origin":              "RAS-LAFFAN",
        "destination":         "ZEEBRUGGE",
        "distance_nm":         11_200,
        "weather_delay_hours": 18.0,
        "canal":               "Suez",
        "canal_delay_hours":   16.0,
        "waypoints": [
            [25.90,  51.55],   # Ras Laffan
            [24.00,  57.00],   # Gulf of Oman exit
            [12.50,  44.00],   # Gulf of Aden
            [11.50,  43.20],   # Bab-el-Mandeb strait
            [20.00,  38.00],   # Red Sea
            [30.00,  32.50],   # Suez Canal
            [31.30,  32.30],   # Mediterranean entry
            [36.00,  15.00],   # Central Mediterranean
            [38.00,   5.00],   # Gibraltar approach
            [36.00,  -5.50],   # Gibraltar strait
            [47.00,  -9.00],   # Bay of Biscay
            [51.33,   3.20],   # Zeebrugge
        ],
    },
    {
        "origin":              "RAS-LAFFAN",
        "destination":         "GATE-ROTTERDAM",
        "distance_nm":         11_100,
        "weather_delay_hours": 18.0,
        "canal":               "Suez",
        "canal_delay_hours":   16.0,
        "waypoints": [
            [25.90,  51.55],   # Ras Laffan
            [24.00,  57.00],   # Gulf of Oman exit
            [12.50,  44.00],   # Gulf of Aden
            [11.50,  43.20],   # Bab-el-Mandeb strait
            [20.00,  38.00],   # Red Sea
            [30.00,  32.50],   # Suez Canal
            [31.30,  32.30],   # Mediterranean entry
            [36.00,  15.00],   # Central Mediterranean
            [38.00,   5.00],   # Gibraltar approach
            [36.00,  -5.50],   # Gibraltar strait
            [47.00,  -9.00],   # Bay of Biscay
            [51.95,   4.05],   # Gate Rotterdam
        ],
    },
    {
        "origin":              "SABINE-PASS",
        "destination":         "ZEEBRUGGE",
        "distance_nm":         5_200,
        "weather_delay_hours": 24.0,
        "canal":               None,
        "canal_delay_hours":   0.0,
        "waypoints": [
            [29.73, -93.87],   # Sabine Pass
            [28.00, -89.00],   # Gulf of Mexico exit
            [25.00, -80.00],   # Florida strait
            [32.00, -64.00],   # Bermuda area
            [42.00, -45.00],   # North Atlantic
            [48.00, -20.00],   # Approaching Europe
            [51.33,   3.20],   # Zeebrugge
        ],
    },
    {
        "origin":              "SABINE-PASS",
        "destination":         "GATE-ROTTERDAM",
        "distance_nm":         5_100,
        "weather_delay_hours": 24.0,
        "canal":               None,
        "canal_delay_hours":   0.0,
        "waypoints": [
            [29.73, -93.87],   # Sabine Pass
            [28.00, -89.00],   # Gulf of Mexico exit
            [25.00, -80.00],   # Florida strait
            [32.00, -64.00],   # Bermuda area
            [42.00, -45.00],   # North Atlantic
            [48.00, -20.00],   # Approaching Europe
            [51.95,   4.05],   # Gate Rotterdam
        ],
    },
    {
        "origin":              "SABINE-PASS",
        "destination":         "FUTTSU",
        "distance_nm":         9_100,
        "weather_delay_hours": 18.0,
        "canal":               "Panama",
        "canal_delay_hours":   24.0,
        "waypoints": [
            [29.73, -93.87],   # Sabine Pass
            [28.00, -89.00],   # Gulf of Mexico
            [23.00, -82.00],   # Cuba strait
            [ 9.00, -79.50],   # Panama Canal
            [ 7.00, -79.50],   # Pacific exit
            [ 5.00, -85.00],   # Pacific approach
            [20.00, -135.00],  # North Pacific
            [35.31, 139.84],   # Futtsu
        ],
    },
]


if __name__ == "__main__":
    print("=== routes.py ===")
    print(f"  {len(ROUTES)} routes loaded\n")
    for r in ROUTES:
        canal_str = f" via {r['canal']}" if r["canal"] else ""
        print(f"  {r['origin']:<14} -> {r['destination']:<16} "
              f"{r['distance_nm']:>6,} nm  {len(r['waypoints'])} waypoints{canal_str}")
    print("\nOK")