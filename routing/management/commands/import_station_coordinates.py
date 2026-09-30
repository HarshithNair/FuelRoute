import csv
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from routing.models import Station


class Command(BaseCommand):
    help = "Attach reviewed station coordinates by source_id from CSV; never use city centroids."

    def add_arguments(self, p):
        p.add_argument("path")

    def handle(self, *args, **options):
        stations = {s.source_id: s for s in Station.objects.all()}
        updates = []
        try:
            with open(options["path"], encoding="utf-8-sig", newline="") as f:
                rows = csv.DictReader(f)
                if not {
                    "source_id",
                    "latitude",
                    "longitude",
                    "coordinate_source",
                } <= set(rows.fieldnames or []):
                    raise CommandError(
                        "Required columns: source_id,latitude,longitude,coordinate_source"
                    )
                seen = set()
                for i, row in enumerate(rows, 2):
                    sid = row["source_id"]
                    if sid not in stations or sid in seen:
                        raise CommandError(
                            f"Row {i}: unknown or duplicate station {sid}"
                        )
                    seen.add(sid)
                    station = stations[sid]
                    lat, lon = float(row["latitude"]), float(row["longitude"])
                    if (
                        not (-90 <= lat <= 90 and -180 <= lon <= 180)
                        or not row["coordinate_source"].strip()
                    ):
                        raise ValueError(f"Invalid coordinate/source at row {i}")
                    station.latitude = lat
                    station.longitude = lon
                    station.coordinate_source = row["coordinate_source"]
                    updates.append(station)
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        with transaction.atomic():
            Station.objects.bulk_update(
                updates, ["latitude", "longitude", "coordinate_source"], batch_size=400
            )
        self.stdout.write(self.style.SUCCESS(f"Located {len(updates)} stations."))
