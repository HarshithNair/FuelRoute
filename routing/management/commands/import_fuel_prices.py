import csv
import hashlib
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from routing.models import Station
from routing.services.geo import US_STATES

ALIASES = {
    "source_id": ["opis truckstop id", "station id", "source id"],
    "name": ["truckstop name", "station name", "name"],
    "address": ["address", "street address"],
    "city": ["city"],
    "state": ["state"],
    "price": ["retail price", "price per gallon", "fuel price", "price"],
    "latitude": ["latitude", "lat"],
    "longitude": ["longitude", "lon", "lng"],
}


def normalized(value):
    return re.sub(r"[_\s-]+", " ", str(value or "").strip().lower())


class Command(BaseCommand):
    help = "Inspect and atomically import the supplied OPIS CSV/XLSX; no network calls."

    def add_arguments(self, parser):
        parser.add_argument(
            "path", nargs="?", default=str(settings.BASE_DIR / "data/fuel_prices.csv")
        )
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Remove stations absent from this input after successful validation.",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.is_file():
            raise CommandError(f"Fuel data not found: {path}")
        workbook = None
        if path.suffix.lower() == ".xlsx":
            from openpyxl import load_workbook

            workbook = load_workbook(path, read_only=True, data_only=True)
            rows = workbook.active.iter_rows(values_only=True)
            headers = next(rows, [])
            records = (dict(zip(headers, row)) for row in rows)
        elif path.suffix.lower() == ".csv":
            handle = path.open(encoding="utf-8-sig", newline="")
            reader = csv.DictReader(handle)
            headers = reader.fieldnames or []
            records = reader
        else:
            raise CommandError("Use a .csv or .xlsx file.")
        lookup = {normalized(header): header for header in headers}
        mapping = {
            field: next((lookup[a] for a in aliases if a in lookup), None)
            for field, aliases in ALIASES.items()
        }
        self.stdout.write("Detected columns: " + ", ".join(map(str, headers)))
        missing = [f for f in ["name", "city", "state", "price"] if not mapping[f]]
        if missing:
            raise CommandError("Missing required columns: " + ", ".join(missing))
        groups = {}
        counts = Counter()
        try:
            for line, row in enumerate(records, 2):
                if not any(str(v or "").strip() for v in row.values()):
                    continue
                counts["rows"] += 1

                def value(field):
                    return str(row.get(mapping[field], "") or "").strip()

                state = value("state").upper()
                if state not in US_STATES:
                    counts["non_us_rows"] += 1
                    continue
                try:
                    price = Decimal(value("price").replace("$", "").replace(",", ""))
                    if not price.is_finite() or not 0 < price < 100:
                        raise ValueError("price must be between 0 and 100")
                    name, city, address = value("name"), value("city"), value("address")
                    if not name or not city:
                        raise ValueError("name and city are required")
                    source_id = value("source_id")
                    if source_id.endswith(".0"):
                        source_id = source_id[:-2]
                    if not source_id:
                        source_id = hashlib.sha256(
                            f"{name}|{address}|{city}|{state}".casefold().encode()
                        ).hexdigest()[:24]
                    lat, lon = value("latitude"), value("longitude")
                    if bool(lat) != bool(lon):
                        raise ValueError("coordinates must be a pair")
                    coords = (float(lat), float(lon)) if lat else (None, None)
                    if lat and not (
                        -90 <= coords[0] <= 90 and -180 <= coords[1] <= 180
                    ):
                        raise ValueError("invalid coordinates")
                except (InvalidOperation, ValueError) as exc:
                    raise CommandError(
                        f"Row {line}: {exc}. No changes imported."
                    ) from exc
                if source_id in groups:
                    old = groups[source_id]
                    if (old["city"].casefold(), old["state"]) != (
                        city.casefold(),
                        state,
                    ):
                        raise CommandError(
                            f"Conflicting locations for station {source_id}, row {line}"
                        )
                    old["prices"].append(price)
                    counts["duplicate_rows"] += 1
                else:
                    groups[source_id] = {
                        "source_id": source_id,
                        "name": name,
                        "address": address,
                        "city": city,
                        "state": state,
                        "prices": [price],
                        "latitude": coords[0],
                        "longitude": coords[1],
                    }
        finally:
            if workbook:
                workbook.close()
            else:
                handle.close()
        if not groups:
            raise CommandError("No valid US fuel stations in this file.")
        existing = {s.source_id: s for s in Station.objects.all()}
        objects = []
        for source_id, item in groups.items():
            prices = item.pop("prices")
            item["price"] = (sum(prices) / len(prices)).quantize(Decimal(".00000001"))
            old = existing.get(source_id)
            same_address = old and (
                old.address.casefold(),
                old.city.casefold(),
                old.state,
            ) == (item["address"].casefold(), item["city"].casefold(), item["state"])
            if item["latitude"] is not None:
                item["coordinate_source"] = "supplied dataset"
            elif same_address:
                item.update(
                    latitude=old.latitude,
                    longitude=old.longitude,
                    coordinate_source=old.coordinate_source,
                )
            objects.append(Station(**item))
        counts["unique_us_stations"] = len(objects)
        counts["with_coordinates"] = sum(s.latitude is not None for s in objects)
        if not options["dry_run"]:
            with transaction.atomic():
                Station.objects.bulk_create(
                    objects,
                    batch_size=400,
                    update_conflicts=True,
                    unique_fields=["source_id"],
                    update_fields=[
                        "name",
                        "address",
                        "city",
                        "state",
                        "price",
                        "latitude",
                        "longitude",
                        "coordinate_source",
                        "updated_at",
                    ],
                )
                if options["replace"]:
                    Station.objects.exclude(source_id__in=groups).delete()
        self.stdout.write(
            self.style.SUCCESS(
                ("Dry run: " if options["dry_run"] else "Imported: ")
                + ", ".join(f"{k}={v}" for k, v in counts.items())
            )
        )
        self.stdout.write(
            "Duplicate OPIS IDs use their arithmetic mean retail price. Missing coordinates remain unlocated; run geocode_stations or import_station_coordinates."
        )
