"""Small synchronous client for HeiGIT's OpenRouteService endpoints."""

import math
from dataclasses import dataclass

import requests
from django.conf import settings


class ProviderError(Exception):
    """A safe, user-facing error from geocoding or routing."""

    def __init__(self, code: str, message: str, status: int = 502):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class GeocodedAddress:
    longitude: float
    latitude: float
    label: str


@dataclass(frozen=True, slots=True)
class DrivingRoute:
    coordinates: list[list[float]]
    distance_miles: float
    duration_seconds: float


class OpenRouteServiceClient:
    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.base_url = settings.ORS_BASE_URL.rstrip("/")
        self.api_key = settings.ORS_API_KEY
        self.timeout = settings.ORS_TIMEOUT_SECONDS

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ProviderError(
                "routing_not_configured",
                "Routing is not configured. Set the ORS_API_KEY environment variable.",
                503,
            )
        return {"Authorization": self.api_key, "Accept": "application/json"}

    def geocode_us_address(self, address: str) -> GeocodedAddress:
        try:
            response = self.session.get(
                f"{self.base_url}/pelias/v1/search",
                params={"text": address, "boundary.country": "USA", "size": 1},
                headers=self._headers(),
                timeout=self.timeout,
            )
            if response.status_code >= 500 or response.status_code in {401, 403, 429}:
                raise ProviderError("routing_provider_error", "The address service is temporarily unavailable.")
            if response.status_code >= 400:
                raise ProviderError("address_not_found", "Address could not be found within the United States.", 422)
            payload = response.json()
        except ProviderError:
            raise
        except (requests.RequestException, ValueError) as exc:
            raise ProviderError("routing_provider_error", "The address service is temporarily unavailable.") from exc

        if not isinstance(payload, dict):
            raise ProviderError("routing_provider_error", "The address service returned an invalid response.")
        features = payload.get("features") or []
        if not isinstance(features, list):
            raise ProviderError("routing_provider_error", "The address service returned an invalid response.")
        if not features:
            raise ProviderError("address_not_found", "Address could not be found within the United States.", 422)
        feature = features[0]
        if not isinstance(feature, dict):
            raise ProviderError("routing_provider_error", "The address service returned an invalid location.")
        properties = feature.get("properties") or {}
        if not isinstance(properties, dict):
            raise ProviderError("routing_provider_error", "The address service returned an invalid location.")
        if properties.get("country_a") not in {"USA", "US"}:
            raise ProviderError("location_not_us", "Both addresses must be within the United States.", 422)
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise ProviderError("address_not_found", "Address could not be found within the United States.", 422)
        try:
            longitude, latitude = float(coordinates[0]), float(coordinates[1])
        except (TypeError, ValueError) as exc:
            raise ProviderError("routing_provider_error", "The address service returned an invalid location.") from exc
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            raise ProviderError("routing_provider_error", "The address service returned an invalid location.")
        return GeocodedAddress(
            longitude=longitude,
            latitude=latitude,
            label=str(properties.get("label") or address),
        )

    def get_driving_route(self, start: GeocodedAddress, finish: GeocodedAddress) -> DrivingRoute:
        try:
            response = self.session.post(
                f"{self.base_url}/openrouteservice/v2/directions/driving-car/geojson",
                json={"coordinates": [[start.longitude, start.latitude], [finish.longitude, finish.latitude]]},
                headers={**self._headers(), "Content-Type": "application/json"},
                timeout=self.timeout,
            )
            if response.status_code in {400, 404, 422}:
                raise ProviderError("route_not_found", "No driving route could be found between these addresses.", 422)
            if response.status_code >= 400:
                raise ProviderError("routing_provider_error", "The routing service is temporarily unavailable.")
            payload = response.json()
        except ProviderError:
            raise
        except (requests.RequestException, ValueError) as exc:
            raise ProviderError("routing_provider_error", "The routing service is temporarily unavailable.") from exc

        try:
            feature = payload["features"][0]
            geometry = feature["geometry"]
            coordinates = geometry["coordinates"]
            summary = feature["properties"]["summary"]
            if not isinstance(geometry, dict) or not isinstance(summary, dict) or not isinstance(coordinates, list):
                raise ValueError("invalid route response")
            distance_meters = float(summary["distance"])
            duration_seconds = float(summary["duration"])
            if geometry.get("type") != "LineString" or len(coordinates) < 2:
                raise ValueError("invalid route geometry")
            if not math.isfinite(distance_meters) or not math.isfinite(duration_seconds):
                raise ValueError("invalid route summary")
            if distance_meters <= 0 or duration_seconds < 0:
                raise ValueError("invalid route summary")
            normalized_coordinates = []
            for coordinate in coordinates:
                if len(coordinate) < 2:
                    raise ValueError("invalid route coordinate")
                lon, lat = float(coordinate[0]), float(coordinate[1])
                if not math.isfinite(lon) or not math.isfinite(lat) or not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    raise ValueError("route coordinate out of bounds")
                normalized_coordinates.append([lon, lat])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError("routing_provider_error", "The routing service returned an invalid route.") from exc
        return DrivingRoute(
            coordinates=normalized_coordinates,
            distance_miles=distance_meters * 0.000621371192,
            duration_seconds=duration_seconds,
        )
