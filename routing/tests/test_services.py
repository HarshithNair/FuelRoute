from decimal import Decimal
from unittest.mock import patch, Mock
import requests
from django.test import TestCase, override_settings
from django.core.cache import cache
from routing.models import Station
from routing.services.routing_service import RoutingService, DrivingRoute
from routing.services.geocoding_service import GeocodingService
from routing.services.station_locator import find_candidates
from routing.exceptions import RouteError


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class ProviderTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("routing.services.routing_service.requests.get")
    def test_one_request_and_cache(self, get):
        get.return_value = Mock(
            **{
                "raise_for_status.return_value": None,
                "json.return_value": {
                    "code": "Ok",
                    "routes": [
                        {
                            "distance": 160934.4,
                            "duration": 7200,
                            "geometry": {"coordinates": [[-74, 40], [-75, 40]]},
                        }
                    ],
                },
            }
        )
        service = RoutingService()
        a = {"latitude": 40, "longitude": -74}
        b = {"latitude": 40, "longitude": -75}
        self.assertEqual(service.route(a, b).distance_miles, 100)
        service.route(a, b)
        get.assert_called_once()
        self.assertEqual(get.call_args.kwargs["params"]["overview"], "full")

    @patch("routing.services.routing_service.requests.get")
    def test_timeout(self, get):
        get.side_effect = requests.Timeout()
        with self.assertRaises(RouteError) as ctx:
            RoutingService().route(
                {"latitude": 40, "longitude": -74}, {"latitude": 41, "longitude": -75}
            )
        self.assertEqual(ctx.exception.status_code, 503)

    @patch("routing.services.routing_service.requests.get")
    def test_invalid_provider_geometry(self, get):
        get.return_value = Mock(
            **{
                "raise_for_status.return_value": None,
                "json.return_value": {
                    "code": "Ok",
                    "routes": [
                        {
                            "distance": 100,
                            "duration": 12,
                            "geometry": {"coordinates": []},
                        }
                    ],
                },
            }
        )
        with self.assertRaises(RouteError):
            RoutingService().route(
                {"latitude": 40, "longitude": -74}, {"latitude": 41, "longitude": -75}
            )

    @patch.object(GeocodingService, "search")
    def test_country_rejection_and_invalid_location(self, search):
        search.return_value = [
            {"lat": "45", "lon": "-75", "address": {"country_code": "ca"}}
        ]
        with self.assertRaises(RouteError) as ctx:
            GeocodingService().locate("Ottawa")
        self.assertEqual(ctx.exception.error_code, "outside_usa")
        search.return_value = []
        with self.assertRaises(RouteError):
            GeocodingService().locate("nonsense")

    @patch("routing.services.geocoding_service.requests.get")
    def test_geocode_cache(self, get):
        get.return_value = Mock(
            **{
                "raise_for_status.return_value": None,
                "json.return_value": [
                    {"lat": "40", "lon": "-74", "address": {"country_code": "us"}}
                ],
            }
        )
        g = GeocodingService()
        g.locate("Test location")
        g.locate("Test location")
        get.assert_called_once()


class ProjectionTests(TestCase):
    def test_projection_uses_segments_not_just_vertices(self):
        Station.objects.create(
            source_id="near",
            name="Near",
            city="Test",
            state="PA",
            price=Decimal("3"),
            latitude=40.001,
            longitude=-75,
        )
        Station.objects.create(
            source_id="far",
            name="Far",
            city="Test",
            state="PA",
            price=Decimal("2"),
            latitude=40.8,
            longitude=-75,
        )
        route = DrivingRoute(200, 3, [[-76, 40], [-74, 40]])
        candidates = find_candidates(route)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].station.source_id, "near")
        self.assertAlmostEqual(candidates[0].progress, 100, places=3)
        self.assertLess(candidates[0].offset_miles, 0.1)
