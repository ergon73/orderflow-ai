from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


def home(request):
    return JsonResponse({"service": "orderflow-ai", "status": "ok"})


def health(request):
    return JsonResponse({"status": "healthy"})


urlpatterns = [
    path("", home, name="home"),
    path("health/", health, name="health"),
    path("", include("dashboard.urls")),
    path("api/", include("orders.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="api-schema"),
        name="api-docs",
    ),
    path("admin/", admin.site.urls),
]
