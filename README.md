# FuelRoute

A Django/DRF fuel-route assessment: enter two US locations, calculate a real driving route, and minimize fuel purchases among reachable, geocoded stations from the supplied price file. Includes a responsive dashboard, interactive Leaflet map, an exact fuel optimizer, data-preparation commands, and automated tests.

**Python 3.12+ · Django 6.1.1 · DRF · SQLite · SciPy/HiGHS · Leaflet**

## Run locally

```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createcachetable
python manage.py import_fuel_prices
python manage.py import_station_coordinates data/station_coordinates.csv
python manage.py collectstatic --noinput
python manage.py runserver
```

Open **http://127.0.0.1:8000/**. API reference: **http://127.0.0.1:8000/api/docs/**.

The supplied assessment file is at `data/fuel_prices.csv`. `data/station_coordinates.csv` contains independently matched real OpenStreetMap fuel POIs, with provenance, for a subset of that dataset. Import both files. The application never substitutes demonstration results or city centroids. A route without a reachable sequence of located stations returns an explicit coverage error. See `docs/verification.md` for verified routes and current coverage.

## Architecture

```text
config/                        settings, URLs, WSGI
routing/
  models.py                    normalized station prices and coordinate provenance
  serializers.py               request validation
  views.py                     orchestration and HTTP responses
  services/
    geocoding_service.py       cached US location lookup + provider rate gate
    routing_service.py         one OSRM route request and geometry cache
    station_locator.py        spatial index, segment projection and chainage
    fuel_optimizer.py         fuel-constrained minimum-cost path / MILP
  management/commands/         import and offline coordinate enrichment
  tests/                       optimizer, API, provider, projection, import tests
static/                        CSS, JS, vendored Leaflet + license
 templates/                    dashboard and API documentation
 data/                         supplied prices + reusable coordinate enrichment
 docs/                         Postman collection, verification and demo guide
```

The route endpoint makes **at most two geocoding requests and one driving-routing request on a cold cache**. Warm geocoding/routing caches avoid those requests. Station enrichment happens before route calculation. The route geometry is reused for all station calculations and rendered directly by the frontend. There are no per-station driving requests.

## The supplied file, not an invented schema

Inspected columns:

| Source column | Treatment |
| --- | --- |
| OPIS Truckstop ID | Stable station identity; unique database key |
| Truckstop Name | Station name |
| Address | Original street/interstate/exit description |
| City / State | Location text; US state/DC allowlist |
| Rack ID | Recognized as a rack identifier, not a station ID or price timestamp |
| Retail Price | USD per gallon, retained to 8 decimal places |

The supplied file has **8,151 rows**, including **620 non-US rows**. The US rows contain **905 repeated station IDs**, resulting in **6,626 unique US stations**. There are no latitude/longitude columns. Because there is no date/product discriminator, duplicate rows for one OPIS ID are normalized to the **arithmetic mean retail price**, not silently treated as different stations or assumed to be latest observations. The dataset does not specify freshness or fuel grade; use its prices as an assessment snapshot.

```sh
# CSV is the default; XLSX is also supported, streaming the first worksheet.
python manage.py import_fuel_prices data/fuel_prices.csv
python manage.py import_fuel_prices /path/to/file.xlsx --dry-run
# Explicitly remove old stations not present in a replacement dataset:
python manage.py import_fuel_prices /path/to/replacement.csv --replace
```

The command prints detected headers, validates all input before writing, uses transactional bulk upserts, and preserves enriched coordinates only when the address/city/state is unchanged. Invalid prices and conflicting station locations fail the import without partially writing. Non-US rows are counted and excluded. Recognized optional coordinate columns are `latitude/lat` and `longitude/lon/lng`. Common explicit aliases for station name and price are supported; missing required columns produce a clear error.

## Coordinates and coverage

City-center coordinates are insufficient for highway fuel selection. Imported stations without coordinates remain unlocated and are excluded from optimization. The status endpoint and dashboard show both imported and located counts.

Three preprocessing options:

