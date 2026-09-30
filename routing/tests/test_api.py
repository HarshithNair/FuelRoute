from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from routing.models import Station
from routing.exceptions import RouteError
from routing.services.routing_service import DrivingRoute
from routing.tests.test_optimizer import candidate


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class RouteAPITests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.client = APIClient()
        Station.objects.create(
            source_id="1",
            name="Actual schema station",
            city="New York",
            state="NY",
            price=Decimal("3.5"),
        )
        self.start = {"name": "New York, NY", "latitude": 40.71, "longitude": -74.0}
        self.finish = {
            "name": "Philadelphia, PA",
            "latitude": 39.95,
            "longitude": -75.16,
        }

    def post(self, **kwargs):
        return self.client.post(
            "/api/route/",
            {"start": "New York, NY", "finish": "Philadelphia, PA", **kwargs},
            format="json",
        )

    def test_empty_and_same_inputs(self):
        for data in [
            {"start": ""},
            {"finish": "   "},
            {"finish": "new york, ny"},
            {"initial_fuel_price": "-2"},
        ]:
            self.assertEqual(self.post(**data).status_code, 400)

    def test_missing_data(self):
        Station.objects.all().delete()
        r = self.post()
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.data["error"]["code"], "missing_fuel_data")

    @patch("routing.views.GeocodingService.locate")
    def test_invalid_location(self, locate):
        locate.side_effect = RouteError("invalid_location", "Unknown location")
        r = self.post()
        self.assertEqual(r.status_code, 422)

    @patch("routing.views.GeocodingService.locate")
    def test_outside_usa(self, locate):
        locate.side_effect = RouteError("outside_usa", "US only")
        self.assertEqual(self.post().status_code, 422)

    @patch("routing.views.GeocodingService.locate")
    def test_same_resolved_location(self, locate):
        locate.return_value = self.start
        r = self.post()
        self.assertEqual(r.data["error"]["code"], "same_location")

    @patch("routing.views.RoutingService.route")
    @patch("routing.views.GeocodingService.locate")
    def test_provider_failure(self, locate, route):
        locate.side_effect = [self.start, self.finish]
        route.side_effect = RouteError("routing_unavailable", "Unavailable", 503)
        self.assertEqual(self.post().status_code, 503)

    @patch("routing.views.RoutingService.route")
    @patch("routing.views.GeocodingService.locate")
    def test_short_route(self, locate, route):
        locate.side_effect = [self.start, self.finish]
        route.return_value = DrivingRoute(100, 2, [[-74, 40.71], [-75.16, 39.95]])
        r = self.post()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["fuel_stops"], [])
        self.assertEqual(r.data["total_fuel_cost"], 35)
        self.assertIn("Server-Timing", r)

    @patch("routing.views.find_candidates")
    @patch("routing.views.RoutingService.route")
    @patch("routing.views.GeocodingService.locate")
    def test_long_route_and_one_routing_call(self, locate, route, candidates):
        locate.side_effect = [self.start, self.finish]
        route.return_value = DrivingRoute(2800, 43, [[-74, 40.71], [-118, 34]])
        candidates.return_value = [candidate(i, 3) for i in range(400, 2800, 400)]
        r = self.post(initial_fuel_price="4")
        self.assertEqual(r.status_code, 200)
        route.assert_called_once()
        self.assertEqual(locate.call_count, 2)
        self.assertTrue(all(l["distance_miles"] <= 500 for l in r.data["legs"]))
        self.assertEqual(r.data["total_fuel_cost"], 890)

    def test_pages_and_status(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/api/docs/").status_code, 200)
        self.assertEqual(self.client.get("/api/status/").data["stations"], 1)

    def test_bad_json(self):
        self.assertEqual(
            self.client.post(
                "/api/route/", "{", content_type="application/json"
            ).status_code,
            400,
        )
