import csv
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from decimal import Decimal
from django.test import TestCase
from django.core.management import call_command, CommandError
from routing.models import Station


class ImportTests(TestCase):
    headers = [
        "OPIS Truckstop ID",
        "Truckstop Name",
        "Address",
        "City",
        "State",
        "Rack ID",
        "Retail Price",
    ]

    def make_file(self, rows, suffix=".csv"):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        p = Path(temp.name) / ("fuel" + suffix)
        if suffix == ".xlsx":
            from openpyxl import Workbook

            w = Workbook()
            s = w.active
            s.append(self.headers)
            for r in rows:
                s.append(r)
            w.save(p)
        else:
            with p.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(self.headers)
                w.writerows(rows)
        return p

    def test_actual_columns_dedup_and_canada(self):
        p = self.make_file(
            [
                ["20", "Pilot", "I-8 exit 119", "Gila Bend", "AZ", "1", "3.1"],
                ["20", "Pilot alt", "I-8 exit 119", "Gila Bend", "AZ", "2", "3.3"],
                ["30", "Canada", "Road", "Toronto", "ON", "1", "4"],
            ]
        )
        call_command("import_fuel_prices", str(p), stdout=StringIO())
        self.assertEqual(Station.objects.count(), 1)
        s = Station.objects.get()
        self.assertEqual(s.price, Decimal("3.2"))
        self.assertIsNone(s.latitude)
        s.latitude = 32.0
        s.longitude = -112
        s.coordinate_source = "reviewed"
        s.save()
        call_command("import_fuel_prices", str(p), stdout=StringIO())
        self.assertEqual(Station.objects.get().latitude, 32)

    def test_invalid_file_is_atomic(self):
        p = self.make_file(
            [
                ["1", "A", "Road", "Town", "PA", "1", "3"],
                ["2", "B", "Road", "Town", "PA", "1", "NaN"],
            ]
        )
        with self.assertRaises(CommandError):
            call_command("import_fuel_prices", str(p), stdout=StringIO())
        self.assertEqual(Station.objects.count(), 0)

    def test_xlsx_and_dry_run(self):
        p = self.make_file([["1", "A", "Road", "Town", "PA", "1", 3.5]], ".xlsx")
        call_command("import_fuel_prices", str(p), dry_run=True, stdout=StringIO())
        self.assertFalse(Station.objects.exists())
        call_command("import_fuel_prices", str(p), stdout=StringIO())
        self.assertEqual(Station.objects.get().price, Decimal("3.5"))