1. **Reuse the included enriched coordinate CSV.** `import_station_coordinates` joins it by `source_id`. Coordinates include the OSM element ID and match method. These are real POIs joined to the supplied price data, not invented prices.
2. **Bulk OSM matching.** `fetch_osm_stations` downloads major-chain US fuel POIs once. `enrich_from_osm` performs a local, conservative match using a unique chain + station number, or an unambiguous chain + city + state. Distant/ambiguous duplicate matches are rejected. Public Overpass queries can time out; regional extracts can be supplied directly to the same importer. No price data is sent to Overpass.
3. **A small address/POI lookup batch.** `geocode_stations --ids ... --limit 20` uses cached, rate-limited Nominatim. It accepts fuel POIs only, never a city result. A public-provider batch is capped at 50. Do not repeatedly run this against the public service to process thousands of stations; use a self-hosted/licensed provider or an OSM extract for nationwide enrichment. Ambiguous results require review and a coordinate CSV.

```sh
python manage.py fetch_osm_stations
python manage.py enrich_from_osm data/osm_stations.json
python manage.py geocode_stations --ids 7263,63770 --limit 2
python manage.py import_station_coordinates data/station_coordinates.csv
```

Coordinate CSV columns: `source_id,latitude,longitude,coordinate_source`. It is idempotent and rejects unknown/duplicate IDs or invalid coordinates. OSM-derived data is © OpenStreetMap contributors under the [ODbL](https://www.openstreetmap.org/copyright). Spatial matches can reflect stale brands or source addresses; the provenance is retained for review. Full nationwide coverage is not claimed.

## API

### `POST /api/route/`

```sh
curl -X POST http://127.0.0.1:8000/api/route/ \
  -H 'Content-Type: application/json' \
  -d '{"start":"New York, NY","finish":"Los Angeles, CA"}'
```

Optional `initial_fuel_price`: decimal USD/gal between 0.001 and 99, e.g. `"3.500"`. This values fuel already in the full starting tank. It defaults to the mean of normalized US station prices, explicitly labeled in the response/UI.

Successful responses include:

- `start`, `finish`: resolved names, latitude, longitude.
- `distance_miles`, `duration_hours`: OSRM base route; excludes refueling and station-access time.
- `fuel_efficiency_mpg: 10`, `vehicle_range_miles: 500`, `initial_fuel_gallons: 50`.
- `fuel_stops`: station ID/name/city/state, coordinates and source, progress along the **base route**, actual modeled journey progress, price, gallons, rounded cost, and estimated station-access distance.
- `legs`: every modeled leg, its distance, fuel on departure, and fuel on arrival. This is the range audit.
- `total_distance_miles`, `detour_miles`: base distance plus the estimated round-trip access for visited stations.
- `total_gallons`: `total_distance_miles / 10`.
- `initial_fuel_cost`, `fuel_purchase_cost`, `total_fuel_cost`: starting fuel consumed + rounded purchases.
- `ending_fuel_gallons`, `initial_fuel_consumed_gallons`, `initial_fuel_price`, `initial_price_source`.
- `route_geometry`: full base-route coordinates in **[longitude, latitude]** order; frontend converts them to Leaflet order.
- `candidate_stations`, `data_coverage`, `optimizer_status`, `assumptions`.

A deterministic **illustrative** 600-mile case with one on-route station at mile 400, a $3/gal station price, and starting fuel valued at $3.50/gal has:

```json
{
  "distance_miles": 600,
  "fuel_efficiency_mpg": 10,
  "vehicle_range_miles": 500,
  "fuel_stops": [{"distance_into_route": 400, "price_per_gallon": 3,
    "gallons": 10, "cost": 30}],
  "total_gallons": 60,
  "initial_fuel_cost": 175,
  "fuel_purchase_cost": 30,
  "total_fuel_cost": 205,
  "ending_fuel_gallons": 0
}
```

This is a math example, not a hardcoded API response. Full live responses are written to `artifacts/` by `python scripts/live_smoke.py`.

Errors use `{"error":{"code":"...","message":"...","details":{...}}}`:

| Status | Examples |
| --- | --- |
| 400 | Empty/oversized fields, invalid JSON, identical input strings, invalid price |
| 422 | Unknown location, outside USA, same resolved place, no driving route, no reachable fuel stop |
| 429 | Rate limit exceeded (30/min/IP); inspect Retry-After |
| 503 | Missing fuel data, geocoding/routing outage, optimizer time/candidate limit |

### `GET /api/status/`

Reports imported station count, located count, dataset readiness, MPG, and range. `ready` means prices are loaded, not that every possible route is covered. The API intentionally permits unauthenticated local assessment use. Add authentication and deployment-specific rate controls for a public commercial service.

## Optimization and the 500-mile constraint

**Assumptions:** a full 50-gallon initial tank, 10 MPG, 500-mile range, no minimum reserve. A short trip uses initial fuel and needs no stops. A longer trip ends empty in the mathematical model; only its consumed starting fuel plus later purchases are charged. This avoids treating a full initial tank as free, or charging a short trip for a whole unused tank. Fuel type and vehicle preset are fixed.

1. Build an STRtree spatial index of the full OSRM route segments. A database bounding box excludes distant stations; local projection computes the nearest route point and along-route progress. Cumulative Haversine distance is scaled to OSRM's road distance.
2. Keep stations within `CORRIDOR_MILES` (default 2). One-way station access is straight-line offset × `DETOUR_FACTOR` (default 1.5).
3. Build a forward directed acyclic graph. For stations i and j, modeled travel distance is `progress[j] - progress[i] + access[i] + access[j]`. Start/end have zero access distance. **Never create an edge longer than 500 miles.**
4. Solve a mixed-integer minimum-cost flow with SciPy/HiGHS. Binary variables select route legs; continuous variables track fuel and purchases. Path-flow constraints select one route, fuel conservation enforces consumption, and departure fuel cannot exceed 50 gallons. Minimize `sum(price[i] * gallons[i])`; the initial fuel cost is constant for long routes.
5. Require proven solver success. Timeouts are explicit 503s, not unlabeled approximate answers. Audit the chosen path again for capacity, nonnegative fuel, and leg length before returning it.

This handles the “buy just enough until a cheaper reachable station, otherwise buy more now” tradeoff globally. Unlike a simple next-cheaper greedy rule, it also accounts for the fuel cost of station detours. It does not choose a station merely because it is 500 miles away.

Spatial work is roughly `O(G log G + S log G + local intersections)` for G segments and S nearby stations. The optimizer has at most `O(N²)` forward edges and sparse constraints. MILP has exponential worst-case complexity; `MAX_CANDIDATES` and `SOLVER_SECONDS` bound resource usage. The implementation does not silently prune away potentially cheaper stations to claim optimality. Large workloads should move to a job queue and benchmark their solver budget.

### Precision and cost reconciliation

Optimization uses floating-point continuous gallons. The returned purchase gallons are rounded to six decimals. Station prices preserve eight decimals from the import. Each displayed purchase cost is computed with Decimal and round-half-up to cents, and `total_fuel_cost` is exactly the sum of these rounded purchase costs plus rounded starting fuel consumed. Distances and leg fuel balances retain precision. Gallon conservation can differ by a few millionths from displayed purchase rounding. The objective is minimum unrounded monetary cost, with cent-rounded reporting.

## Free APIs and performance

- [OSRM Route API](https://project-osrm.org/docs/v5.24.0/api/#route-service): one request with `overview=full`, `geometries=geojson`, no alternatives/steps; distance and geometry reused locally. One-day route cache.
- [Nominatim](https://operations.osmfoundation.org/policies/nominatim/): explicit user-submitted location searches only, no autocomplete; one-second-plus request spacing across local workers, identifiable user agent, persistent 30-day success cache and one-hour negative cache. Its public endpoint is for low-volume use.
- OSM station enrichment runs independently of route requests. Overpass receives spatial/brand queries, not the price file.
- Leaflet is vendored locally. The regional basemap uses bundled public-domain Natural Earth countries, US state boundaries and city labels, avoiding tile-server keys and availability issues. It is a geographic overview, not a street-level navigation map. Natural Earth and OSM attribution remain visible. The map renders the returned geometry; it never requests routes itself.
- One indexed bounding-box station query, no station-by-station database or API lookup during projection. SQLite-backed caches persist through restarts.
- Logs report API elapsed milliseconds; responses include a `Server-Timing` header.
- Public demonstration services have no availability guarantee. Configure a self-hosted OSRM/Nominatim and appropriate map tiles for sustained production traffic. TLS verification is enabled and timeouts are bounded. No secret keys are hardcoded.

## Configuration

| Variable | Default / purpose |
| --- | --- |
| `DEBUG` | `true` for local demo; use `false` in deployment |
| `SECRET_KEY` | Development-only value; non-development value required when DEBUG=false |
| `ALLOWED_HOSTS` | localhost,127.0.0.1 (explicit deployment hosts) |
| `DATABASE_PATH` | project db.sqlite3 |
| `OSRM_URL` | https://router.project-osrm.org |
| `GEOCODER_URL` | https://nominatim.openstreetmap.org |
| `GEOCODER_USER_AGENT` | Identifying application/contact string |
| `HTTP_TIMEOUT` | 25 seconds per provider request |
| `CORRIDOR_MILES` | 2 miles maximum straight-line offset |
| `DETOUR_FACTOR` | 1.5 × straight-line one-way station offset |
| `MAX_CANDIDATES` | 300; explicit failure above this threshold |
| `SOLVER_SECONDS` | 15; exact solution required |
| `SECURE_SSL_REDIRECT` | false locally; true behind a correctly configured HTTPS deployment |

For deployment: set production environment variables, run migrations/cache creation/import/collectstatic, then `gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 2 --timeout 120` behind HTTPS. Use a persistent writable database/volume, backups and monitoring. If proxying, configure trusted forwarded headers for that infrastructure rather than blindly trusting arbitrary client headers. SQLite is the assessment default; replace it with PostgreSQL/shared Redis and a distributed provider limiter when scaling beyond one machine.

## Test and demonstrate

```sh
python manage.py collectstatic --noinput
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
# Live checks, after importing prices and coordinates (requires network):
python scripts/live_smoke.py
```

Tests cover short/exact-range/long/cross-country cases, partial purchases, cheapest reachable choices, detour penalties and infeasibility, conservation of gallons, monetary rounding, imported schema/duplicates/Canadian rows/XLSX/atomicity, malformed inputs/provider failures, cache reuse, segment projection, and API integration. Randomized small instances are checked against an independent exhaustive fuel-state dynamic program.

Import `docs/FuelRoute.postman_collection.json` in Postman. Follow `docs/demo.md` for a five-minute presentation.

## Known limitations — the meaning of this estimate

- All leg distances obey 500 miles **under the modeled access distances**. The model cannot prove that a nearby station is accessible across a river, divided highway, interchange, or private road without additional road-network routing. Detour connectors on the map are dashed estimates, not turn-by-turn directions. Base-route geometry is genuine OSRM geometry. For dispatch-grade range guarantees, use a local road graph to calculate exact station-access distances; that can still preserve one external routing request.
- The best plan is among located dataset stations in the corridor, on the selected base route. It does not globally reroute highways for lower prices or claim coverage of unlocated stations.
- Fuel prices are a supplied snapshot, not a live pump-price feed. Duplicate averaging and initial-price estimation are disclosed. There are no taxes, tolls, grades, idling, terrain, weather, or traffic adjustments.
- Duration excludes station detours and refueling; the 500-mile range assumes no reserve. Confirm station availability and access before real travel.
- Public API rate limits, outages and geocoding ambiguity are handled as errors; there is no fake offline success fallback. Coordinates can go stale and may need manual review.
