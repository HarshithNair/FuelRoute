# Five-minute Loom script

1. **0:00–0:40 — Explain the brief.** Show FuelRoute, the supplied file's actual headers, 500-mile range and 10 MPG. Explain the full starting tank and why consumed starting fuel is charged.
2. **0:40–1:40 — Postman.** Send New York → Los Angeles. Highlight route distance, number of candidate stations, fuel stops, total cost and auditable `legs`. Show every leg ≤500 and total cost = initial fuel consumed + purchases.
3. **1:40–2:40 — Dashboard.** Calculate the same trip. Show full route, numbered markers, station popup, station-to-map button, summary, and Export plan. Explain that dashed access connectors are estimates.
4. **2:40–3:10 — Short route.** New York → Philadelphia: no fuel stops, positive cost for consumed starting fuel. Show that reversing the fields works.
5. **3:10–3:40 — Errors.** Same locations →400; Toronto →outside-USA. Explain missing coordinate coverage fails safely rather than making up stops.
6. **3:40–4:35 — Backend.** Show the isolated optimizer, distance filter and importer. One route request per cold calculation, no route requests per station, persistent caches. Explain exact min-cost flow and bounded solver runtime.
7. **4:35–5:00 — Evidence.** Show passing tests and `docs/verification.md`; mention real OSM coordinate enrichment, snapshot prices and detour limitations.

Start the local server and preflight the two live routes before recording; public providers have no uptime guarantee. Keep Postman and the dashboard side-by-side. Import the included collection and set `base_url` if using a different host.
