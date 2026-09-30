from decimal import Decimal
from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(
        max_length=200, allow_blank=False, trim_whitespace=True
    )
    finish = serializers.CharField(
        max_length=200, allow_blank=False, trim_whitespace=True
    )
    initial_fuel_price = serializers.DecimalField(
        max_digits=6,
        decimal_places=3,
        min_value=Decimal("0.001"),
        max_value=99,
        required=False,
    )

    def validate(self, attrs):
        if attrs["start"].casefold() == attrs["finish"].casefold():
            raise serializers.ValidationError(
                "Start and destination must be different."
            )
        return attrs
