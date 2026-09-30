"""Join the external route, local fuel prices, and stop optimizer."""

from decimal import Decimal

from .fuel_data import get_stations
from .geometry import match_stations_to_route
from .optimizer import MAX_RANGE_MILES, MILES_PER_GALLON, optimize_fuel_stops
from .routing import OpenRouteServiceClient


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def build_fuel_plan(start_address: str, finish_address: str, client: OpenRouteServiceClient | None = None) -> dict:
    client = client or OpenRouteServiceClient()
    start = client.geocode_us_address(start_address)
    finish = client.geocode_us_address(finish_address)
    route = client.get_driving_route(start, finish)
    candidates = match_stations_to_route(route.coordinates, get_stations(), route.distance_miles)
    plan = optimize_fuel_stops(route.distance_miles, candidates)

    stops = []
    for stop in plan.stops:
        station = stop.route_station.station
        stops.append(
            {
                "station_id": station.station_id,
                "name": station.name,
                "address": station.address,
                "city": station.city,
                "state": station.state,
                "price_per_gallon_usd": float(station.price_per_gallon),
                "coordinates": {"latitude": station.latitude, "longitude": station.longitude},
                "location_accuracy": "approximate_city_center",
                "city_center_offset_from_route_miles": round(stop.route_station.offset_miles, 2),
                "distance_from_start_miles": round(stop.route_station.route_mile, 2),
                "distance_from_previous_stop_miles": round(stop.miles_from_previous_stop, 2),
                "distance_to_next_stop_miles": round(stop.miles_to_next_stop, 2),
                "range_added_by_purchase_miles": round(stop.gallons_purchased * MILES_PER_GALLON, 2),
                "gallons_purchased": round(stop.gallons_purchased, 3),
                "estimated_cost_usd": _money(stop.cost_usd),
            }
        )

    return {
        "route": {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": route.coordinates},
            "properties": {
                "start": start.label,
                "finish": finish.label,
                "distance_miles": round(route.distance_miles, 2),
                "duration_seconds": round(route.duration_seconds, 1),
                "source": "OpenRouteService / OpenStreetMap",
            },
        },
        "fuel_stops": stops,
        "summary": {
            "distance_miles": round(route.distance_miles, 2),
            "duration_seconds": round(route.duration_seconds, 1),
            "fuel_efficiency_miles_per_gallon": MILES_PER_GALLON,
            "fuel_consumed_gallons": round(route.distance_miles / MILES_PER_GALLON, 3),
            "fuel_purchased_en_route_gallons": round(plan.total_fuel_purchased_gallons, 3),
            "estimated_fuel_spend_usd": _money(plan.total_cost_usd),
            "currency": "USD",
            "maximum_range_miles": MAX_RANGE_MILES,
            "initial_fuel_assumption": "Starts with a full 500-mile range; the initial tank cost is excluded.",
            "fuel_estimate_basis": "Route miles at 10 mpg; local access mileage to approximate city-center station points is not included.",
            "fuel_price_source": "fuel-prices-for-be-assessment.csv (prices used as supplied)",
            "station_coordinate_accuracy": "Approximate Census city/town representative point, not exact truckstop coordinates.",
            "matched_fuel_station_count": len(candidates),
        },
    }
