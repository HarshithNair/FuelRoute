from decimal import Decimal
from types import SimpleNamespace
import random
from django.test import SimpleTestCase, override_settings
from routing.exceptions import RouteError
from routing.services.fuel_optimizer import optimize
from routing.services.station_locator import Candidate


def candidate(mile, price, detour=0, sid=None):
    s = SimpleNamespace(
        source_id=str(sid if sid is not None else mile),
        name=f"Test Station {mile}",
        city="Test City",
        state="PA",
        price=Decimal(str(price)),
        latitude=40.0,
        longitude=-80.0,
        coordinate_source="test fixture",
    )
    return Candidate(s, mile, detour)


class OptimizerTests(SimpleTestCase):
    def audit(self, plan):
        self.assertTrue(all(leg["distance_miles"] <= 500 for leg in plan["legs"]))
        self.assertTrue(
            all(
                -1e-6
                <= leg["fuel_arrival_gallons"]
                <= leg["fuel_departure_gallons"]
                <= 50 + 1e-6
                for leg in plan["legs"]
            )
        )
        self.assertAlmostEqual(
            sum(l["distance_miles"] for l in plan["legs"]) / 10,
            plan["total_gallons"],
            places=6,
        )
        self.assertAlmostEqual(
            50
            + sum(s["gallons"] for s in plan["fuel_stops"])
            - plan["ending_fuel_gallons"],
            plan["total_gallons"],
            places=5,
        )
        self.assertAlmostEqual(
            sum(s["cost"] for s in plan["fuel_stops"]) + plan["initial_fuel_cost"],
            plan["total_fuel_cost"],
            places=2,
        )

    def test_short_route_no_stops_charges_consumed_fuel(self):
        p = optimize(200, [], Decimal("3.5"))
        self.assertEqual(p["fuel_stops"], [])
        self.assertEqual(p["total_fuel_cost"], 70)
        self.assertEqual(p["ending_fuel_gallons"], 30)
        self.audit(p)

    def test_exactly_500_miles(self):
        p = optimize(500, [], Decimal("3"))
        self.assertEqual(p["total_fuel_cost"], 150)
        self.audit(p)

    def test_route_over_500(self):
        p = optimize(600, [candidate(400, 3)], Decimal("3.5"))
        self.assertEqual(p["fuel_stops"][0]["gallons"], 10)
        self.assertEqual(p["total_fuel_cost"], 205)
        self.audit(p)

    def test_cross_country(self):
        p = optimize(
            2800,
            [candidate(i, 3 + i / 10000) for i in range(350, 2800, 350)],
            Decimal("3"),
        )
        self.assertGreaterEqual(len(p["fuel_stops"]), 5)
        self.audit(p)

    def test_cheapest_reachable_skips_expensive_station(self):
        p = optimize(
            900, [candidate(300, 5), candidate(450, 2), candidate(600, 4)], Decimal("3")
        )
        self.assertEqual([s["station_id"] for s in p["fuel_stops"]], ["450"])
        self.assertEqual(p["total_fuel_cost"], 230)
        self.audit(p)

    def test_buy_only_until_next_cheaper_station(self):
        p = optimize(1000, [candidate(400, 4), candidate(600, 2)], Decimal("3"))
        self.assertEqual([s["gallons"] for s in p["fuel_stops"]], [10, 40])
        self.assertEqual(p["total_fuel_cost"], 270)
        self.audit(p)

    def test_detour_can_outweigh_lower_price(self):
        p = optimize(
            600,
            [candidate(400, 3, 0, sid="near"), candidate(410, 2.9, 20, sid="far")],
            Decimal("3"),
        )
        self.assertEqual([s["station_id"] for s in p["fuel_stops"]], ["near"])
        self.audit(p)

    def test_detour_is_included_in_range_and_fuel(self):
        p = optimize(800, [candidate(400, 3, 2)], Decimal("3"))
        self.assertEqual(p["total_distance_miles"], 804)
        self.assertEqual(p["fuel_stops"][0]["gallons"], 30.4)
        self.audit(p)

    def test_detour_makes_station_unreachable(self):
        with self.assertRaises(RouteError) as ctx:
            optimize(600, [candidate(499, 3, 2)], Decimal("3"))
        self.assertEqual(ctx.exception.error_code, "no_reachable_station")

    def test_gap_and_missing_coordinates(self):
        for stations in [
            [],
            [candidate(510, 3)],
            [candidate(400, 3), candidate(950, 2)],
        ]:
            with self.assertRaises(RouteError):
                optimize(1200, stations, Decimal("3"))

    def test_decimal_rounding_cost(self):
        p = optimize(600, [candidate(400, "3.00733333")], Decimal("3.125"))
        self.assertEqual(p["fuel_purchase_cost"], 30.07)
        self.assertEqual(p["total_fuel_cost"], 186.32)
        self.audit(p)

    @override_settings(MAX_CANDIDATES=1)
    def test_explicit_candidate_limit(self):
        with self.assertRaises(RouteError) as ctx:
            optimize(600, [candidate(200, 3), candidate(400, 3)], Decimal("3"))
        self.assertEqual(ctx.exception.error_code, "too_many_candidates")

    def test_matches_independent_discrete_dynamic_program(self):
        # Distances and access are multiples of 10mi, so integer-gallon DP is
        # an exact independent oracle for these small randomized instances.
        rng = random.Random(17)
        for case in range(10):
            stations = [
                candidate(pos, rng.randint(2, 6), rng.choice([0, 10, 20]))
                for pos in [200, 350, 450, 600, 750]
            ]
            positions = [0] + [s.progress for s in stations] + [900]
            access = [0] + [s.access_miles for s in stations] + [0]
            prices = [0] + [float(s.station.price) for s in stations] + [0]
            states = [{} for _ in positions]
            states[0][50] = 0
            for i in range(len(positions) - 1):
                for fuel, cost in states[i].items():
                    for departure in range(fuel, 51) if i else [50]:
                        cost2 = cost + (departure - fuel) * prices[i]
                        for j in range(i + 1, len(positions)):
                            need = int(
                                round(
                                    (
                                        positions[j]
                                        - positions[i]
                                        + access[i]
                                        + access[j]
                                    )
                                    / 10
                                )
                            )
                            if need > departure:
                                continue
                            remaining = departure - need
                            states[j][remaining] = min(
                                states[j].get(remaining, float("inf")), cost2
                            )
            plan = optimize(900, stations, Decimal("3"))
            self.assertAlmostEqual(
                plan["fuel_purchase_cost"], states[-1][0], places=2, msg=f"case {case}"
            )
            self.audit(plan)
