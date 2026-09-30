from django.test import SimpleTestCase, override_settings

from .routing import GeocodedAddress, OpenRouteServiceClient, ProviderError


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, get_responses=(), post_responses=()):
        self.get_responses = list(get_responses)
        self.post_responses = list(post_responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.get_responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.post_responses.pop(0)


class OpenRouteServiceClientTests(SimpleTestCase):
    @override_settings(ORS_API_KEY="example-key")
    def test_geocodes_with_us_boundary(self):
        session = FakeSession(get_responses=[FakeResponse({
            "features": [{
                "geometry": {"coordinates": [-96.8, 32.8]},
                "properties": {"country_a": "USA", "label": "Dallas, TX, USA"},
            }]
        })])
        result = OpenRouteServiceClient(session).geocode_us_address("Dallas, TX")
        self.assertEqual(result, GeocodedAddress(-96.8, 32.8, "Dallas, TX, USA"))
        self.assertEqual(session.calls[0][2]["params"]["boundary.country"], "USA")
        self.assertEqual(session.calls[0][1], "https://api.heigit.org/pelias/v1/search")

    @override_settings(ORS_API_KEY="example-key")
    def test_rejects_non_us_geocoder_result(self):
        session = FakeSession(get_responses=[FakeResponse({
            "features": [{
                "geometry": {"coordinates": [-79.4, 43.7]},
                "properties": {"country_a": "CAN", "label": "Toronto, Canada"},
            }]
        })])
        with self.assertRaises(ProviderError) as error:
            OpenRouteServiceClient(session).geocode_us_address("Toronto, Canada")
        self.assertEqual(error.exception.code, "location_not_us")
        self.assertEqual(error.exception.status, 422)

    @override_settings(ORS_API_KEY="example-key")
    def test_reads_geojson_driving_route(self):
        session = FakeSession(post_responses=[FakeResponse({
            "type": "FeatureCollection",
            "features": [{
                "geometry": {"type": "LineString", "coordinates": [[-96.8, 32.8], [-84.4, 33.7]]},
                "properties": {"summary": {"distance": 1150000, "duration": 40000}},
            }],
        })])
        client = OpenRouteServiceClient(session)
        route = client.get_driving_route(GeocodedAddress(-96.8, 32.8, "start"), GeocodedAddress(-84.4, 33.7, "finish"))
        self.assertEqual(route.coordinates[0], [-96.8, 32.8])
        self.assertAlmostEqual(route.distance_miles, 714.6, places=1)
        self.assertEqual(route.duration_seconds, 40000)
        self.assertEqual(session.calls[0][1], "https://api.heigit.org/openrouteservice/v2/directions/driving-car/geojson")

    @override_settings(ORS_API_KEY="")
    def test_reports_missing_api_key_as_configuration_error(self):
        client = OpenRouteServiceClient(FakeSession())
        with self.assertRaises(ProviderError) as error:
            client.geocode_us_address("Dallas, TX")
        self.assertEqual(error.exception.status, 503)
