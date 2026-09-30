from django.urls import path
from .views import RouteView, DataStatusView

urlpatterns = [
    path("route/", RouteView.as_view(), name="route"),
    path("status/", DataStatusView.as_view(), name="data-status"),
]
