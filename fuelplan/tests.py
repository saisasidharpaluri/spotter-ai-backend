from decimal import Decimal
from unittest import TestCase

from django.test import SimpleTestCase

from .fuel_data import FuelStation, get_fuel_data_stats, get_stations
from .geometry import RouteStation, match_stations_to_route
from .optimizer import NoFeasibleFuelPlan, optimize_fuel_stops


def station(city: str, route_mile: float, price: str, offset: float = 0.0) -> RouteStation:
    fuel_station = FuelStation(
        station_id=city,
        name=city,
        address=f"{city} Road",
        city=city,
        state="TX",
        price_per_gallon=Decimal(price),
        latitude=0.0,
        longitude=0.0,
    )
    return RouteStation(fuel_station, route_mile, offset)


class FuelDataTests(SimpleTestCase):
    def test_csv_loads_us_stations_and_uses_approximate_coordinates(self):
        stations = get_stations()
        self.assertEqual(len(stations), 7209)
        stats = get_fuel_data_stats()
        self.assertEqual(stats["us_rows"], 7531)
        self.assertEqual(stats["unmatched_rows"], 322)
        canadian_provinces = {"AB", "BC", "MB", "NB", "NS", "ON", "QC", "SK", "YT"}
        self.assertTrue(all(item.state not in canadian_provinces for item in stations))
        woodshed = next(item for item in stations if item.name == "WOODSHED OF BIG CABIN")
        self.assertAlmostEqual(woodshed.latitude, 36.537602, places=5)
        self.assertAlmostEqual(woodshed.longitude, -95.229368, places=5)


class RouteMatchingTests(TestCase):
    def test_matches_near_city_centers_and_uses_cheapest_station_per_route_slot(self):
        route = [[-100.0, 30.0], [-99.0, 30.0]]
        stations = (
            FuelStation("1", "Expensive", "", "Same City", "TX", Decimal("4.00"), 30.1, -99.5),
            FuelStation("2", "Cheap", "", "Same City", "TX", Decimal("3.00"), 30.1, -99.5),
            FuelStation("3", "Far", "", "Remote", "TX", Decimal("2.00"), 32.0, -99.5),
        )
        found = match_stations_to_route(route, stations, 60.0)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].station.name, "Cheap")
        self.assertAlmostEqual(found[0].route_mile, 30.0, places=1)
        self.assertLess(found[0].offset_miles, 8.0)


class FuelOptimizerTests(SimpleTestCase):
    def test_initial_full_tank_is_excluded_and_minimum_cost_stops_are_returned(self):
        plan = optimize_fuel_stops(
            1000.0,
            [station("First", 200.0, "2.00"), station("Second", 700.0, "4.00")],
        )
        self.assertEqual([stop.route_station.station.city for stop in plan.stops], ["First", "Second"])
        self.assertEqual([stop.gallons_purchased for stop in plan.stops], [20.0, 30.0])
        self.assertEqual([stop.cost_usd for stop in plan.stops], [Decimal("40.00"), Decimal("120.00")])
        self.assertEqual(plan.total_fuel_purchased_gallons, 50.0)
        self.assertEqual(plan.total_cost_usd, Decimal("160.00"))

    def test_route_within_full_tank_range_needs_no_purchased_fuel(self):
        plan = optimize_fuel_stops(450.0, [])
        self.assertEqual(plan.stops, ())
        self.assertEqual(plan.total_cost_usd, Decimal("0.00"))

    def test_unreachable_stations_produce_a_clear_failure(self):
        with self.assertRaises(NoFeasibleFuelPlan):
            optimize_fuel_stops(900.0, [station("Too Far", 600.0, "3.00")])

    def test_every_chosen_leg_obeys_the_maximum_range(self):
        plan = optimize_fuel_stops(
            1400.0,
            [station("A", 450.0, "3.00"), station("B", 900.0, "2.50"), station("C", 1300.0, "3.00")],
        )
        for stop in plan.stops:
            self.assertLessEqual(stop.miles_to_next_stop, 500.0)
        self.assertLessEqual(plan.stops[0].miles_from_previous_stop, 500.0)
        self.assertGreater(plan.total_fuel_purchased_gallons, 0)

    def test_full_tank_capacity_can_carry_fuel_through_a_more_expensive_station(self):
        plan = optimize_fuel_stops(
            1000.0,
            [
                station("Cheap", 100.0, "1.00"),
                station("Mid", 300.0, "2.00"),
                station("Expensive", 500.0, "10.00"),
            ],
        )
        self.assertEqual(
            [stop.route_station.station.city for stop in plan.stops],
            ["Mid", "Expensive"],
        )
        self.assertEqual([stop.gallons_purchased for stop in plan.stops], [30.0, 20.0])
        self.assertEqual(plan.total_cost_usd, Decimal("260.00"))
