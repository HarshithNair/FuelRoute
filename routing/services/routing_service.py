import hashlib
import math
from dataclasses import dataclass
import requests
from django.conf import settings
from django.core.cache import cache
from routing.exceptions import RouteError
from .geo import haversine


@dataclass
class DrivingRoute:
    distance_miles: float
    duration_hours: float
    geometry: list


class RoutingService:
    def route(self, start, finish):
        points = f"{start['longitude']},{start['latitude']};{finish['longitude']},{finish['latitude']}"
        key = (
            "route:" + hashlib.sha256((settings.OSRM_URL + points).encode()).hexdigest()
        )
        data = cache.get(key)
        if data is None:
            try:
                response = requests.get(
                    f"{settings.OSRM_URL.rstrip('/')}/route/v1/driving/{points}",
                    params={
                        "overview": "full",
                        "geometries": "geojson",
                        "steps": "false",
                        "alternatives": "false",
                    },
                    timeout=settings.HTTP_TIMEOUT,
                )
                response.raise_for_status()
                data = response.json()
                if data.get("code") == "NoRoute":
                    raise RouteError(
                        "no_driving_route", "No driving route connects these locations."
                    )
                if data.get("code") != "Ok":
                    raise ValueError("OSRM error")
                self._parse(data)
            except (
                requests.RequestException,
                ValueError,
                KeyError,
                TypeError,
                IndexError,
            ) as exc:
                raise RouteError(
                    "routing_unavailable",
                    "The routing provider is temporarily unavailable. Please try again.",
                    503,
                ) from exc
            cache.set(key, data, 86400)
        route = self._parse(data)
        if route.distance_miles < 0.1:
            raise RouteError(
                "same_location", "Start and destination resolve to the same place."
            )
        for location, point in [
            (start, route.geometry[0]),
            (finish, route.geometry[-1]),
        ]:
            if haversine([location["longitude"], location["latitude"]], point) > 5:
                raise RouteError(
                    "location_off_road", "A location is too far from a routable road."
                )
        return route

    @staticmethod
    def _parse(data):
        raw = data["routes"][0]
        distance, duration = (
            float(raw["distance"]) / 1609.344,
            float(raw["duration"]) / 3600,
        )
        coords = raw["geometry"]["coordinates"]
        if (
            not math.isfinite(distance + duration)
            or distance <= 0
            or duration < 0
            or len(coords) < 2
        ):
            raise ValueError("Invalid route")
        for point in coords:
            if len(point) != 2 or not (
                -180 <= point[0] <= 180 and -90 <= point[1] <= 90
            ):
                raise ValueError("Invalid geometry")
        return DrivingRoute(distance, duration, coords)
