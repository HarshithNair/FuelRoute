"""Offline join against OpenStreetMap POIs, not city-center geocoding."""

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from routing.models import Station
from routing.services.geo import haversine

BRANDS = [
    ("flyingj", r"flying\s*j"),
    ("pilot", r"\bpilot\b"),
    ("loves", r"\blove'?s\b"),
    ("sapp", r"sapp\s*bros"),
    ("petro", r"\bpetro\b"),
    ("ta", r"(^ta\b|travelcenters|travel centers|\bta\s+travel)"),
    ("speedway", r"speedway"),
    ("caseys", r"casey'?s"),
    ("maverik", r"maverik"),
    ("kwiktrip", r"kwik\s*trip"),
    ("kwikstar", r"kwik\s*star"),
    ("sheetz", r"sheetz"),
    ("circlek", r"circle\s*k"),
]


def brand(text):
    for key, pattern in BRANDS:
        if re.search(pattern, text, re.I):
            return key
    return None


def normalize_city(text):
    return re.sub(r"[^a-z0-9]", "", text.casefold().replace("saint", "st"))


def numbers(text):
    return {str(int(n)) for n in re.findall(r"\d+", str(text))}


def cluster_one(matches):
    """Multiple OSM representations of the same site are OK, distant sites aren't."""
    if not matches:
        return None
    first = matches[0]
    if any(
        haversine([first["lon"], first["lat"]], [m["lon"], m["lat"]]) > 0.35
        for m in matches
    ):
        return None
    return sorted(
        matches,
        key=lambda m: (m["tags"].get("hgv") != "yes", m["type"] != "way", m["id"]),
    )[0]


class Command(BaseCommand):
    help = "Conservative local match of supplied station IDs to real OSM fuel POIs, by chain/ref or unique city/state/brand."

    def add_arguments(self, p):
        p.add_argument(
            "path",
            help="Overpass JSON, from fetch_osm_stations or a licensed OSM extract",
        )
        p.add_argument("--export", default="data/station_coordinates.csv")

    def handle(self, *args, **o):
        try:
            data = json.loads(Path(o["path"]).read_text())
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if "remark" in data:
            raise CommandError(f"Incomplete OSM response: {data['remark']}")
        by_number = defaultdict(list)
        by_city = defaultdict(list)
        for raw in data.get("elements", []):
            tags = raw.get("tags", {})
            if tags.get("amenity") != "fuel":
                continue
            coords = raw.get("center", raw)
            lat, lon = coords.get("lat"), coords.get("lon")
            if (
                lat is None
                or lon is None
                or not (24 <= lat <= 50 and -125 <= lon <= -66)
            ):
                continue
            b = brand(" ".join(tags.get(k, "") for k in ["brand", "name", "operator"]))
            if not b:
                continue
            item = {**raw, "lat": lat, "lon": lon}
            refs = numbers(tags.get("ref", "")) | numbers(
                " ".join(re.findall(r"#\s*(\d+)", tags.get("name", "")))
            )
            for website in [tags.get("website", ""), tags.get("contact:website", "")]:
                if b == "loves":
                    refs |= set(
                        re.findall(
                            r"loves\.com/(?:locations|en/location-and-fuel-price-search)/?(\d+)",
                            website,
                            re.I,
                        )
                    )
            item["refs"] = refs
            for ref in refs:
                by_number[b, ref].append(item)
            city = normalize_city(tags.get("addr:city", ""))
            state = tags.get("addr:state", "").upper()
            if city and state:
                by_city[b, city, state].append(item)
        stations = list(Station.objects.all())
        source_numbers = defaultdict(list)
        source_cities = defaultdict(list)
        for s in stations:
            b = brand(s.name)
            ref = re.search(r"#\s*(\d+)", s.name)
            if ref:
                source_numbers[b, str(int(ref[1]))].append(s.source_id)
            source_cities[b, normalize_city(s.city), s.state].append(s.source_id)
        located = 0
        methods = defaultdict(int)
        for s in stations:
            if s.latitude is not None:
                continue
            b = brand(s.name)
            ref = re.search(r"#\s*(\d+)", s.name)
            match = None
            method = ""
            if not b:
                continue
            ref = str(int(ref[1])) if ref else None
            if ref and len(source_numbers[b, ref]) == 1:
                pool = [
                    m
                    for m in by_number[b, ref]
                    if not m["tags"].get("addr:state")
                    or m["tags"]["addr:state"].upper() == s.state
                ]
                match = cluster_one(pool)
                method = "chain and station number"
            key = b, normalize_city(s.city), s.state
            if not match and len(source_cities[key]) == 1:
                pool = [
                    m
                    for m in by_city[key]
                    if not ref or not m["refs"] or ref in m["refs"]
                ]
                match = cluster_one(pool)
                method = "unique chain, city and state"
            if not match:
                continue
            s.latitude = match["lat"]
            s.longitude = match["lon"]
            s.coordinate_source = (
                f"OpenStreetMap {match['type']}/{match['id']}; {method}"
            )
            s.save(update_fields=["latitude", "longitude", "coordinate_source"])
            located += 1
            methods[method] += 1
        path = Path(o["export"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["source_id", "latitude", "longitude", "coordinate_source"])
            for s in Station.objects.filter(latitude__isnull=False).order_by(
                "source_id"
            ):
                w.writerow([s.source_id, s.latitude, s.longitude, s.coordinate_source])
        self.stdout.write(
            self.style.SUCCESS(
                f"Matched {located} stations: {dict(methods)}. Total located: {Station.objects.filter(latitude__isnull=False).count()}"
            )
        )
