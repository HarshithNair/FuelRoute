"""Live integration check. Uses configured external services; run after import."""

import os, sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from rest_framework.test import APIClient

client = APIClient(HTTP_HOST="localhost")
output = Path("artifacts")
output.mkdir(exist_ok=True)
for name, start, finish in [
    ("short", "New York, NY", "Philadelphia, PA"),
    ("cross-country", "New York, NY", "Los Angeles, CA"),
]:
    response = client.post(
        "/api/route/", {"start": start, "finish": finish}, format="json"
    )
    data = response.json()
    (output / f"{name}.json").write_text(json.dumps(data, indent=2))
    print(name, response.status_code, flush=True)
    if response.status_code != 200:
        print(data, flush=True)
        sys.exit(1)
    assert all(leg["distance_miles"] <= 500 for leg in data["legs"])
    assert (
        abs(
            sum(s["cost"] for s in data["fuel_stops"])
            + data["initial_fuel_cost"]
            - data["total_fuel_cost"]
        )
        < 0.005
    )
    assert abs(data["total_gallons"] - data["total_distance_miles"] / 10) < 1e-6
    assert (
        abs(
            50
            + sum(s["gallons"] for s in data["fuel_stops"])
            - data["ending_fuel_gallons"]
            - data["total_gallons"]
        )
        < 1e-5
    )
    print(
        {
            k: data[k]
            for k in [
                "distance_miles",
                "total_distance_miles",
                "total_gallons",
                "total_fuel_cost",
                "candidate_stations",
                "data_coverage",
            ]
        },
        flush=True,
    )
    print(
        "Stops:",
        [(s["name"], s["city"], s["state"]) for s in data["fuel_stops"]],
        flush=True,
    )
