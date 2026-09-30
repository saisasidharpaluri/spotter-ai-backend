from django.apps import AppConfig


class FuelPlanConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "fuelplan"

    def ready(self):
        from .fuel_data import get_stations

        get_stations()
