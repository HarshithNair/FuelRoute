import csv
import re
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from routing.models import Station
from routing.services.geocoding_service import GeocodingService
from routing.exceptions import RouteError


class Command(BaseCommand):
    help = "Offline, cached, rate-limited station POI lookup. Public service restricted to small, one-time batches."

    def add_arguments(self, p):
        p.add_argument("--limit", type=int, default=20)
        p.add_argument("--ids", help="Comma-separated OPIS station IDs")
        p.add_argument("--city")
        p.add_argument("--state")
        p.add_argument("--export", default="data/station_coordinates.csv")

    def handle(self, *args, **o):
        if o["limit"] < 1 or (
            "nominatim.openstreetmap.org" in settings.GEOCODER_URL and o["limit"] > 50
        ):
            raise CommandError(
                "Public Nominatim: small one-time batches only (1–50). Use a self-hosted provider for full-dataset enrichment."
            )
        qs = Station.objects.filter(latitude__isnull=True).order_by("source_id")
        if o["ids"]:
            qs = qs.filter(source_id__in=o["ids"].split(","))
        if o["city"]:
            qs = qs.filter(city__iexact=o["city"])
        if o["state"]:
            qs = qs.filter(state__iexact=o["state"])
        service = GeocodingService()
        success = 0
        for s in qs[: o["limit"]]:
            name = re.sub(r"#\s*[\w-]+", "", s.name).strip()
            for pattern, brand in [
                (r"FLYING J", "Flying J"),
                (r"LOVES", "Love's"),
                (r"PILOT", "Pilot"),
                (r"SAPP BROS", "Sapp Bros"),
                (r"^TA ", "TA"),
                (r"PETRO", "Petro"),
            ]:
                if re.search(pattern, name, re.I):
                    name = brand
                    break
            query = f"{name}, {s.city}, {s.state}, USA"
            try:
                results = service.search(query)
            except RouteError as exc:
                raise CommandError(str(exc.detail)) from exc
            # Only an actual fuel POI is eligible; never accept a city centroid.
            fuel = [
                r
                for r in results
                if r.get("type") == "fuel"
                and r.get("address", {}).get("country_code") == "us"
            ]
            if len(fuel) != 1:
                self.stdout.write(
                    f"Unresolved {s.source_id}: {query} ({len(fuel)} fuel matches)"
                )
                continue
            r = fuel[0]
            # Require name overlap and the requested city in the result to avoid
            # silently accepting a distant namesake or city-boundary ambiguity.
            city = s.city.casefold()
            if city not in r.get("display_name", "").casefold():
                self.stdout.write(
                    f"Review required {s.source_id}: {r.get('display_name')}"
                )
                continue
            s.latitude = float(r["lat"])
            s.longitude = float(r["lon"])
            s.coordinate_source = (
                f"OpenStreetMap {r.get('osm_type')}/{r.get('osm_id')} via Nominatim"
            )
            s.save(update_fields=["latitude", "longitude", "coordinate_source"])
            success += 1
            self.stdout.write(f"Located {s.source_id}: {s.name} ({s.city}, {s.state})")
        path = Path(o["export"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["source_id", "latitude", "longitude", "coordinate_source"])
            for s in Station.objects.filter(latitude__isnull=False).order_by(
                "source_id"
            ):
                writer.writerow(
                    [s.source_id, s.latitude, s.longitude, s.coordinate_source]
                )
        self.stdout.write(
            self.style.SUCCESS(
                f"Located {success} new stations; exported all located stations to {path}"
            )
        )
