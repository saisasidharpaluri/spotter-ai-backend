"""Minimum-cost fueling plan along one fixed route."""

from dataclasses import dataclass
from decimal import Decimal

from .geometry import RouteStation

MAX_RANGE_MILES = 500.0
MILES_PER_GALLON = 10.0


@dataclass(frozen=True, slots=True)
class PlannedStop:
    route_station: RouteStation
    miles_from_previous_stop: float
    miles_to_next_stop: float
    gallons_purchased: float
    cost_usd: Decimal


@dataclass(frozen=True, slots=True)
class FuelPlan:
    stops: tuple[PlannedStop, ...]
    total_fuel_purchased_gallons: float
    total_cost_usd: Decimal


class NoFeasibleFuelPlan(ValueError):
    """Raised when no sequence of listed stations stays within vehicle range."""


def _fuel_cost(price: Decimal, gallons: float) -> Decimal:
    return price * Decimal(str(gallons))


def optimize_fuel_stops(route_distance_miles: float, stations: list[RouteStation]) -> FuelPlan:
    """Use the minimum-cost fuel-station greedy strategy on the route.

    Prices are ordered by projected route mile. At a stop, buy only enough to
    reach the next cheaper station within one full tank; if there is none,
    refuel to capacity and travel as far as possible. The first 500 route miles
    are already in the tank and are never charged. City-center offsets are
    reported separately; the fuel calculation uses projected route mileage.
    """
    if route_distance_miles < 0:
        raise ValueError("Route distance cannot be negative.")
    if route_distance_miles <= MAX_RANGE_MILES:
        return FuelPlan((), 0.0, Decimal("0.00"))

    ordered = sorted(stations, key=lambda item: item.route_mile)
    count = len(ordered)
    if not count:
        raise NoFeasibleFuelPlan("No fuel stations were found near this route.")

    # The next strictly cheaper station is the correct target when it is within
    # a full tank. A monotonic stack computes that target in linear time.
    next_cheaper: list[int | None] = [None] * count
    price_stack: list[int] = []
    for index in range(count - 1, -1, -1):
        price = ordered[index].station.price_per_gallon
        while price_stack and ordered[price_stack[-1]].station.price_per_gallon >= price:
            price_stack.pop()
        if price_stack:
            next_cheaper[index] = price_stack[-1]
        price_stack.append(index)

    # Furthest candidate reachable after filling at each station.
    furthest_reachable = [0] * count
    right = 0
    for left in range(count):
        right = max(right, left)
        while right + 1 < count and ordered[right + 1].route_mile - ordered[left].route_mile <= MAX_RANGE_MILES:
            right += 1
        furthest_reachable[left] = right

    def simulate(first_index: int) -> tuple[list[tuple[int, float]], Decimal] | None:
        current_index = first_index
        fuel_range = max(0.0, MAX_RANGE_MILES - ordered[first_index].route_mile)
        purchases: list[tuple[int, float]] = []
        total_cost = Decimal("0.00")

        for _ in range(count + 1):
            position = ordered[current_index].route_mile
            distance_to_destination = max(0.0, route_distance_miles - position)
            if distance_to_destination <= fuel_range + 1e-9:
                return purchases, total_cost

            cheaper_index = next_cheaper[current_index]
            if (
                cheaper_index is not None
                and ordered[cheaper_index].route_mile - position <= MAX_RANGE_MILES
            ):
                target = ordered[cheaper_index].route_mile - position
                purchased_range = max(0.0, target - fuel_range)
                if purchased_range > 1e-9:
                    gallons = purchased_range / MILES_PER_GALLON
                    purchases.append((current_index, gallons))
                    total_cost += _fuel_cost(ordered[current_index].station.price_per_gallon, gallons)
                fuel_range = max(0.0, fuel_range - target)
                current_index = cheaper_index
                continue

            if distance_to_destination <= MAX_RANGE_MILES:
                purchased_range = max(0.0, distance_to_destination - fuel_range)
                if purchased_range > 1e-9:
                    gallons = purchased_range / MILES_PER_GALLON
                    purchases.append((current_index, gallons))
                    total_cost += _fuel_cost(ordered[current_index].station.price_per_gallon, gallons)
                return purchases, total_cost

            purchased_range = max(0.0, MAX_RANGE_MILES - fuel_range)
            if purchased_range > 1e-9:
                gallons = purchased_range / MILES_PER_GALLON
                purchases.append((current_index, gallons))
                total_cost += _fuel_cost(ordered[current_index].station.price_per_gallon, gallons)

            target_index = furthest_reachable[current_index]
            if target_index == current_index:
                return None
            fuel_range = max(0.0, MAX_RANGE_MILES - (ordered[target_index].route_mile - position))
            current_index = target_index
        return None

    best_purchases: list[tuple[int, float]] | None = None
    best_total: Decimal | None = None
    for first_index, station in enumerate(ordered):
        if station.route_mile > MAX_RANGE_MILES:
            break
        result = simulate(first_index)
        if result is None:
            continue
        purchases, cost = result
        if best_total is None or cost < best_total:
            best_purchases, best_total = purchases, cost

    if best_purchases is None or best_total is None:
        raise NoFeasibleFuelPlan(
            "No listed fuel stations provide a route with every leg within 500 miles."
        )

    stops: list[PlannedStop] = []
    for purchase_index, (station_index, gallons) in enumerate(best_purchases):
        station = ordered[station_index]
        previous_position = 0.0 if purchase_index == 0 else ordered[best_purchases[purchase_index - 1][0]].route_mile
        next_position = (
            route_distance_miles
            if purchase_index + 1 == len(best_purchases)
            else ordered[best_purchases[purchase_index + 1][0]].route_mile
        )
        stops.append(
            PlannedStop(
                route_station=station,
                miles_from_previous_stop=max(0.0, station.route_mile - previous_position),
                miles_to_next_stop=max(0.0, next_position - station.route_mile),
                gallons_purchased=gallons,
                cost_usd=_fuel_cost(station.station.price_per_gallon, gallons),
            )
        )

    purchased = sum(stop.gallons_purchased for stop in stops)
    total = sum((stop.cost_usd for stop in stops), Decimal("0.00")).quantize(Decimal("0.01"))
    return FuelPlan(tuple(stops), purchased, total)
