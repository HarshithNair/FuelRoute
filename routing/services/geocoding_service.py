import hashlib
import time
import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from routing.models import ProviderGate
from routing.exceptions import RouteError


class GeocodingService:
    def search(self, query, limit=5):
        key = (
            "geocode:"
            + hashlib.sha256(
                (settings.GEOCODER_URL + query.casefold() + str(limit)).encode()
            ).hexdigest()
        )
        cached = cache.get(key)
        if cached is not None:
            return cached
        # Reserve slots atomically across processes (SQLite write lock), then sleep
        # outside the transaction. Public Nominatim allows at most 1 request/sec.
        ProviderGate.objects.get_or_create(key="geocoder")
        with transaction.atomic():
            # Acquire the SQLite write lock BEFORE reading the current slot.
            ProviderGate.objects.filter(pk="geocoder").update(
                next_allowed=F("next_allowed")
            )
            gate = ProviderGate.objects.get(pk="geocoder")
            slot = max(time.time(), gate.next_allowed)
            gate.next_allowed = slot + 1.1
            gate.save(update_fields=["next_allowed"])
        time.sleep(max(0, slot - time.time()))
        try:
            response = requests.get(
                settings.GEOCODER_URL.rstrip("/") + "/search",
                params={
                    "q": query,
                    "format": "jsonv2",
                    "addressdetails": 1,
                    "limit": limit,
                },
                headers={"User-Agent": settings.GEOCODER_USER_AGENT},
                timeout=settings.HTTP_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list):
                raise ValueError("Invalid geocoder response")
        except (requests.RequestException, ValueError) as exc:
            raise RouteError(
                "geocoding_unavailable",
                "Location search is temporarily unavailable. Please try again.",
                503,
            ) from exc
        cache.set(key, data, 86400 * 30 if data else 3600)
        return data

    def locate(self, query):
        results = self.search(query)
        if not results:
            raise RouteError("invalid_location", f"No location found for ‘{query}’.")
        result = results[0]
        if result.get("address", {}).get("country_code") != "us":
            raise RouteError(
                "outside_usa", "Both locations must be in the United States."
            )
        try:
            lat, lon = float(result["lat"]), float(result["lon"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError()
        except (KeyError, TypeError, ValueError) as exc:
            raise RouteError(
                "geocoding_unavailable",
                "Location provider returned invalid coordinates.",
                503,
            ) from exc
        return {
            "name": result.get("display_name", query),
            "latitude": lat,
            "longitude": lon,
        }
