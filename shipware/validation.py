"""Validate an entire shipment CSV before returning normalized data."""

import csv
import re
from datetime import date, datetime, timezone
from io import StringIO

import pandas as pd

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_ROWS = 10_000
COLUMNS = [
    "shipment_id",
    "carrier",
    "tracking_number",
    "expected_delivery_date",
    "status",
    "last_update_at",
]
STATUSES = {"pending", "in_transit", "delivered", "cancelled"}
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
# Require a clock time and an explicit UTC marker or numeric timezone offset.
TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?"
    r"(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)",
    re.ASCII,
)


def validate_csv(content: bytes) -> tuple[pd.DataFrame | None, list[str]]:
    """Return a clean table, or None and helpful errors; never a partial table."""
    if len(content) > MAX_UPLOAD_BYTES:
        return None, ["File exceeds the 5 MiB upload limit."]
    try:
        # utf-8-sig also accepts the invisible header marker some CSV tools add.
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, ["Save the file as UTF-8 CSV and upload it again."]
    if "\x00" in text:
        return None, ["File contains null bytes. Save it as a plain UTF-8 CSV."]

    reader = csv.reader(StringIO(text, newline=""), strict=True)
    rows = []
    errors = []
    try:
        header = [name.strip() for name in next(reader, [])]
        if not header:
            return None, ["The file is empty. Include a header and shipment rows."]
        if len(header) != len(set(header)):
            return None, ["Header contains duplicate column names."]
        missing = [name for name in COLUMNS if name not in header]
        extra = [name for name in header if name not in COLUMNS]
        if missing:
            errors.append("Missing columns: " + ", ".join(missing) + ".")
        if extra:
            errors.append("Unexpected columns: " + ", ".join(extra) + ". Use the documented six columns.")
        if errors:
            return None, errors

        for row_number, row in enumerate(reader, start=2):
            if row_number > MAX_ROWS + 1:
                return None, ["File exceeds the 10,000 shipment row limit."]
            # Check shape first: CSV readers can otherwise hide extra or missing cells.
            if len(row) != len(header):
                errors.append(f"Row {row_number}: expected 6 cells; found {len(row)}.")
            rows.append(row)
    except csv.Error:
        # Do not echo parser details, which may contain uploaded shipment values.
        return None, [f"CSV record near line {reader.line_num} cannot be read. Check quoting and field lengths."]

    if errors:
        return None, errors
    if not rows:
        return None, ["The file has a header but no shipment rows."]

    # Start with strings so leading zeros and literal values such as 'NA' survive.
    shipments = pd.DataFrame(rows, columns=header, dtype="string")[COLUMNS]
    for column in COLUMNS:
        shipments[column] = shipments[column].str.strip()
    shipments["status"] = shipments["status"].str.lower()

    duplicate_ids = shipments["shipment_id"].duplicated(keep=False)
    delivery_dates = []
    update_times = []
    for index, row in shipments.iterrows():
        row_number = index + 2
        for column in COLUMNS:
            if column != "tracking_number" and not row[column]:
                errors.append(f"Row {row_number}: {column} is required.")
        if row["shipment_id"] and duplicate_ids[index]:
            errors.append(f"Row {row_number}: shipment_id must be unique within this file.")
        if row["status"] and row["status"] not in STATUSES:
            errors.append(f"Row {row_number}: status must be pending, in_transit, delivered, or cancelled.")

        delivery_date = None
        if row["expected_delivery_date"]:
            try:
                if not DATE_PATTERN.fullmatch(row["expected_delivery_date"]):
                    raise ValueError
                delivery_date = date.fromisoformat(row["expected_delivery_date"])
            except ValueError:
                errors.append(f"Row {row_number}: expected_delivery_date must be a real date in YYYY-MM-DD format.")
        delivery_dates.append(delivery_date)

        update_time = None
        if row["last_update_at"]:
            try:
                if not TIMESTAMP_PATTERN.fullmatch(row["last_update_at"]):
                    raise ValueError
                update_time = datetime.fromisoformat(row["last_update_at"]).astimezone(timezone.utc)
            except (ValueError, OverflowError):
                errors.append(
                    f"Row {row_number}: last_update_at must be an ISO 8601 timestamp with a timezone, "
                    "for example 2026-10-29T12:00:00Z or 2026-10-29T17:30:00+05:30."
                )
        update_times.append(update_time)

    if errors:
        return None, errors
    # Python dates and aware UTC datetimes keep calendar dates separate from times.
    shipments["expected_delivery_date"] = pd.Series(delivery_dates, dtype=object)
    shipments["last_update_at"] = pd.Series(update_times, dtype=object)
    return shipments, []
