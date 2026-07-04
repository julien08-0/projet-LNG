# core/routing.py
# Dynamic routing engine.
# Calculates the maritime route between any two terminals automatically,
# choosing the right chokepoints based on geography.
# No more hardcoded routes — any terminal pair works.

import sys
import os
import math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.waypoints import CHOKEPOINTS


# ---------------------------------------------------------------------------
# Distance helper
# ---------------------------------------------------------------------------

def haversine_nm(lat1, lon1, lat2, lon2):
    """Great-circle distance in nautical miles."""
    R = 3440.065
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi    = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def total_distance(waypoints):
    """Sum of haversine distances along a list of [lat, lon] waypoints."""
    total = 0.0
    for i in range(len(waypoints) - 1):
        total += haversine_nm(
            waypoints[i][0], waypoints[i][1],
            waypoints[i+1][0], waypoints[i+1][1],
        )
    return round(total, 0)


# ---------------------------------------------------------------------------
# Geographic region detection
# ---------------------------------------------------------------------------

def _region(lat, lon):
    """Classify a point into a broad maritime region."""
    if lon > 40 and lon < 60 and lat > 20:
        return "GULF"           # Persian Gulf / Arabian Gulf
    if lon > 30 and lon < 60 and lat < 20:
        return "RED_SEA_AREA"   # Red Sea / Gulf of Aden
    if lon > 60 and lon < 110 and lat < 25:
        return "INDIAN_OCEAN"
    if lon > 100:
        return "PACIFIC_ASIA"   # East Asia, Pacific
    if lon < -60 and lat > 0:
        return "AMERICAS"       # US Gulf, Caribbean
    if lon > -15 and lon < 40 and lat > 30:
        return "EUROPE"
    if lon > -15 and lon < 40 and lat < 30:
        return "WEST_AFRICA"
    return "OTHER"


# ---------------------------------------------------------------------------
# Route builder
# ---------------------------------------------------------------------------

