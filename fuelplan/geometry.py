"""Project approximate station coordinates onto a routed GeoJSON line."""

import math
from collections import defaultdict
from dataclasses import dataclass

from .fuel_data import FuelStation, normalize_place

GRID_DEGREES = 0.5
MAX_STATION_OFFSET_MILES = 10.0
MILES_PER_DEGREE_LAT = 69.0


@dataclass(frozen=True, slots=True)
class RouteStation:
    station: FuelStation
    route_mile: float
    offset_miles: float


@dataclass(frozen=True, slots=True)
class _Segment:
    start: tuple[float, float]
    end: tuple[float, float]
    start_mile: float
    length_miles: float


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Return great-circle distance between ``(longitude, latitude)`` pairs."""
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 3958.7613 * 2 * math.asin(math.sqrt(min(1.0, h)))


def _cell(value: float) -> int:
    return math.floor(value / GRID_DEGREES)


def _make_segments(coordinates: list[list[float]]) -> tuple[list[_Segment], float, dict[tuple[int, int], list[int]]]:
    if len(coordinates) < 2:
        raise ValueError("Route geometry must contain at least two coordinates.")
    segments: list[_Segment] = []
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    cumulative = 0.0
    for raw_start, raw_end in zip(coordinates, coordinates[1:]):
        start = (float(raw_start[0]), float(raw_start[1]))
        end = (float(raw_end[0]), float(raw_end[1]))
        length = haversine_miles(start, end)
        segment = _Segment(start, end, cumulative, length)
        segment_index = len(segments)
        segments.append(segment)
        cumulative += length
        min_x, max_x = sorted((start[0], end[0]))
        min_y, max_y = sorted((start[1], end[1]))
        for gx in range(_cell(min_x), _cell(max_x) + 1):
            for gy in range(_cell(min_y), _cell(max_y) + 1):
                grid[(gx, gy)].append(segment_index)
    return segments, cumulative, grid


def _project_to_segment(
    point: tuple[float, float], segment: _Segment
) -> tuple[float, float]:
    lon, lat = point
    start_lon, start_lat = segment.start
    end_lon, end_lat = segment.end
    mean_lat = math.radians((start_lat + end_lat + lat) / 3)
    x_scale = MILES_PER_DEGREE_LAT * math.cos(mean_lat)
    px, py = lon * x_scale, lat * MILES_PER_DEGREE_LAT
    ax, ay = start_lon * x_scale, start_lat * MILES_PER_DEGREE_LAT
    bx, by = end_lon * x_scale, end_lat * MILES_PER_DEGREE_LAT
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    t = 0.0 if length_squared == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    cross_track = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
    return t, cross_track


def match_stations_to_route(
    coordinates: list[list[float]],
    stations: tuple[FuelStation, ...],
    reported_distance_miles: float,
    *,
    max_offset_miles: float = MAX_STATION_OFFSET_MILES,
) -> list[RouteStation]:
    """Find fuel cities near the route and collapse co-located price duplicates.

    Census points represent city centers, not the exact truckstop. The 10-mile
    corridor therefore allows for that known imprecision while retaining the
    measured offset for range and response calculations.
    """
    segments, geometry_length, grid = _make_segments(coordinates)
    if geometry_length <= 0:
        raise ValueError("Route geometry has no measurable length.")
    scale = reported_distance_miles / geometry_length if reported_distance_miles > 0 else 1.0

    # Keep only one price row per city; at the same coordinate, the cheapest
    # station always dominates the more expensive rows.
    city_stations: dict[tuple[str, str], FuelStation] = {}
    for station in stations:
        key = (station.state, normalize_place(station.city))
        existing = city_stations.get(key)
        if existing is None or station.price_per_gallon < existing.price_per_gallon:
            city_stations[key] = station

    best_by_route_mile: dict[int, RouteStation] = {}
    for station in city_stations.values():
        gx, gy = _cell(station.longitude), _cell(station.latitude)
        segment_ids: set[int] = set()
        for x in range(gx - 1, gx + 2):
            for y in range(gy - 1, gy + 2):
                segment_ids.update(grid.get((x, y), ()))
        best: RouteStation | None = None
        station_point = (station.longitude, station.latitude)
        for segment_id in segment_ids:
            segment = segments[segment_id]
            fraction, offset = _project_to_segment(station_point, segment)
            if offset > max_offset_miles:
                continue
            candidate = RouteStation(
                station=station,
                route_mile=(segment.start_mile + fraction * segment.length_miles) * scale,
                offset_miles=offset,
            )
            if best is None or candidate.offset_miles < best.offset_miles:
                best = candidate
        if best is None:
            continue
        # Collapse nearby city centers to a single route-mile slot while
        # retaining the most cost-effective station at that point.
        slot = round(best.route_mile * 2)
        previous = best_by_route_mile.get(slot)
        if previous is None or (
            best.station.price_per_gallon,
            best.offset_miles,
        ) < (
            previous.station.price_per_gallon,
            previous.offset_miles,
        ):
            best_by_route_mile[slot] = best

    return sorted(best_by_route_mile.values(), key=lambda candidate: candidate.route_mile)
