import json
from pathlib import Path
import requests
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


class Command(BaseCommand):
    help = "One-time bulk download of major US truckstop-chain POIs. Never called by the route API."

    def add_arguments(self, p):
        p.add_argument("--output", default="data/osm_stations.json")
        p.add_argument("--url", default="https://overpass-api.de/api/interpreter")

    def handle(self, *args, **o):
        # Exact indexed brand IDs avoid scanning every US amenity/name.
        brands = [
            "Q1872496",
            "Q64128179",
            "Q64130592",
            "Q64051305",
            "Q7835892",
            "Q64149010",
            "Q2940968",
            "Q7575683",
        ]
        query = (
            "[out:json][timeout:90];("
            + "".join(
                f'nwr["brand:wikidata"="{brand}"][amenity=fuel](24,-125,50,-66);'
                for brand in brands
            )
            + ");out center tags;"
        )
        try:
            r = requests.get(
                o["url"],
                params={"data": query},
                headers={"User-Agent": settings.GEOCODER_USER_AGENT},
                timeout=120,
            )
            r.raise_for_status()
            data = r.json()
            if "remark" in data or "elements" not in data:
                raise ValueError(data.get("remark", "Invalid OSM response"))
        except (requests.RequestException, ValueError) as exc:
            raise CommandError(f"OSM download failed: {exc}") from exc
        path = Path(o["output"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        self.stdout.write(
            self.style.SUCCESS(
                f"Saved {len(data['elements'])} OSM fuel POIs to {path}. Run enrich_from_osm next. Attribution: © OpenStreetMap contributors, ODbL."
            )
        )