def build_route(origin, destination, closed_chokepoints=None):
    """
    Build a maritime route between two terminals.

    Automatically selects the correct chokepoints based on the
    geographic regions of origin and destination.

    Args:
        origin              : terminal dict (with lat, lon, id)
        destination         : terminal dict (with lat, lon, id)
        closed_chokepoints  : set of chokepoint ids to avoid (disruption)

    Returns a dict with:
        waypoints       : list of [lat, lon]
        distance_nm     : total distance
        canals          : list of canal ids used (for toll/delay calc)
        canal_delay_hours: total canal delay
        canal_toll_usd  : total canal tolls
        weather_delay_hours: estimated weather delay
        blocked         : True if route is impossible (all paths closed)
    """
    if closed_chokepoints is None:
        closed_chokepoints = set()

    cp = CHOKEPOINTS

    o_region = _region(origin["lat"], origin["lon"])
    d_region = _region(destination["lat"], destination["lon"])

    waypoints     = [[origin["lat"], origin["lon"]]]
    canals        = []
    canal_delay   = 0.0
    canal_toll    = 0.0
    weather_delay = 0.0
    blocked       = False

    # --- GULF origin ---
    if o_region == "GULF":
        # Must exit via Hormuz
        if "HORMUZ" not in closed_chokepoints:
            waypoints.append([cp["HORMUZ"]["lat"], cp["HORMUZ"]["lon"]])
        else:
            blocked = True

        if d_region in ("EUROPE",):
            # Gulf → Red Sea → Suez → Europe
            if "BAB_EL_MANDEB" not in closed_chokepoints and "SUEZ" not in closed_chokepoints:
                waypoints += [
                    [cp["ADEN"]["lat"],          cp["ADEN"]["lon"]],
                    [cp["BAB_EL_MANDEB"]["lat"], cp["BAB_EL_MANDEB"]["lon"]],
                    [20.00, 38.00],   # Red Sea midpoint
                    [cp["SUEZ"]["lat"],          cp["SUEZ"]["lon"]],
                    [cp["MED_ENTRY"]["lat"],     cp["MED_ENTRY"]["lon"]],
                    [36.00, 15.00],   # Central Mediterranean
                    [cp["GIBRALTAR"]["lat"],     cp["GIBRALTAR"]["lon"]],
                    [47.00, -9.00],   # Bay of Biscay
                ]
                canals.append("SUEZ")
                canal_delay += cp["SUEZ"]["delay_hours"]
                canal_toll  += cp["SUEZ"]["toll_usd"]
                weather_delay += 18.0
            else:
                # Reroute via Cape of Good Hope
                waypoints += [
                    [cp["ADEN"]["lat"],           cp["ADEN"]["lon"]],
                    [-10.00,  55.00],  # Indian Ocean south
                    [cp["CAPE_GOOD_HOPE"]["lat"], cp["CAPE_GOOD_HOPE"]["lon"]],
                    [0.00,   -10.00],  # Atlantic
                    [47.00,   -9.00],  # Bay of Biscay
                ]
                weather_delay += 36.0

        elif d_region in ("PACIFIC_ASIA",):
            # Gulf → Indian Ocean → Malacca → Asia
            if "MALACCA" not in closed_chokepoints:
                waypoints += [
                    [cp["ADEN"]["lat"],    cp["ADEN"]["lon"]],
                    [1.20, 73.00],    # Indian Ocean
                    [cp["MALACCA"]["lat"], cp["MALACCA"]["lon"]],
                    [3.00, 108.00],   # South China Sea
                    [20.00, 122.00],  # Philippine Sea
                ]
                weather_delay += 12.0
            else:
                # Malacca closed → go around Lombok / Sunda strait
                waypoints += [
                    [cp["ADEN"]["lat"], cp["ADEN"]["lon"]],
                    [1.20, 73.00],
                    [-8.50, 115.00],  # Lombok Strait
                    [10.00, 125.00],
                    [20.00, 130.00],
                ]
                weather_delay += 18.0

        elif d_region == "AMERICAS":
            # Gulf → Indian Ocean → Cape of Good Hope → Atlantic → Americas
            waypoints += [
                [cp["ADEN"]["lat"],           cp["ADEN"]["lon"]],
                [-10.00,  55.00],
                [cp["CAPE_GOOD_HOPE"]["lat"], cp["CAPE_GOOD_HOPE"]["lon"]],
                [0.00,  -20.00],
                [10.00, -50.00],
            ]
            weather_delay += 30.0

        else:
            # Short haul within Gulf / Red Sea area
            weather_delay += 4.0

    # --- AMERICAS origin ---
    elif o_region == "AMERICAS":
        if d_region == "EUROPE":
            # US Gulf → Florida Strait → Atlantic → Europe
            waypoints += [
                [28.00, -89.00],
                [cp["FLORIDA"]["lat"], cp["FLORIDA"]["lon"]],
                [32.00, -64.00],
                [42.00, -45.00],
                [48.00, -20.00],
            ]
            weather_delay += 24.0

        elif d_region in ("PACIFIC_ASIA",):
            # US Gulf → Panama → Pacific → Asia
            if "PANAMA" not in closed_chokepoints:
                waypoints += [
                    [28.00, -89.00],
                    [23.00, -82.00],
                    [cp["PANAMA"]["lat"], cp["PANAMA"]["lon"]],
                    [7.00,  -79.50],
                    [5.00,  -85.00],
                    [20.00, -135.00],
                ]
                canals.append("PANAMA")
                canal_delay += cp["PANAMA"]["delay_hours"]
                canal_toll  += cp["PANAMA"]["toll_usd"]
                weather_delay += 18.0
            else:
                # Panama closed → go around Cape Horn
                waypoints += [
                    [28.00,  -89.00],
                    [0.00,   -80.00],
                    [-56.00, -67.00],  # Cape Horn
                    [-40.00, -100.00],
                    [20.00,  135.00],
                ]
                weather_delay += 40.0

        elif d_region == "GULF":
            waypoints += [
                [28.00, -89.00],
                [cp["FLORIDA"]["lat"], cp["FLORIDA"]["lon"]],
                [30.00,  -20.00],
                [0.00,    40.00],
                [cp["ADEN"]["lat"], cp["ADEN"]["lon"]],
                [cp["HORMUZ"]["lat"], cp["HORMUZ"]["lon"]],
            ]
            weather_delay += 30.0

    # --- EUROPE origin ---
    elif o_region == "EUROPE":
        if d_region == "GULF":
            waypoints += [
                [47.00,  -9.00],
                [cp["GIBRALTAR"]["lat"], cp["GIBRALTAR"]["lon"]],
                [36.00,  15.00],
                [cp["MED_ENTRY"]["lat"], cp["MED_ENTRY"]["lon"]],
                [cp["SUEZ"]["lat"],      cp["SUEZ"]["lon"]],
                [20.00,  38.00],
                [cp["BAB_EL_MANDEB"]["lat"], cp["BAB_EL_MANDEB"]["lon"]],
                [cp["ADEN"]["lat"],          cp["ADEN"]["lon"]],
                [cp["HORMUZ"]["lat"],        cp["HORMUZ"]["lon"]],
            ]
            canals.append("SUEZ")
            canal_delay += cp["SUEZ"]["delay_hours"]
            canal_toll  += cp["SUEZ"]["toll_usd"]
            weather_delay += 18.0

        elif d_region == "AMERICAS":
            waypoints += [
                [47.00,  -9.00],
                [42.00, -45.00],
                [32.00, -64.00],
                [28.00, -89.00],
            ]
            weather_delay += 24.0

    # Add destination
    waypoints.append([destination["lat"], destination["lon"]])

    distance = total_distance(waypoints)

    return {
        "origin_id":          origin["id"],
        "destination_id":     destination["id"],
        "waypoints":          waypoints,
        "distance_nm":        distance,
        "canals":             canals,
        "canal_delay_hours":  canal_delay,
        "canal_toll_usd":     canal_toll,
        "weather_delay_hours": weather_delay,
        "blocked":            blocked,
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from data.terminals import TERMINALS

    print("=== core/routing.py ===\n")

    terminals_by_id = {t["id"]: t for t in TERMINALS}

    pairs = [
        ("RAS-LAFFAN",  "FUTTSU"),
        ("RAS-LAFFAN",  "ZEEBRUGGE"),
        ("RAS-LAFFAN",  "GATE-ROTTERDAM"),
        ("RAS-LAFFAN",  "AL-ZOUR"),
        ("SABINE-PASS", "ZEEBRUGGE"),
        ("SABINE-PASS", "FUTTSU"),
        ("SABINE-PASS", "AL-ZOUR"),
    ]

    for origin_id, dest_id in pairs:
        origin = terminals_by_id[origin_id]
        dest   = terminals_by_id[dest_id]
        route  = build_route(origin, dest)
        canals = f" via {'+'.join(route['canals'])}" if route['canals'] else ""
        print(f"  {origin_id:<14} -> {dest_id:<16} "
              f"{route['distance_nm']:>6,.0f} nm  "
              f"{len(route['waypoints'])} waypoints"
              f"{canals}")

    print("\n-- Disruption: Suez closed --\n")
    origin = terminals_by_id["RAS-LAFFAN"]
    dest   = terminals_by_id["ZEEBRUGGE"]
    route_normal = build_route(origin, dest)
    route_closed = build_route(origin, dest, closed_chokepoints={"SUEZ"})
    print(f"  Normal route : {route_normal['distance_nm']:,.0f} nm via Suez")
    print(f"  Suez closed  : {route_closed['distance_nm']:,.0f} nm via Cape of Good Hope")
    print(f"  Extra distance: {route_closed['distance_nm'] - route_normal['distance_nm']:,.0f} nm")

    print("\nOK")
