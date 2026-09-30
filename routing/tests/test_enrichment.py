import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from django.test import TestCase
from django.core.management import call_command
from routing.models import Station


class EnrichmentTests(TestCase):
    def run_import(self, elements):
        with TemporaryDirectory() as folder:
            p = Path(folder) / "osm.json"
            p.write_text(json.dumps({"elements": elements}))
            call_command(
                "enrich_from_osm",
                str(p),
                export=str(Path(folder) / "coords.csv"),
                stdout=StringIO(),
            )

    def station(self, sid, name="LOVES TRAVEL STOP #123", city="Test", state="PA"):
        return Station.objects.create(
            source_id=sid, name=name, city=city, state=state, price="3.1"
        )

    def poi(self, sid=1, lon=-79, ref="123"):
        return {
            "type": "node",
            "id": sid,
            "lat": 41,
            "lon": lon,
            "tags": {
                "amenity": "fuel",
                "brand": "Love's",
                "ref": ref,
                "addr:state": "PA",
            },
        }

    def test_number_match_retains_provenance(self):
        s = self.station("1")
        self.run_import([self.poi()])
        s.refresh_from_db()
        self.assertEqual(s.longitude, -79)
        self.assertIn("node/1", s.coordinate_source)

    def test_ambiguous_distant_pois_are_not_guessed(self):
        s = self.station("1")
        self.run_import([self.poi(), self.poi(sid=2, lon=-80)])
        s.refresh_from_db()
        self.assertIsNone(s.latitude)

    def test_wrong_state_not_matched(self):
        s = self.station("1", state="OH")
        self.run_import([self.poi()])
        s.refresh_from_db()
        self.assertIsNone(s.latitude)

    def test_duplicate_source_chain_number_not_matched(self):
        self.station("1")
        self.station("2")
        self.run_import([self.poi()])
        self.assertEqual(Station.objects.filter(latitude__isnull=False).count(), 0)
