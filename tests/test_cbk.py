from datetime import date
from pathlib import Path

from kenya_economic_data.cbk import process_cbk


FIXTURES = Path(__file__).parent / "fixtures"
SELECTED = ("US DOLLAR", "STG POUND", "EURO")


def test_cbk_reconciliation_collapses_exact_duplicates_and_counts_exclusions() -> None:
    result = process_cbk(
        (FIXTURES / "synthetic_cbk_duplicates.csv").read_bytes(),
        start_date=date(2023, 10, 1),
        end_date=date(2023, 12, 31),
        selected_labels=SELECTED,
        retrieval_date=date(2026, 10, 5),
        batch_id="synthetic_batch",
        snapshot_sha256="0" * 64,
    )

    assert not result.blocked
    assert len(result.accepted) == 3
    assert result.reconciliation["selected_exact_duplicate_row_count"] == 1
    assert result.reconciliation["invalid_record_count"] == 2
    assert result.reconciliation["excluded_date_record_count"] == 1
    assert result.reconciliation["excluded_currency_record_count"] == 1
    assert result.reconciliation["equations"]["source_partition"]["passed"]
    assert result.reconciliation["equations"]["selected_resolution"]["passed"]
    assert result.reconciliation["diagnostic_relationships"]["whole_file_counts_are_additive"] is False
    assert {row["currency_code"] for row in result.accepted} == {"USD", "GBP", "EUR"}
    assert {row["reason"] for row in result.rejected} == {
        "observation_after_retrieval_date",
        "unsupported_date_format",
    }


def test_cbk_conflicts_are_quarantined_and_block_candidate() -> None:
    result = process_cbk(
        (FIXTURES / "synthetic_cbk_conflict.csv").read_bytes(),
        start_date=date(2023, 10, 1),
        end_date=date(2023, 12, 31),
        selected_labels=SELECTED,
        retrieval_date=date(2026, 10, 5),
        batch_id="synthetic_batch",
        snapshot_sha256="0" * 64,
    )

    assert result.blocked
    assert result.reconciliation["selected_conflict_key_count"] == 1
    assert result.reconciliation["selected_conflict_row_count"] == 2
    assert all(row["reason"] == "conflicting_business_key" for row in result.rejected)

