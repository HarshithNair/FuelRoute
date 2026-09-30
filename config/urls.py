from django.urls import path, include
from django.views.generic import TemplateView

urlpatterns = [
    path("", TemplateView.as_view(template_name="index.html"), name="home"),
    path("api/docs/", TemplateView.as_view(template_name="docs.html"), name="api-docs"),
    path("api/", include("routing.urls")),
]
