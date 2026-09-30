from django.urls import path

from .views import health, route_fuel_plan

urlpatterns = [
    path("health/", health, name="health"),
    path("route-fuel-plan/", route_fuel_plan, name="route-fuel-plan"),
]
