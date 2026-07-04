# data/waypoints.py
# Strategic maritime chokepoints and their coordinates.
# Used by the dynamic routing engine to build routes between any two terminals.

# Each chokepoint has:
#   id       : unique identifier
#   lat/lon  : coordinates
#   closeable: True if it can be blocked in disruption simulation

CHOKEPOINTS = {
    "HORMUZ": {
        "id": "HORMUZ", "lat": 26.50, "lon": 56.50,
        "name": "Strait of Hormuz",
        "closeable": True,
    },
    "ADEN": {
        "id": "ADEN", "lat": 12.50, "lon": 44.00,
        "name": "Gulf of Aden",
        "closeable": True,
    },
    "BAB_EL_MANDEB": {
        "id": "BAB_EL_MANDEB", "lat": 11.50, "lon": 43.20,
        "name": "Bab-el-Mandeb Strait",
        "closeable": True,
    },
    "SUEZ": {
        "id": "SUEZ", "lat": 30.00, "lon": 32.50,
        "name": "Suez Canal",
        "closeable": True,
        "delay_hours": 16.0,
        "toll_usd": 600_000,
    },
    "MED_ENTRY": {
        "id": "MED_ENTRY", "lat": 31.30, "lon": 32.30,
        "name": "Mediterranean Entry",
        "closeable": False,
    },
    "GIBRALTAR": {
        "id": "GIBRALTAR", "lat": 36.00, "lon": -5.50,
        "name": "Strait of Gibraltar",
        "closeable": True,
    },
    "MALACCA": {
        "id": "MALACCA", "lat": 1.35, "lon": 104.00,
        "name": "Strait of Malacca",
        "closeable": True,
    },
    "PANAMA": {
        "id": "PANAMA", "lat": 9.00, "lon": -79.50,
        "name": "Panama Canal",
        "closeable": True,
        "delay_hours": 24.0,
        "toll_usd": 350_000,
    },
    "FLORIDA": {
        "id": "FLORIDA", "lat": 25.00, "lon": -80.00,
        "name": "Florida Strait",
        "closeable": False,
    },
    "CAPE_GOOD_HOPE": {
        "id": "CAPE_GOOD_HOPE", "lat": -34.50, "lon": 19.00,
        "name": "Cape of Good Hope",
        "closeable": False,
    },
}


if __name__ == "__main__":
    print("=== waypoints.py ===")
    print(f"  {len(CHOKEPOINTS)} chokepoints defined\n")
    for cp in CHOKEPOINTS.values():
        closeable = "closeable" if cp["closeable"] else "fixed"
        print(f"  {cp['id']:<20} {cp['name']:<30} [{closeable}]")
    print("\nOK")
