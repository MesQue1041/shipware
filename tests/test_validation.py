"""Examples of valid uploads and mistakes that must reject the whole file."""

import csv
from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from shipware.validation import COLUMNS, MAX_ROWS, MAX_UPLOAD_BYTES, validate_csv

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample_shipments.csv"
VALID_ROW = ["0001", "Demo Parcel", "000123", "2026-10-29", "in_transit", "2026-10-29T17:30:00+05:30"]


def csv_bytes(rows, header=COLUMNS):
    """Build test CSVs with proper quoting, including embedded commas/newlines."""
    buffer = StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def test_sample_is_valid_and_has_nine_rows():
    shipments, errors = validate_csv(SAMPLE.read_bytes())
    assert errors == []
    assert len(shipments) == 9
    assert shipments.loc[0, "tracking_number"] == "000123"
    assert shipments.loc[8, "status"] == "in_transit"


def test_normalization_preserves_text_and_converts_to_utc():
    row = [f" {value} " for value in VALID_ROW]
    row[1] = " NA "  # This literal carrier name must not turn into a missing value.
    row[4] = " In_Transit "
    shipments, errors = validate_csv(csv_bytes([row]))
    assert errors == []
    assert shipments.loc[0, "shipment_id"] == "0001"
    assert shipments.loc[0, "carrier"] == "NA"
    assert shipments.loc[0, "tracking_number"] == "000123"
    assert shipments.loc[0, "status"] == "in_transit"
    assert shipments.loc[0, "expected_delivery_date"] == date(2026, 10, 29)
    update = shipments.loc[0, "last_update_at"]
    assert update == datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
    assert update.tzinfo == timezone.utc


@pytest.mark.parametrize("status", ["pending", "in_transit", "delivered", "cancelled"])
def test_blank_tracking_is_allowed_for_every_status(status):
    row = VALID_ROW.copy()
    row[2], row[4] = "   ", status
    shipments, errors = validate_csv(csv_bytes([row]))
    assert errors == []
    assert shipments.loc[0, "tracking_number"] == ""


@pytest.mark.parametrize("column", [name for name in COLUMNS if name != "tracking_number"])
def test_missing_required_values_name_the_row_and_field(column):
    row = VALID_ROW.copy()
    row[COLUMNS.index(column)] = " "
    shipments, errors = validate_csv(csv_bytes([row]))
    assert shipments is None
    assert f"Row 2: {column} is required." in errors


def test_duplicates_are_detected_after_trimming_and_report_both_rows():
    duplicate = VALID_ROW.copy()
    duplicate[0] = " 0001 "
    shipments, errors = validate_csv(csv_bytes([VALID_ROW, duplicate]))
    assert shipments is None
    assert len(errors) == 2
    assert errors[0].startswith("Row 2:")
    assert errors[1].startswith("Row 3:")
    assert all("unique" in error for error in errors)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("expected_delivery_date", "2026-02-29"),
        ("expected_delivery_date", "2026-04-31"),
        ("expected_delivery_date", "2026-1-02"),
        ("expected_delivery_date", "29/10/2026"),
        ("expected_delivery_date", "2026-10-29T00:00:00Z"),
        ("last_update_at", "2026-10-29T12:00:00"),
        ("last_update_at", "2026-10-29"),
        ("last_update_at", "2026-02-30T12:00:00Z"),
        ("last_update_at", "2026-10-29T25:00:00Z"),
        ("last_update_at", "2026-10-29T12:00:00+25:00"),
        ("last_update_at", "2026-10-29T12:00:00+05:60"),
        ("last_update_at", "0001-01-01T00:00:00+01:00"),
        ("status", "shipped"),
    ],
)
def test_invalid_fields_reject_the_entire_upload(column, value):
    invalid = VALID_ROW.copy()
    invalid[0] = "0002"
    invalid[COLUMNS.index(column)] = value
    shipments, errors = validate_csv(csv_bytes([VALID_ROW, invalid]))
    assert shipments is None  # Even the valid first row must not be returned.
    assert any(error.startswith("Row 3:") and column in error for error in errors)


def test_multiple_field_errors_are_shown_together():
    row = VALID_ROW.copy()
    row[1], row[3], row[4] = "", "bad-date", "unsupported"
    shipments, errors = validate_csv(csv_bytes([row]))
    assert shipments is None
    assert len(errors) == 3


@pytest.mark.parametrize("timestamp", ["2026-10-29T12:00:00Z", "2026-10-29T12:00Z", "2026-10-29T12:00:00.123456Z"])
def test_supported_utc_timestamp_forms(timestamp):
    row = VALID_ROW.copy()
    row[5] = timestamp
    shipments, errors = validate_csv(csv_bytes([row]))
    assert errors == []
    assert shipments.loc[0, "last_update_at"].tzinfo == timezone.utc


def test_bom_reordered_headers_and_quoted_cells_are_supported():
    row = VALID_ROW.copy()
    row[1] = "Demo, Parcel\nDivision"
    content = csv_bytes([list(reversed(row))], [f" {name} " for name in reversed(COLUMNS)])
    shipments, errors = validate_csv(b"\xef\xbb\xbf" + content)
    assert errors == []
    assert list(shipments.columns) == COLUMNS
    assert shipments.loc[0, "carrier"] == row[1]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "empty"),
        (csv_bytes([]), "no shipment rows"),
        (csv_bytes([VALID_ROW[:-1]]), "Row 2: expected 6 cells; found 5"),
        (csv_bytes([VALID_ROW + ["extra"]]), "Row 2: expected 6 cells; found 7"),
        (csv_bytes([[]]), "Row 2: expected 6 cells; found 0"),
        (csv_bytes([VALID_ROW]) + b'"unclosed', "cannot be read"),
        (csv_bytes([[VALID_ROW[0], "x" * 131_073, *VALID_ROW[2:]]]), "cannot be read"),
        (csv_bytes([VALID_ROW], COLUMNS[:-1] + ["status"]), "duplicate"),
        (csv_bytes([], COLUMNS[:-1]), "Missing columns: last_update_at"),
        (csv_bytes([], COLUMNS + ["notes"]), "Unexpected columns: notes"),
        (b"\xff\xfe", "UTF-8"),
        (csv_bytes([VALID_ROW]) + b"\x00", "null bytes"),
        (b"x" * (MAX_UPLOAD_BYTES + 1), "5 MiB"),
    ],
)
def test_file_errors_are_helpful(content, message):
    shipments, errors = validate_csv(content)
    assert shipments is None
    assert any(message in error for error in errors)


def test_upload_size_boundary():
    # Scale the limit down to check equality without building another large file.
    ordinary = csv_bytes([VALID_ROW])
    with patch("shipware.validation.MAX_UPLOAD_BYTES", len(ordinary)):
        assert validate_csv(ordinary)[1] == []
        assert validate_csv(ordinary + b" ")[0] is None


def test_row_limit_accepts_boundary_and_rejects_one_more():
    rows = [[str(index), *VALID_ROW[1:]] for index in range(MAX_ROWS)]
    shipments, errors = validate_csv(csv_bytes(rows))
    assert errors == []
    assert len(shipments) == MAX_ROWS
    rows.append(["extra-id", *VALID_ROW[1:]])
    shipments, errors = validate_csv(csv_bytes(rows))
    assert shipments is None
    assert "10,000" in errors[0]
