from decimal import Decimal
from django.db.models import Avg, Count, Q
from rest_framework.views import APIView
from rest_framework.response import Response
from routing.models import Station
from routing.serializers import RouteRequestSerializer
from routing.exceptions import RouteError
from routing.services.geocoding_service import GeocodingService
from routing.services.routing_service import RoutingService
from routing.services.station_locator import find_candidates
from routing.services.fuel_optimizer import optimize
from routing.services.geo import haversine


class RouteView(APIView):
    def post(self, request):
        serializer = RouteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        stats = Station.objects.aggregate(
            count=Count("id"),
            located=Count("id", filter=Q(latitude__isnull=False)),
            price=Avg("price"),
        )
        if not stats["count"]:
            raise RouteError(
                "missing_fuel_data",
                "Import the supplied fuel-price dataset before calculating routes.",
                503,
            )
        geocoder = GeocodingService()
        start = geocoder.locate(values["start"])
        finish = geocoder.locate(values["finish"])
        if (
            haversine(
                [start["longitude"], start["latitude"]],
                [finish["longitude"], finish["latitude"]],
            )
            < 0.1
        ):
            raise RouteError(
                "same_location", "Start and destination resolve to the same place."
            )
        route = RoutingService().route(start, finish)
        candidates = find_candidates(route) if route.distance_miles > 500 else []
        price = values.get(
            "initial_fuel_price",
            Decimal(str(stats["price"])).quantize(Decimal(".00000001")),
        )
        plan = optimize(route.distance_miles, candidates, price)
        return Response(
            {
                "start": start,
                "finish": finish,
                "distance_miles": route.distance_miles,
                "duration_hours": route.duration_hours,
                "fuel_efficiency_mpg": 10,
                "vehicle_range_miles": 500,
                "initial_fuel_gallons": 50,
                "initial_fuel_price": float(price),
                "initial_price_source": "user"
                if "initial_fuel_price" in values
                else "mean imported US station price",
                "route_geometry": route.geometry,
                "candidate_stations": len(candidates),
                "data_coverage": {
                    "stations": stats["count"],
                    "located": stats["located"],
                },
                "assumptions": [
                    "Start with a full 50-gallon tank. Starting fuel consumed is valued separately from purchases.",
                    "Detours are geometric access estimates, not verified road directions. Range guarantees apply to this model.",
                    "Base driving duration excludes station detours and refueling time.",
                    "Optimal cost among imported, located stations inside the route corridor; prices are the supplied dataset snapshot.",
                ],
                **plan,
            }
        )


class DataStatusView(APIView):
    def get(self, request):
        stats = Station.objects.aggregate(
            stations=Count("id"), located=Count("id", filter=Q(latitude__isnull=False))
        )
        return Response(
            {
                **stats,
                "ready": stats["stations"] > 0,
                "fuel_efficiency_mpg": 10,
                "vehicle_range_miles": 500,
            }
        )
