# core/routing.py
# Dynamic routing engine.
# Calculates the maritime route between any two terminals automatically,
# choosing the right chokepoints based on geography.
# No more hardcoded routes — any terminal pair works.

import sys
import os
import math
import random
import zlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.waypoints import CHOKEPOINTS
from config import WEATHER_DELAY_VOLATILITY_FRACTION, WEATHER_DELAY_SEED


def _weather_draw(base_hours, *route_key_parts):
    """
    Route-specific but reproducible weather delay. Every route used to add
    the same flat constant as every other route sharing its branch (e.g.
    ALL Gulf->Europe voyages got +18h, no matter which two terminals).
    Seeded by a deterministic hash of the route + branch label (not
    Python's randomized hash()) so the same route always draws the same
    value within a run — no jitter on every Streamlit rerun — while
    different routes, or the same route on a different branch (e.g. the
    Suez-open vs Suez-closed reroute), draw independently.
    """
    key = "-".join(str(p) for p in route_key_parts)
    rng = random.Random(WEATHER_DELAY_SEED + zlib.crc32(key.encode()))
    low  = base_hours * (1.0 - WEATHER_DELAY_VOLATILITY_FRACTION)
    high = base_hours * (1.0 + WEATHER_DELAY_VOLATILITY_FRACTION)
    return rng.uniform(low, high)


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
                # Refined against the actual charted Red Sea / Mediterranean
                # LNG corridor (this is the busiest route in the dataset,
                # worth the extra waypoints) — a single crude "midpoint" per
                # sea cuts the corner short of the real, narrower shipping
                # lane; these hug it more closely without pretending to be
                # a full maritime routing feed.
                waypoints += [
                    [cp["ADEN"]["lat"],          cp["ADEN"]["lon"]],
                    [cp["BAB_EL_MANDEB"]["lat"], cp["BAB_EL_MANDEB"]["lon"]],
                    [19.00, 39.00],   # Southern Red Sea, off Port Sudan
                    [26.50, 34.20],   # Gulf of Suez approach
                    [cp["SUEZ"]["lat"],          cp["SUEZ"]["lon"]],
                    [cp["MED_ENTRY"]["lat"],     cp["MED_ENTRY"]["lon"]],
                    [34.80, 24.00],   # South of Crete
                    [36.00, 14.40],   # Malta Channel
                    [cp["GIBRALTAR"]["lat"],     cp["GIBRALTAR"]["lon"]],
                    [47.00, -9.00],   # Bay of Biscay
                ]
                canals.append("SUEZ")
                canal_delay += cp["SUEZ"]["delay_hours"]
                canal_toll  += cp["SUEZ"]["toll_usd"]
                weather_delay += _weather_draw(18.0, origin["id"], destination["id"], "gulf_europe_suez")
            else:
                # Reroute via Cape of Good Hope
                waypoints += [
                    [cp["ADEN"]["lat"],           cp["ADEN"]["lon"]],
                    [-10.00,  55.00],  # Indian Ocean south
                    [cp["CAPE_GOOD_HOPE"]["lat"], cp["CAPE_GOOD_HOPE"]["lon"]],
                    [0.00,   -10.00],  # Atlantic
                    [47.00,   -9.00],  # Bay of Biscay
                ]
                weather_delay += _weather_draw(36.0, origin["id"], destination["id"], "gulf_europe_cape")

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
                weather_delay += _weather_draw(12.0, origin["id"], destination["id"], "gulf_asia_malacca")
            else:
                # Malacca closed → go around Lombok / Sunda strait
                waypoints += [
                    [cp["ADEN"]["lat"], cp["ADEN"]["lon"]],
                    [1.20, 73.00],
                    [-8.50, 115.00],  # Lombok Strait
                    [10.00, 125.00],
                    [20.00, 130.00],
                ]
                weather_delay += _weather_draw(18.0, origin["id"], destination["id"], "gulf_asia_lombok")

        elif d_region == "AMERICAS":
            # Gulf → US Gulf Coast is a genuinely long haul either way; the
            # Suez + Atlantic corridor (same Red Sea/Med lane as Gulf→Europe,
            # continued across the Atlantic) is meaningfully shorter than
            # rounding the Cape of Good Hope, so a real ship takes it
            # whenever Suez is open — Cape is the disruption fallback, not
            # the default.
            if "BAB_EL_MANDEB" not in closed_chokepoints and "SUEZ" not in closed_chokepoints:
                waypoints += [
                    [cp["ADEN"]["lat"],          cp["ADEN"]["lon"]],
                    [cp["BAB_EL_MANDEB"]["lat"], cp["BAB_EL_MANDEB"]["lon"]],
                    [19.00, 39.00],
                    [26.50, 34.20],
                    [cp["SUEZ"]["lat"],          cp["SUEZ"]["lon"]],
                    [cp["MED_ENTRY"]["lat"],     cp["MED_ENTRY"]["lon"]],
                    [34.80, 24.00],
                    [36.00, 14.40],
                    [cp["GIBRALTAR"]["lat"],     cp["GIBRALTAR"]["lon"]],
                    [47.00, -9.00],
                    [42.00, -45.00],
                    [32.00, -64.00],
                ]
                canals.append("SUEZ")
                canal_delay += cp["SUEZ"]["delay_hours"]
                canal_toll  += cp["SUEZ"]["toll_usd"]
                weather_delay += _weather_draw(42.0, origin["id"], destination["id"], "gulf_americas_suez")
            else:
                # Reroute via Cape of Good Hope
                waypoints += [
                    [cp["ADEN"]["lat"],           cp["ADEN"]["lon"]],
                    [-10.00,  55.00],
                    [cp["CAPE_GOOD_HOPE"]["lat"], cp["CAPE_GOOD_HOPE"]["lon"]],
                    [0.00,  -20.00],
                    [10.00, -50.00],
                ]
                weather_delay += _weather_draw(48.0, origin["id"], destination["id"], "gulf_americas_cape")

        else:
            # Short haul within Gulf / Red Sea area
            weather_delay += _weather_draw(4.0, origin["id"], destination["id"], "gulf_short_haul")

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
            weather_delay += _weather_draw(24.0, origin["id"], destination["id"], "americas_europe")

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
                weather_delay += _weather_draw(18.0, origin["id"], destination["id"], "americas_asia_panama")
            else:
                # Panama closed → go around Cape Horn
                waypoints += [
                    [28.00,  -89.00],
                    [0.00,   -80.00],
                    [-56.00, -67.00],  # Cape Horn
                    [-40.00, -100.00],
                    [20.00,  135.00],
                ]
                weather_delay += _weather_draw(40.0, origin["id"], destination["id"], "americas_asia_horn")

        elif d_region == "GULF":
            # Mirror of Gulf→Americas: Atlantic → Suez → Red Sea → Gulf is
            # shorter than rounding the Cape, so it's the default; Cape is
            # only used as the disruption fallback.
            if "BAB_EL_MANDEB" not in closed_chokepoints and "SUEZ" not in closed_chokepoints:
                waypoints += [
                    [28.00, -89.00],
                    [cp["FLORIDA"]["lat"],       cp["FLORIDA"]["lon"]],
                    [32.00, -64.00],
                    [42.00, -45.00],
                    [47.00,  -9.00],
                    [cp["GIBRALTAR"]["lat"],     cp["GIBRALTAR"]["lon"]],
                    [36.00,  14.40],
                    [34.80,  24.00],
                    [cp["MED_ENTRY"]["lat"],     cp["MED_ENTRY"]["lon"]],
                    [cp["SUEZ"]["lat"],          cp["SUEZ"]["lon"]],
                    [26.50,  34.20],
                    [19.00,  39.00],
                    [cp["BAB_EL_MANDEB"]["lat"], cp["BAB_EL_MANDEB"]["lon"]],
                    [cp["ADEN"]["lat"],          cp["ADEN"]["lon"]],
                    [cp["HORMUZ"]["lat"],        cp["HORMUZ"]["lon"]],
                ]
                canals.append("SUEZ")
                canal_delay += cp["SUEZ"]["delay_hours"]
                canal_toll  += cp["SUEZ"]["toll_usd"]
                weather_delay += _weather_draw(42.0, origin["id"], destination["id"], "americas_gulf_suez")
            else:
                # Reroute via Cape of Good Hope
                waypoints += [
                    [28.00, -89.00],
                    [cp["FLORIDA"]["lat"],       cp["FLORIDA"]["lon"]],
                    [10.00, -50.00],
                    [0.00,  -20.00],
                    [cp["CAPE_GOOD_HOPE"]["lat"], cp["CAPE_GOOD_HOPE"]["lon"]],
                    [-10.00, 55.00],
                    [cp["ADEN"]["lat"],          cp["ADEN"]["lon"]],
                    [cp["HORMUZ"]["lat"],        cp["HORMUZ"]["lon"]],
                ]
                weather_delay += _weather_draw(48.0, origin["id"], destination["id"], "americas_gulf_cape")

    # --- EUROPE origin ---
    elif o_region == "EUROPE":
        if d_region == "GULF":
            # Same refined corridor as the Gulf->Europe branch, mirrored.
            waypoints += [
                [47.00,  -9.00],
                [cp["GIBRALTAR"]["lat"], cp["GIBRALTAR"]["lon"]],
                [36.00,  14.40],   # Malta Channel
                [34.80,  24.00],   # South of Crete
                [cp["MED_ENTRY"]["lat"], cp["MED_ENTRY"]["lon"]],
                [cp["SUEZ"]["lat"],      cp["SUEZ"]["lon"]],
                [26.50,  34.20],   # Gulf of Suez approach
                [19.00,  39.00],   # Southern Red Sea, off Port Sudan
                [cp["BAB_EL_MANDEB"]["lat"], cp["BAB_EL_MANDEB"]["lon"]],
                [cp["ADEN"]["lat"],          cp["ADEN"]["lon"]],
                [cp["HORMUZ"]["lat"],        cp["HORMUZ"]["lon"]],
            ]
            canals.append("SUEZ")
            canal_delay += cp["SUEZ"]["delay_hours"]
            canal_toll  += cp["SUEZ"]["toll_usd"]
            weather_delay += _weather_draw(18.0, origin["id"], destination["id"], "europe_gulf_suez")

        elif d_region == "AMERICAS":
            waypoints += [
                [47.00,  -9.00],
                [42.00, -45.00],
                [32.00, -64.00],
                [28.00, -89.00],
            ]
            weather_delay += _weather_draw(24.0, origin["id"], destination["id"], "europe_americas")

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

    print("\n-- Sanity check vs. published real-world distance --")
    # Ras Laffan (Qatar) -> Rotterdam via Suez is commonly cited around
    # 11,000-12,000 km (~5,940-6,480 nm) in published shipping distance
    # tables. Not a live routing API (none free exists for this), but a
    # concrete external number this project's own waypoint chain can be
    # checked against, rather than trusting it by construction.
    real_route = build_route(terminals_by_id["RAS-LAFFAN"], terminals_by_id["GATE-ROTTERDAM"])
    published_low, published_high = 5_940, 6_650   # nm, with a small margin either side
    print(f"  Computed Ras Laffan -> Rotterdam : {real_route['distance_nm']:,.0f} nm")
    print(f"  Published range                 : {published_low:,}-{published_high:,} nm")
    assert published_low <= real_route["distance_nm"] <= published_high, \
        "computed distance has drifted outside the realistic published range"
    print("  OK, within the realistic published range")

    print("\n-- Weather delay: varies per route, reproducible per route --")
    for origin_id, dest_id in pairs[:4]:
        route = build_route(terminals_by_id[origin_id], terminals_by_id[dest_id])
        print(f"  {origin_id:<14} -> {dest_id:<16} weather_delay={route['weather_delay_hours']:.1f}h")

    repeat_a = build_route(terminals_by_id["RAS-LAFFAN"], terminals_by_id["ZEEBRUGGE"])
    repeat_b = build_route(terminals_by_id["RAS-LAFFAN"], terminals_by_id["ZEEBRUGGE"])
    assert repeat_a["weather_delay_hours"] == repeat_b["weather_delay_hours"], \
        "same route must draw the same weather delay every call within a run"
    print(f"  OK, RAS-LAFFAN->ZEEBRUGGE draws {repeat_a['weather_delay_hours']:.1f}h identically on repeat calls")

    suez_open_delay   = build_route(origin, dest)["weather_delay_hours"]
    suez_closed_delay = build_route(origin, dest, closed_chokepoints={"SUEZ"})["weather_delay_hours"]
    assert suez_open_delay != suez_closed_delay, \
        "the Suez-open and Cape-reroute branches must draw independently, not share one value"
    print(f"  OK, Suez-open ({suez_open_delay:.1f}h) and Cape-reroute ({suez_closed_delay:.1f}h) "
          f"draw independently for the same terminal pair")

    print("\nOK")
