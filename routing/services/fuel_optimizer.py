"""Fuel-constrained minimum-cost path with continuous fuel and binary road legs.

A greedy next-cheaper rule is exact on a fixed line with zero detours, but it
can choose a costly detour. This model jointly selects stops and purchases.
There are O(N²) potential edges (only forward, <=500 miles); sparse constraints
have O(N²) nonzeros. MILP worst-case complexity is exponential, so candidate
and solver limits fail explicitly rather than claiming a heuristic is optimal.
All distances/range guarantees are under the documented access-distance model.
"""

from decimal import Decimal, ROUND_HALF_UP
from math import isfinite
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix
from django.conf import settings
from routing.exceptions import RouteError

MPG = 10.0
RANGE = 500.0
CAPACITY = RANGE / MPG


def money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def optimize(distance, candidates, initial_price):
    if (
        not isfinite(distance)
        or distance <= 0
        or not isfinite(float(initial_price))
        or initial_price <= 0
    ):
        raise ValueError("Distance and initial fuel price must be positive and finite")
    if distance <= RANGE:
        consumed = distance / MPG
        cost = money(Decimal(str(consumed)) * Decimal(str(initial_price)))
        return {
            "fuel_stops": [],
            "legs": [
                {
                    "from": "start",
                    "to": "finish",
                    "distance_miles": distance,
                    "fuel_departure_gallons": 50.0,
                    "fuel_arrival_gallons": 50 - consumed,
                }
            ],
            "total_gallons": consumed,
            "total_distance_miles": distance,
            "detour_miles": 0.0,
            "fuel_purchase_cost": 0.0,
            "initial_fuel_cost": float(cost),
            "initial_fuel_consumed_gallons": consumed,
            "ending_fuel_gallons": 50 - consumed,
            "total_fuel_cost": float(cost),
            "optimizer_status": "optimal",
        }
    candidates = sorted(
        candidates, key=lambda c: (c.progress, str(c.station.source_id))
    )
    if len(candidates) > settings.MAX_CANDIDATES:
        raise RouteError(
            "too_many_candidates",
            f"Found {len(candidates)} nearby stations, above the configured optimization limit ({settings.MAX_CANDIDATES}). Narrow CORRIDOR_MILES or raise MAX_CANDIDATES.",
            503,
        )
    n = len(candidates)
    positions = [0] + [c.progress for c in candidates] + [distance]
    access = [0] + [c.access_miles for c in candidates] + [0]
    prices = [0] + [float(c.station.price) for c in candidates] + [0]
    for c in candidates:
        if not (
            0 < c.progress < distance
            and isfinite(c.access_miles)
            and c.access_miles >= 0
            and isfinite(float(c.station.price))
            and c.station.price > 0
        ):
            raise ValueError("Invalid station candidate")
    edges, incoming, outgoing = [], [[] for _ in positions], [[] for _ in positions]
    reachable = {0}
    for i in range(n + 1):
        for j in range(i + 1, n + 2):
            if positions[j] - positions[i] > RANGE:
                break
            miles = positions[j] - positions[i] + access[i] + access[j]
            if miles <= RANGE:
                idx = len(edges)
                edges.append((i, j, miles))
                outgoing[i].append(idx)
                incoming[j].append(idx)
                if i in reachable:
                    reachable.add(j)
    if n + 1 not in reachable:
        raise RouteError(
            "no_reachable_station",
            "There is a gap longer than 500 miles between usable fuel stops. Add verified station coordinates or choose another route.",
        )
    # x[e] chooses a road leg; f[e] is fuel on departure; q[i] is purchase.
    m = len(edges)
    size = 2 * m + n
    objective = np.zeros(size)
    objective[2 * m :] = prices[1:-1]
    integrality = np.zeros(size)
    integrality[:m] = 1
    upper = np.full(size, CAPACITY)
    upper[:m] = 1
    ri = []
    ci = []
    values = []
    lower = []
    high = []

    def constraint(terms, lo, hi):
        row = len(lower)
        for column, value in terms:
            ri.append(row)
            ci.append(column)
            values.append(value)
        lower.append(lo)
        high.append(hi)

    for node in range(n + 2):
        flow = [(e, 1) for e in outgoing[node]] + [(e, -1) for e in incoming[node]]
        target = 1 if node == 0 else -1 if node == n + 1 else 0
        constraint(flow, target, target)
        if node not in (0, n + 1):
            constraint([(e, 1) for e in incoming[node]], 0, 1)
        fuel = (
            [(m + e, 1) for e in outgoing[node]]
            + [(m + e, -1) for e in incoming[node]]
            + [(e, edges[e][2] / MPG) for e in incoming[node]]
        )
        if 0 < node < n + 1:
            fuel.append((2 * m + node - 1, -1))
        # Full initial tank; empty terminal tank on trips >500 mi.
        target = CAPACITY if node == 0 else 0
        constraint(fuel, target, target)
    for e, (_, _, miles) in enumerate(edges):
        constraint([(m + e, 1), (e, -CAPACITY)], -np.inf, 0)
        constraint([(m + e, 1), (e, -miles / MPG)], 0, np.inf)
    matrix = coo_matrix((values, (ri, ci)), shape=(len(lower), size)).tocsc()
    result = milp(
        objective,
        integrality=integrality,
        bounds=Bounds(np.zeros(size), upper),
        constraints=LinearConstraint(matrix, lower, high),
        options={"time_limit": settings.SOLVER_SECONDS, "mip_rel_gap": 0.0},
    )
    if result.status == 2:
        raise RouteError(
            "no_reachable_station", "No feasible fuel plan exists along this route."
        )
    if not result.success:
        raise RouteError(
            "optimization_timeout",
            "The exact fuel optimizer did not finish within its time limit. Try a shorter route or increase SOLVER_SECONDS.",
            503,
        )
    chosen = {
        i: (j, miles, e) for e, (i, j, miles) in enumerate(edges) if result.x[e] > 0.5
    }
    stops = []
    legs = []
    node = 0
    tank = CAPACITY
    actual_distance = 0.0
    while node != n + 1:
        if node not in chosen:
            raise RouteError("optimization_failed", "Fuel plan validation failed.", 503)
        j, miles, e = chosen[node]
        gallons = max(0.0, float(result.x[2 * m + node - 1])) if node else 0.0
        tank += gallons
        arrival = tank - miles / MPG
        if tank > CAPACITY + 1e-6 or arrival < -1e-6 or miles > RANGE:
            raise RouteError(
                "optimization_failed", "Fuel plan failed the range audit.", 503
            )
        if node:
            candidate = candidates[node - 1]
            station = candidate.station
            # Six-decimal purchase precision, eight-decimal source price retained.
            purchase = Decimal(str(gallons)).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP
            )
            cost = money(purchase * station.price)
            stops.append(
                {
                    "station_id": station.source_id,
                    "name": station.name,
                    "city": station.city,
                    "state": station.state,
                    "latitude": station.latitude,
                    "longitude": station.longitude,
                    "distance_into_route": candidate.progress,
                    "distance_into_journey": actual_distance,
                    "price_per_gallon": float(station.price),
                    "gallons": float(purchase),
                    "cost": float(cost),
                    "detour_miles": 2 * candidate.access_miles,
                    "offset_miles": candidate.offset_miles,
                    "route_point": list(candidate.route_point),
                    "coordinate_source": station.coordinate_source,
                }
            )
        legs.append(
            {
                "from": "start"
                if node == 0
                else candidates[node - 1].station.source_id,
                "to": "finish" if j == n + 1 else candidates[j - 1].station.source_id,
                "distance_miles": miles,
                "fuel_departure_gallons": tank,
                "fuel_arrival_gallons": max(0, arrival),
            }
        )
        actual_distance += miles
        tank = max(0, arrival)
        node = j
    purchase_cost = sum((Decimal(str(s["cost"])) for s in stops), Decimal(0))
    initial_cost = money(Decimal("50") * Decimal(str(initial_price)))
    return {
        "fuel_stops": stops,
        "legs": legs,
        "total_gallons": actual_distance / MPG,
        "total_distance_miles": actual_distance,
        "detour_miles": actual_distance - distance,
        "fuel_purchase_cost": float(purchase_cost),
        "initial_fuel_cost": float(initial_cost),
        "initial_fuel_consumed_gallons": 50.0,
        "ending_fuel_gallons": tank,
        "total_fuel_cost": float(initial_cost + purchase_cost),
        "optimizer_status": "optimal",
    }
