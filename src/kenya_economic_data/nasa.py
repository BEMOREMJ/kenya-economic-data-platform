"""NASA POWER request construction, parsing, validation, and reconciliation."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .config import Location


ACCEPTED_FIELDS = [
    "observation_date", "location_name", "latitude", "longitude", "time_standard",
    "t2m_c", "prectotcorr_mm_day", "source", "batch_id", "source_snapshot_sha256",
]
REJECTED_FIELDS = [
    "observation_date", "location_name", "raw_t2m", "raw_prectotcorr", "reason",
]


@dataclass(frozen=True)
class NasaLocationResult:
    accepted: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    reconciliation: dict[str, Any]
    source_metadata: dict[str, Any]
    blocked: bool


def request_parameters(
    location: Location,
    start_date: date,
    end_date: date,
    *,
    community: str,
    time_standard: str,
    parameters: tuple[str, ...],
) -> dict[str, str]:
    return {
        "parameters": ",".join(parameters),
        "community": community,
        "longitude": format(location.longitude, ".6f"),
        "latitude": format(location.latitude, ".6f"),
        "start": start_date.strftime("%Y%m%d"),
        "end": end_date.strftime("%Y%m%d"),
        "format": "JSON",
        "time-standard": time_standard,
    }


def process_nasa_location(
    raw_bytes: bytes,
    *,
    location: Location,
    start_date: date,
    end_date: date,
    missing_value: float,
    batch_id: str,
    snapshot_sha256: str,
) -> NasaLocationResult:
    payload = json.loads(raw_bytes.decode("utf-8"))
    header = payload.get("header", {})
    if header.get("time_standard") != "UTC":
        raise ValueError(f"NASA time standard is not UTC for {location.name}")
    declared_fill = float(header.get("fill_value"))
    if declared_fill != missing_value:
        raise ValueError(f"unexpected NASA fill value for {location.name}: {declared_fill}")
    definitions = payload.get("parameters", {})
    if definitions.get("T2M", {}).get("units") != "C":
        raise ValueError("unexpected NASA T2M unit")
    if definitions.get("PRECTOTCORR", {}).get("units") != "mm/day":
        raise ValueError("unexpected NASA PRECTOTCORR unit")
    values = payload.get("properties", {}).get("parameter", {})
    temperature = values.get("T2M", {})
    precipitation = values.get("PRECTOTCORR", {})
    expected_dates = _date_range(start_date, end_date)
    returned_keys = set(temperature) | set(precipitation)

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    missing_field_count = 0
    invalid_field_count = 0
    for day in expected_dates:
        key = day.strftime("%Y%m%d")
        raw_t2m = temperature.get(key)
        raw_precip = precipitation.get(key)
        reasons: list[str] = []
        t2m = _value_or_none(raw_t2m, missing_value)
        precip = _value_or_none(raw_precip, missing_value)
        if t2m is None:
            missing_field_count += 1
            reasons.append("missing_T2M")
        elif not math.isfinite(t2m) or not -90 <= t2m <= 60:
            invalid_field_count += 1
            reasons.append("invalid_T2M")
        if precip is None:
            missing_field_count += 1
            reasons.append("missing_PRECTOTCORR")
        elif not math.isfinite(precip) or not 0 <= precip <= 2000:
            invalid_field_count += 1
            reasons.append("invalid_PRECTOTCORR")
        if reasons:
            rejected.append(
                {
                    "observation_date": day.isoformat(),
                    "location_name": location.name,
                    "raw_t2m": "" if raw_t2m is None else raw_t2m,
                    "raw_prectotcorr": "" if raw_precip is None else raw_precip,
                    "reason": ";".join(reasons),
                }
            )
            continue
        accepted.append(
            {
                "observation_date": day.isoformat(),
                "location_name": location.name,
                "latitude": format(location.latitude, ".6f"),
                "longitude": format(location.longitude, ".6f"),
                "time_standard": "UTC",
                "t2m_c": _number_text(t2m),
                "prectotcorr_mm_day": _number_text(precip),
                "source": "NASA_POWER",
                "batch_id": batch_id,
                "source_snapshot_sha256": snapshot_sha256,
            }
        )

    expected_keys = {day.strftime("%Y%m%d") for day in expected_dates}
    missing_dates = sorted(expected_keys - returned_keys)
    extra_dates = sorted(returned_keys - expected_keys)
    rejected.sort(key=lambda row: row["observation_date"])
    reconciliation = {
        "location": location.name,
        "expected_date_count": len(expected_dates),
        "returned_unique_date_count": len(returned_keys & expected_keys),
        "missing_date_count": len(missing_dates),
        "extra_date_count": len(extra_dates),
        "missing_measurement_field_count": missing_field_count,
        "invalid_measurement_field_count": invalid_field_count,
        "rejected_observation_row_count": len(rejected),
        "accepted_observation_count": len(accepted),
        "missing_dates": missing_dates,
        "extra_dates": extra_dates,
        "equation": {
            "left": len(expected_dates),
            "right": len(accepted) + len(rejected),
            "passed": len(expected_dates) == len(accepted) + len(rejected),
            "formula": "expected rows = accepted rows + rejected rows",
        },
    }
    source_metadata = {
        "api": header.get("api"),
        "sources": header.get("sources"),
        "fill_value": declared_fill,
        "time_standard": header.get("time_standard"),
        "coordinates_returned": payload.get("geometry", {}).get("coordinates"),
        "units": {name: definitions.get(name, {}).get("units") for name in ("T2M", "PRECTOTCORR")},
    }
    blocked = bool(rejected or missing_dates or extra_dates or not reconciliation["equation"]["passed"])
    return NasaLocationResult(accepted, rejected, reconciliation, source_metadata, blocked)


def _date_range(start_date: date, end_date: date) -> list[date]:
    return [start_date + timedelta(days=offset) for offset in range((end_date - start_date).days + 1)]


def _value_or_none(value: Any, fill_value: float) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    return None if parsed == fill_value else parsed


def _number_text(value: float) -> str:
    return format(value, ".15g")

