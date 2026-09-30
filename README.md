# Route Fuel Planner API

A Django API that returns a US driving route as GeoJSON and chooses cost-effective fuel stops from the provided truckstop price dataset. The vehicle model has a 500-mile maximum range and achieves 10 miles per gallon.

## Run locally

1. Create a free OpenRouteService/HeiGIT API key. `.env.example` lists the available settings; the app reads environment variables and does not load `.env` automatically.
2. In PowerShell, set the key for the current session with `$env:ORS_API_KEY="your-key"`.
3. Install and start the service:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   python manage.py runserver
   ```

The health check is `GET http://127.0.0.1:8000/api/v1/health/`.

## Plan a route

Send `POST http://127.0.0.1:8000/api/v1/route-fuel-plan/` with `Content-Type: application/json`:

```json
{
  "start_address": "Dallas, TX",
  "finish_address": "Atlanta, GA"
}
```

The response includes:

- `route`: a GeoJSON `Feature` with the driving route `LineString`, distance, duration, resolved US addresses, and source attribution.
- `fuel_stops`: selected station details, approximate city-center coordinates, price, route position, gallons purchased, and estimated cost at each stop.
- `summary`: distance, fuel consumed and purchased, estimated en-route spend in USD, vehicle assumptions, and data accuracy notes.

The planner starts with a full 500-mile range. Fuel already in that initial tank is not charged; the spend total covers fuel purchased after departure. Stop selection uses the lowest-cost feasible fueling strategy with partial refills and fuel carried between stops. The route geometry distance drives the 10 mpg estimate. Because neither source file contains exact station coordinates, Census city/town representative points are used; the selected point may be up to 10 miles from the route, and local access mileage to the actual truckstop is not included in the cost or range calculation.

The supplied CSV has 7,531 rows in US states/DC and Canadian provinces. Province rows are excluded. The 2025 Census places and county subdivisions match 7,209 US station rows (about 95.7%) to city/state coordinates; unmatched rows are omitted from routing. The source archives and attribution are in [`data/README.md`](data/README.md).

## Map and Loom walkthrough

Import [`postman/Route Fuel Planner.postman_collection.json`](postman/Route%20Fuel%20Planner.postman_collection.json) into Postman. Its request is prefilled with a Dallas-to-Atlanta example. Set `baseUrl` to `http://127.0.0.1:8000`, start the service, and send the request. The Postman **Visualize** tab draws the route and numbered recommended fuel stops from the returned GeoJSON and station coordinates. The API response itself remains ordinary JSON for clients to render on any map.

For a five-minute Loom: briefly show the request and response, open **Visualize** to show the route and stops, then point to `fuelplan/routing.py`, `fuelplan/optimizer.py`, and `fuelplan/planning.py` for a short code overview. The collection and this README are included to make that walkthrough repeatable; record and share the Loom separately.

## External calls and response time

An uncached request makes two HeiGIT Pelias geocoding calls (one per address) and one OpenRouteService directions call. Repeated requests with the same ordered addresses use a 10-minute process-local response cache. Calls use an 8-second timeout by default; set `ORS_TIMEOUT_SECONDS` to change it. The fuel CSV and coordinate gazetteers are loaded once when Django starts, so they are not fetched per request.

The client uses the current HeiGIT host and paths: `api.heigit.org/pelias/v1/search` and `api.heigit.org/openrouteservice/v2/directions/driving-car/geojson`. A free key is required. See the [HeiGIT API restrictions](https://openrouteservice.org/restrictions/) before using the public service beyond this assessment.

## Errors

Errors use a consistent JSON shape, for example:

```json
{
  "error": {
    "code": "no_feasible_fuel_plan",
    "message": "No listed fuel stations provide a route with every leg within 500 miles."
  }
}
```

Malformed inputs return `400`, unsupported content types `415`, unknown/non-US addresses or infeasible plans `422`, provider/configuration failures `502`/`503`, and unexpected internal errors `500`.

## Tests

Run `python manage.py test`. The suite covers CSV filtering and coordinate lookup, route projection, full-tank and 500-mile constraints, price-based station choice including carried fuel, API validation and caching, and routing-provider success/error responses. Provider calls are mocked so tests do not require an API key or network access.
