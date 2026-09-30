from django.db import models
from django.db.models import Q


class Station(models.Model):
    source_id = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=500, blank=True)
    city = models.CharField(max_length=150)
    state = models.CharField(max_length=2, db_index=True)
    price = models.DecimalField(max_digits=12, decimal_places=8)
    latitude = models.FloatField(null=True, blank=True, db_index=True)
    longitude = models.FloatField(null=True, blank=True, db_index=True)
    coordinate_source = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(price__gt=0), name="positive_price"),
            models.CheckConstraint(
                condition=(
                    Q(latitude__isnull=True, longitude__isnull=True)
                    | Q(
                        latitude__gte=-90,
                        latitude__lte=90,
                        longitude__gte=-180,
                        longitude__lte=180,
                    )
                ),
                name="valid_coordinate_pair",
            ),
        ]
        indexes = [models.Index(fields=["latitude", "longitude"])]


class ProviderGate(models.Model):
    key = models.CharField(max_length=100, primary_key=True)
    next_allowed = models.FloatField(default=0)
