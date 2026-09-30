from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase

from .fuel_data import FuelStation
from .planning import build_fuel_plan
from .routing import DrivingRoute, GeocodedAddress


class FakeRoutingClient:
    def __init__(self):
        self.geocoded = []
        self.routed = 0

    def geocode_us_address(self, address):
        self.geocoded.append(address)
        return GeocodedAddress(-96.8, 32.8, address)

    def get_driving_route(self, start, finish):
        self.routed += 1
        return DrivingRoute([[0.0, 0.0], [15.0, 0.0]], 1000.0, 60000.0)


class FuelPlanningServiceTests(SimpleTestCase):
    @patch("fuelplan.planning.get_stations")
    def test_builds_geojson_and_accounts_for_fuel_purchased_after_full_tank(self, get_stations):
        get_stations.return_value = (
            FuelStation("A", "First stop", "I-1", "City A", "TX", Decimal("2.50"), 0.0, 7.5),
            FuelStation("B", "Second stop", "I-2", "City B", "TX", Decimal("2.00"), 0.0, 13.5),
        )
        client = FakeRoutingClient()

        result = build_fuel_plan("Dallas, TX", "Atlanta, GA", client)

        self.assertEqual(client.geocoded, ["Dallas, TX", "Atlanta, GA"])
        self.assertEqual(client.routed, 1)
        self.assertEqual(result["route"]["geometry"]["type"], "LineString")
        self.assertEqual([stop["name"] for stop in result["fuel_stops"]], ["First stop", "Second stop"])
        self.assertAlmostEqual(result["summary"]["fuel_purchased_en_route_gallons"], 50.0, places=1)
        self.assertEqual(result["summary"]["estimated_fuel_spend_usd"], 120.0)
        self.assertAlmostEqual(result["summary"]["fuel_consumed_gallons"], 100.0, places=1)
        self.assertEqual(result["summary"]["distance_miles"], 1000.0)
        self.assertIn("local access mileage", result["summary"]["fuel_estimate_basis"])
