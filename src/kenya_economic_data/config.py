"""Typed loading and validation for non-secret extraction configuration."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Location:
    name: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Settings:
    project_root: Path
    cbk_currencies: tuple[str, ...]
    cbk_raw_path: Path
    cbk_source_url: str
    cbk_verified_sha256: str
    nasa_endpoint: str
    nasa_community: str
    nasa_time_standard: str
    nasa_parameters: tuple[str, ...]
    nasa_missing_value: float
    locations: dict[str, Location]
    connect_timeout_seconds: float
    read_timeout_seconds: float
    retry_after_cap_seconds: float
    max_attempts: int
    max_window_days: int


def load_settings(path: Path) -> Settings:
    config_path = path.resolve()
    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    root = config_path.parent.parent
    source = raw["sources"]
    http = raw.get("http", {})
    limits = raw.get("extraction", {})

    locations: dict[str, Location] = {}
    for item in source["nasa_power"]["locations"]:
        location = Location(
            name=str(item["name"]),
            latitude=float(item["latitude"]),
            longitude=float(item["longitude"]),
        )
        if location.name in locations:
            raise ValueError(f"duplicate configured location: {location.name}")
        if not -90 <= location.latitude <= 90 or not -180 <= location.longitude <= 180:
            raise ValueError(f"invalid coordinates for {location.name}")
        locations[location.name] = location

    nasa_parameters = tuple(source["nasa_power"]["parameters"])
    if nasa_parameters != ("T2M", "PRECTOTCORR"):
        raise ValueError("NASA parameters must be exactly T2M and PRECTOTCORR for Phase 1")
    if source["nasa_power"]["community"] != "AG":
        raise ValueError("NASA community must be AG for Phase 1")
    if source["nasa_power"]["time_standard"] != "UTC":
        raise ValueError("NASA time standard must be UTC for Phase 1")

    return Settings(
        project_root=root,
        cbk_currencies=tuple(source["cbk"]["currencies"]),
        cbk_raw_path=root / source["cbk"]["raw_path"],
        cbk_source_url=str(source["cbk"]["source_url"]),
        cbk_verified_sha256=str(source["cbk"]["verified_sha256"]),
        nasa_endpoint=str(source["nasa_power"]["endpoint"]),
        nasa_community=str(source["nasa_power"]["community"]),
        nasa_time_standard=str(source["nasa_power"]["time_standard"]),
        nasa_parameters=nasa_parameters,
        nasa_missing_value=float(source["nasa_power"]["missing_value"]),
        locations=locations,
        connect_timeout_seconds=float(http.get("connect_timeout_seconds", 10)),
        read_timeout_seconds=float(http.get("read_timeout_seconds", 30)),
        retry_after_cap_seconds=float(http.get("retry_after_cap_seconds", 10)),
        max_attempts=int(http.get("max_attempts", 3)),
        max_window_days=int(limits.get("max_window_days", 366)),
    )

