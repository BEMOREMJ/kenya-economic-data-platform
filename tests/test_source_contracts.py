from datetime import date

import pytest

from kenya_economic_data.source_contracts import parse_cbk_date


@pytest.mark.parametrize("raw", ["2023-10-02", "02/10/2023"])
def test_parse_cbk_date_supports_both_observed_formats(raw: str) -> None:
    assert parse_cbk_date(raw) == date(2023, 10, 2)


def test_parse_cbk_date_rejects_ambiguous_or_unobserved_formats() -> None:
    with pytest.raises(ValueError, match="unsupported CBK date"):
        parse_cbk_date("10/02/23")

