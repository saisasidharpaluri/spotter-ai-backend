import hashlib
import json
import logging

from django.core.cache import cache
from django.http import JsonResponse

from .optimizer import NoFeasibleFuelPlan
from .planning import build_fuel_plan
from .routing import ProviderError

logger = logging.getLogger(__name__)


def health(request):
    if request.method != "GET":
        return JsonResponse({"error": {"code": "method_not_allowed", "message": "Use GET."}}, status=405)
    return JsonResponse({"status": "ok"})


def _error(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


def route_fuel_plan(request):
    if request.method != "POST":
        response = _error("method_not_allowed", "Use POST with a JSON body.", 405)
        response["Allow"] = "POST"
        return response
    if request.content_type != "application/json":
        return _error("unsupported_media_type", "Content-Type must be application/json.", 415)
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _error("invalid_json", "Request body must be valid JSON.", 400)
    if not isinstance(payload, dict):
        return _error("invalid_request", "Request body must be a JSON object.", 400)

    addresses = {}
    for field in ("start_address", "finish_address"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            return _error("invalid_request", f"'{field}' must be a non-empty address string.", 400)
        value = value.strip()
        if len(value) > 300:
            return _error("invalid_request", f"'{field}' must be 300 characters or fewer.", 400)
        addresses[field] = value

    cache_material = "\0".join(addresses[field].casefold() for field in ("start_address", "finish_address"))
    cache_key = "fuel-plan:" + hashlib.sha256(cache_material.encode("utf-8")).hexdigest()
    cached = cache.get(cache_key)
    if cached is not None:
        return JsonResponse(cached)

    try:
        result = build_fuel_plan(addresses["start_address"], addresses["finish_address"])
    except ProviderError as exc:
        return _error(exc.code, exc.message, exc.status)
    except NoFeasibleFuelPlan as exc:
        return _error("no_feasible_fuel_plan", str(exc), 422)
    except Exception:
        logger.exception("Route fuel planning failed unexpectedly")
        return _error("internal_error", "The route could not be planned due to an internal error.", 500)

    cache.set(cache_key, result, timeout=600)
    return JsonResponse(result)
