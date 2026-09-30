import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, SimpleTestCase

from .optimizer import NoFeasibleFuelPlan
from .routing import ProviderError


class RouteFuelPlanApiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.request_body = {
            "start_address": "Dallas, TX",
            "finish_address": "Atlanta, GA",
        }

    def tearDown(self):
        cache.clear()

    def post(self, body=None):
        return self.client.post(
            "/api/v1/route-fuel-plan/",
            data=json.dumps(self.request_body if body is None else body),
            content_type="application/json",
        )

    def test_rejects_missing_or_invalid_addresses(self):
        response = self.post({"start_address": "Dallas, TX"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

        response = self.post({"start_address": " ", "finish_address": "Atlanta, GA"})
        self.assertEqual(response.status_code, 400)

    def test_rejects_malformed_json_and_wrong_content_type(self):
        response = self.client.post("/api/v1/route-fuel-plan/", data="{", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_json")

        response = self.client.post("/api/v1/route-fuel-plan/", data={"start_address": "Dallas"})
        self.assertEqual(response.status_code, 415)

    @patch("fuelplan.views.build_fuel_plan")
    def test_returns_and_caches_successful_route_plan(self, build_plan):
        build_plan.return_value = {"route": {"geometry": {"type": "LineString", "coordinates": []}}, "fuel_stops": [], "summary": {}}
        first = self.post()
        second = self.post()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), second.json())
        build_plan.assert_called_once_with("Dallas, TX", "Atlanta, GA")

    @patch("fuelplan.views.build_fuel_plan", side_effect=ProviderError("location_not_us", "Both addresses must be within the United States.", 422))
    def test_non_us_addresses_are_rejected(self, _build_plan):
        response = self.post({"start_address": "Toronto, Canada", "finish_address": "Atlanta, GA"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "location_not_us")

    @patch("fuelplan.views.build_fuel_plan", side_effect=NoFeasibleFuelPlan("No listed fuel stations provide a route with every leg within 500 miles."))
    def test_impossible_fuel_plan_has_clear_error(self, _build_plan):
        response = self.post()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "no_feasible_fuel_plan")

    @patch("fuelplan.views.build_fuel_plan", side_effect=ProviderError("routing_provider_error", "The routing service is temporarily unavailable.", 502))
    def test_provider_outage_is_returned_as_gateway_error(self, _build_plan):
        response = self.post()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "routing_provider_error")

    @patch("fuelplan.views.build_fuel_plan", side_effect=ProviderError("routing_not_configured", "Routing is not configured. Set the ORS_API_KEY environment variable.", 503))
    def test_missing_provider_key_is_returned_as_service_unavailable(self, _build_plan):
        response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "routing_not_configured")

    def test_other_methods_return_json_405(self):
        response = self.client.get("/api/v1/route-fuel-plan/")
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.headers["Allow"], "POST")
        self.assertEqual(response.json()["error"]["code"], "method_not_allowed")
