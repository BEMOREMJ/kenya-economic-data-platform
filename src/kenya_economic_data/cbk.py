"""Explicit parsing, validation, and reconciliation for the CBK historical CSV."""

from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from .source_contracts import parse_cbk_date


CURRENCY_MAP = {
    "US DOLLAR": "USD",
    "STG POUND": "GBP",
    "EURO": "EUR",
}

ACCEPTED_FIELDS = [
    "observation_date", "currency_code", "source_currency_label", "rate_type",
    "base_currency", "quote_currency", "unit_multiplier", "mean_rate",
    "buy_rate", "sell_rate", "source", "batch_id", "source_snapshot_sha256",
]
REJECTED_FIELDS = [
    "source_row_number", "raw_date", "raw_currency_label", "raw_mean",
    "raw_buy", "raw_sell", "reason",
]


@dataclass(frozen=True)
class CbkResult:
    accepted: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    reconciliation: dict[str, Any]
    blocked: bool


def validate_currency_selection(labels: tuple[str, ...]) -> None:
    unsupported = sorted(set(labels) - CURRENCY_MAP.keys())
    if unsupported:
        raise ValueError(f"unsupported CBK currencies: {', '.join(unsupported)}")


def process_cbk(
    raw_bytes: bytes,
    *,
    start_date: date,
    end_date: date,
    selected_labels: tuple[str, ...],
    retrieval_date: date,
    batch_id: str,
    snapshot_sha256: str,
) -> CbkResult:
    validate_currency_selection(selected_labels)
    reader = csv.reader(io.StringIO(raw_bytes.decode("utf-8-sig"), newline=""))
    physical_rows = list(reader)
    invalid: list[dict[str, Any]] = []
    valid: list[dict[str, Any]] = []

    for row_number, row in enumerate(physical_rows, start=1):
        padded = (row + [""] * 5)[:5]
        rejected_base = {
            "source_row_number": row_number,
            "raw_date": padded[0],
            "raw_currency_label": padded[1],
            "raw_mean": padded[2],
            "raw_buy": padded[3],
            "raw_sell": padded[4],
        }
        if len(row) != 5:
            invalid.append({**rejected_base, "reason": "field_count_not_5"})
            continue
        try:
            parsed_date = parse_cbk_date(row[0])
        except ValueError:
            invalid.append({**rejected_base, "reason": "unsupported_date_format"})
            continue
        if parsed_date > retrieval_date:
            invalid.append({**rejected_base, "reason": "observation_after_retrieval_date"})
            continue
        try:
            mean_rate, buy_rate, sell_rate = (float(value) for value in row[2:5])
        except ValueError:
            invalid.append({**rejected_base, "reason": "non_numeric_rate"})
            continue
        if not all(math.isfinite(value) and value > 0 for value in (mean_rate, buy_rate, sell_rate)):
            invalid.append({**rejected_base, "reason": "rate_not_finite_positive"})
            continue
        if not buy_rate <= mean_rate <= sell_rate:
            invalid.append({**rejected_base, "reason": "buy_mean_sell_order"})
            continue
        valid.append(
            {
                "source_row_number": row_number,
                "date": parsed_date,
                "raw_date": row[0],
                "label": row[1],
                "mean": mean_rate,
                "buy": buy_rate,
                "sell": sell_rate,
                "raw_mean": row[2],
                "raw_buy": row[3],
                "raw_sell": row[4],
            }
        )

    whole_groups: dict[tuple[date, str], list[dict[str, Any]]] = defaultdict(list)
    for row in valid:
        whole_groups[(row["date"], row["label"])].append(row)
    whole_exact_duplicates = 0
    whole_conflict_keys = 0
    whole_conflict_rows = 0
    whole_conflict_rejections: list[dict[str, Any]] = []
    for group in whole_groups.values():
        values = {(row["mean"], row["buy"], row["sell"]) for row in group}
        if len(values) == 1:
            whole_exact_duplicates += len(group) - 1
        else:
            whole_conflict_keys += 1
            whole_conflict_rows += len(group)
            for row in group:
                whole_conflict_rejections.append(
                    {
                        "source_row_number": row["source_row_number"],
                        "raw_date": row["raw_date"],
                        "raw_currency_label": row["label"],
                        "raw_mean": row["raw_mean"],
                        "raw_buy": row["raw_buy"],
                        "raw_sell": row["raw_sell"],
                        "reason": "conflicting_business_key_outside_scope",
                    }
                )

    excluded_date = [row for row in valid if not start_date <= row["date"] <= end_date]
    within_date = [row for row in valid if start_date <= row["date"] <= end_date]
    excluded_currency = [row for row in within_date if row["label"] not in selected_labels]
    selected = [row for row in within_date if row["label"] in selected_labels]

    selected_groups: dict[tuple[date, str], list[dict[str, Any]]] = defaultdict(list)
    for row in selected:
        selected_groups[(row["date"], row["label"])].append(row)

    accepted: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    selected_duplicate_rows = 0
    selected_conflict_keys = 0
    for (observation_date, label), group in sorted(selected_groups.items()):
        values = {(row["mean"], row["buy"], row["sell"]) for row in group}
        if len(values) > 1:
            selected_conflict_keys += 1
            for row in group:
                conflicts.append(
                    {
                        "source_row_number": row["source_row_number"],
                        "raw_date": row["raw_date"],
                        "raw_currency_label": row["label"],
                        "raw_mean": row["raw_mean"],
                        "raw_buy": row["raw_buy"],
                        "raw_sell": row["raw_sell"],
                        "reason": "conflicting_business_key",
                    }
                )
            continue
        selected_duplicate_rows += len(group) - 1
        row = min(group, key=lambda item: item["source_row_number"])
        accepted.append(
            {
                "observation_date": observation_date.isoformat(),
                "currency_code": CURRENCY_MAP[label],
                "source_currency_label": label,
                "rate_type": "indicative_opening_mean_buy_sell",
                "base_currency": CURRENCY_MAP[label],
                "quote_currency": "KES",
                "unit_multiplier": 1,
                "mean_rate": _decimal_text(row["raw_mean"]),
                "buy_rate": _decimal_text(row["raw_buy"]),
                "sell_rate": _decimal_text(row["raw_sell"]),
                "source": "CBK",
                "batch_id": batch_id,
                "source_snapshot_sha256": snapshot_sha256,
            }
        )

    accepted.sort(key=lambda row: (row["observation_date"], row["currency_code"]))
    selected_conflict_rows = {row["source_row_number"] for row in conflicts}
    whole_conflict_rejections = [
        ({**row, "reason": "conflicting_business_key"} if row["source_row_number"] in selected_conflict_rows else row)
        for row in whole_conflict_rejections
    ]
    rejected = sorted(
        invalid + whole_conflict_rejections,
        key=lambda row: (row["source_row_number"], row["reason"]),
    )
    equation_left = len(physical_rows)
    equation_right = len(invalid) + len(excluded_date) + len(excluded_currency) + len(selected)
    reconciliation = {
        "definitions": {
            "source_record": "one record emitted by Python csv.reader, including blank/malformed records",
            "accepted_observation": "one unique selected publication-date/currency business key",
            "duplicate_row": "an additional row with the same business key and identical three rates",
            "conflict_row": "a selected row whose business key has more than one distinct rate tuple",
            "whole_file_diagnostic": "overlapping, non-additive diagnostics across valid records; do not add these counts to the source partition",
        },
        "source_record_count": len(physical_rows),
        "valid_record_count": len(valid),
        "invalid_record_count": len(invalid),
        "excluded_date_record_count": len(excluded_date),
        "excluded_currency_record_count": len(excluded_currency),
        "selected_input_record_count": len(selected),
        "accepted_observation_count": len(accepted),
        "selected_exact_duplicate_row_count": selected_duplicate_rows,
        "selected_conflict_key_count": selected_conflict_keys,
        "selected_conflict_row_count": len(conflicts),
        "whole_file_exact_duplicate_row_count": whole_exact_duplicates,
        "whole_file_conflict_key_count": whole_conflict_keys,
        "whole_file_conflict_row_count": whole_conflict_rows,
        "quarantined_conflict_row_count": len(whole_conflict_rejections),
        "diagnostic_relationships": {
            "whole_file_counts_are_additive": False,
            "explanation": "Whole-file duplicate and conflict counts overlap valid records already partitioned by excluded-date, excluded-currency, and selected-input categories.",
        },
        "rejected_artifact_row_count": len(rejected),
        "source_max_observation_date": max(row["date"] for row in valid).isoformat(),
        "requested_start_date": start_date.isoformat(),
        "requested_end_date": end_date.isoformat(),
        "requested_window_publication_date_count": len({row["date"] for row in selected}),
        "warehouse_loaded_count": None,
        "published_count": None,
        "warehouse_counts_verified": False,
        "equations": {
            "source_partition": {
                "left": equation_left,
                "right": equation_right,
                "passed": equation_left == equation_right,
                "formula": "source = invalid + excluded_date + excluded_currency + selected_input",
            },
            "selected_resolution": {
                "left": len(selected),
                "right": len(accepted) + selected_duplicate_rows + len(conflicts),
                "passed": len(selected) == len(accepted) + selected_duplicate_rows + len(conflicts),
                "formula": "selected_input = accepted + exact_duplicates + conflict_rows",
            },
        },
        "quality_policy": {
            "completeness": "All selected currencies must exist on each CBK publication date present; weekends and holidays are not expected dates.",
            "freshness": "Historical requested-window completeness is independent of retrieval recency.",
            "quotation": "Selected labels are verified as KES per one USD/GBP/EUR; reversed and per-100 labels are excluded.",
        },
    }
    dates_to_codes: dict[str, set[str]] = defaultdict(set)
    for row in accepted:
        dates_to_codes[row["observation_date"]].add(row["currency_code"])
    expected_codes = set(CURRENCY_MAP[label] for label in selected_labels)
    incomplete_dates = sorted(day for day, codes in dates_to_codes.items() if codes != expected_codes)
    reconciliation["incomplete_publication_dates"] = incomplete_dates
    blocked = bool(conflicts or incomplete_dates or not all(
        equation["passed"] for equation in reconciliation["equations"].values()
    ))
    return CbkResult(accepted, rejected, reconciliation, blocked)


def _decimal_text(value: str) -> str:
    text = value.strip()
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text

