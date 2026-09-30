from math import radians, sin, cos, asin, sqrt

EARTH_MILES = 3958.7613
US_STATES = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)


def haversine(a, b):
    # Coordinates are always GeoJSON [longitude, latitude].
    lon1, lat1, lon2, lat2 = map(radians, (*a, *b))
    h = (
        sin((lat2 - lat1) / 2) ** 2
        + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_MILES * asin(min(1, sqrt(h)))
