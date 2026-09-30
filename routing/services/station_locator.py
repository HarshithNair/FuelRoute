from dataclasses import dataclass
from math import cos, radians
from shapely.geometry import LineString, box
from shapely.strtree import STRtree
from django.conf import settings
from routing.models import Station
from .geo import haversine


@dataclass(frozen=True)
class Candidate:
    station: object
    progress: float
    access_miles: float
    offset_miles: float = 0
    route_point: tuple = (0, 0)


def find_candidates(route):
    """Index the full geometry once. O(G log G + S log G + nearby segments).

    Segment lengths use Haversine; projection uses a station-local plane.
    Chainage is scaled to OSRM distance. No provider calls per station.
    """
    coords = route.geometry
    segments, lengths, cumulative = [], [], [0.0]
    for a, b in zip(coords, coords[1:]):
        segments.append(LineString([a, b]))
        lengths.append(haversine(a, b))
        cumulative.append(cumulative[-1] + lengths[-1])
    if cumulative[-1] <= 0:
        return []
    tree = STRtree(segments)
    scale = route.distance_miles / cumulative[-1]
    lons, lats = zip(*coords)
    pad_lat = settings.CORRIDOR_MILES / 69 + 0.001
    pad_lon = pad_lat / max(0.1, cos(radians(max(abs(min(lats)), abs(max(lats))))))
    stations = Station.objects.filter(
        latitude__gte=min(lats) - pad_lat,
        latitude__lte=max(lats) + pad_lat,
        longitude__gte=min(lons) - pad_lon,
        longitude__lte=max(lons) + pad_lon,
    ).only(
        "source_id",
        "name",
        "city",
        "state",
        "price",
        "latitude",
        "longitude",
        "coordinate_source",
    )
    candidates = []
    for station in stations.iterator(chunk_size=1000):
        lon, lat = station.longitude, station.latitude
        k = max(0.1, cos(radians(lat)))
        nearby = tree.query(
            box(lon - pad_lat / k, lat - pad_lat, lon + pad_lat / k, lat + pad_lat)
        )
        best = None
        for raw_idx in nearby:
            idx = int(raw_idx)
            a, b = coords[idx], coords[idx + 1]
            ax, ay = (a[0] - lon) * k, a[1] - lat
            dx, dy = (b[0] - a[0]) * k, b[1] - a[1]
            denom = dx * dx + dy * dy
            t = max(0, min(1, -(ax * dx + ay * dy) / denom)) if denom else 0
            point = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            offset = haversine((lon, lat), point)
            progress = (cumulative[idx] + t * lengths[idx]) * scale
            if best is None or (offset, progress) < (best[0], best[1]):
                best = (offset, progress, point)
        if (
            best
            and best[0] <= settings.CORRIDOR_MILES
            and 0 < best[1] < route.distance_miles
        ):
            # The road-access factor is an estimate, not a routed detour.
            candidates.append(
                Candidate(
                    station, best[1], best[0] * settings.DETOUR_FACTOR, best[0], best[2]
                )
            )
    return sorted(candidates, key=lambda x: (x.progress, str(x.station.source_id)))
