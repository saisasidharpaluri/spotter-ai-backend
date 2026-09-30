"""Load fuel prices and offline Census place coordinates once per process."""

import csv
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

from django.conf import settings


US_STATES = frozenset(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS "
    "MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA "
    "WV WI WY DC".split()
)

_PLACE_SUFFIX = re.compile(
    r"\s+(?:city|town|borough|village|cdp|municipality|plantation|urban county|zona urbana)$",
    re.IGNORECASE,
)
_SUBDIVISION_SUFFIX = re.compile(
    r"\s+(?:ccd|county|township|town|borough|city|municipality|district|plantation|"
    r"parish|precinct|magisterial district|census area|division)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class FuelStation:
    station_id: str
    name: str
    address: str
    city: str
    state: str
    price_per_gallon: Decimal
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class FuelData:
    stations: tuple[FuelStation, ...]
    stats: dict[str, int]


def normalize_place(value: str) -> str:
    """Normalize names while reconciling common city-name abbreviations."""
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    words = text.split()
    if words:
        words[0] = {"st": "saint", "ste": "sainte", "ft": "fort", "mt": "mount"}.get(words[0], words[0])
    return " ".join(words)


def _gazetteer_entries(archive_path: Path, suffix: re.Pattern[str]) -> dict[tuple[str, str], set[tuple[float, float]]]:
    entries: dict[tuple[str, str], set[tuple[float, float]]] = {}
    try:
        with zipfile.ZipFile(archive_path) as archive:
            text_files = [name for name in archive.namelist() if name.lower().endswith(".txt")]
            if not text_files:
                raise ValueError("archive contains no text gazetteer")
            with archive.open(text_files[0]) as binary:
                lines = (line.decode("utf-8") for line in binary)
                next(lines, None)
                for line in lines:
                    columns = line.rstrip("\r\n").split("|")
                    if len(columns) < 12 or columns[0] not in US_STATES:
                        continue
                    name = suffix.sub("", columns[4]).strip()
                    key = (columns[0], normalize_place(name))
                    try:
                        point = (float(columns[-2]), float(columns[-1]))
                    except ValueError:
                        continue
                    entries.setdefault(key, set()).add(point)
    except (OSError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"Cannot read Census coordinates at {archive_path}: {exc}") from exc
    return entries


@lru_cache(maxsize=1)
def get_city_coordinates() -> dict[tuple[str, str], tuple[float, float]]:
    """Return unique city/state coordinates, preferring Census places."""
    places = _gazetteer_entries(Path(settings.CENSUS_PLACES_PATH), _PLACE_SUFFIX)
    subdivisions = _gazetteer_entries(Path(settings.CENSUS_SUBDIVISIONS_PATH), _SUBDIVISION_SUFFIX)
    coordinates: dict[tuple[str, str], tuple[float, float]] = {}
    for key, points in places.items():
        if len(points) == 1:
            coordinates[key] = next(iter(points))
    for key, points in subdivisions.items():
        if key not in coordinates and len(points) == 1:
            coordinates[key] = next(iter(points))
    return coordinates


@lru_cache(maxsize=1)
def _load_fuel_data() -> FuelData:
    """Validate the supplied CSV, retain U.S. rows, and attach place points."""
    path = Path(settings.FUEL_DATA_PATH)
    coordinates = get_city_coordinates()
    required = {
        "OPIS Truckstop ID", "Truckstop Name", "Address", "City", "State", "Retail Price"
    }
    stations: list[FuelStation] = []
    us_rows = 0
    unmatched_rows = 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                raise ValueError(f"CSV must contain columns: {', '.join(sorted(required))}")
            for line_number, row in enumerate(reader, start=2):
                state = (row.get("State") or "").strip().upper()
                price_text = (row.get("Retail Price") or "").strip()
                try:
                    price = Decimal(price_text)
                except InvalidOperation as exc:
                    raise ValueError(f"Invalid retail price at CSV line {line_number}") from exc
                if not price.is_finite() or price <= 0:
                    raise ValueError(f"Invalid retail price at CSV line {line_number}")
                if state not in US_STATES:
                    continue
                us_rows += 1
                city = (row.get("City") or "").strip()
                point = coordinates.get((state, normalize_place(city)))
                if point is None:
                    unmatched_rows += 1
                    continue
                stations.append(
                    FuelStation(
                        station_id=(row.get("OPIS Truckstop ID") or "").strip(),
                        name=(row.get("Truckstop Name") or "").strip(),
                        address=(row.get("Address") or "").strip(),
                        city=city,
                        state=state,
                        price_per_gallon=price,
                        latitude=point[0],
                        longitude=point[1],
                    )
                )
    except OSError as exc:
        raise RuntimeError(f"Cannot read fuel price data at {path}: {exc}") from exc
    if not stations:
        raise RuntimeError("No U.S. fuel stations could be matched to Census coordinates.")
    return FuelData(
        stations=tuple(stations),
        stats={"us_rows": us_rows, "matched_rows": len(stations), "unmatched_rows": unmatched_rows},
    )


def get_stations() -> tuple[FuelStation, ...]:
    return _load_fuel_data().stations


def get_fuel_data_stats() -> dict[str, int]:
    return dict(_load_fuel_data().stats)
