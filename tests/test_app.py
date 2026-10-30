"""Exercise the page with real validation and simulated file uploads."""

from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_page_starts_without_an_upload():
    app = AppTest.from_file(str(ROOT / "app.py")).run()
    assert not app.exception
    assert app.info[0].value == "Upload a CSV to begin."
    assert len(app.dataframe) == 0


def test_valid_upload_then_invalid_replacement_clears_preview():
    # AppTest cannot set the file uploader directly, so substitute its return value.
    app = AppTest.from_file(str(ROOT / "app.py"))
    sample = BytesIO((ROOT / "data" / "sample_shipments.csv").read_bytes())
    with patch("streamlit.file_uploader", return_value=sample):
        app.run()
    assert not app.exception
    assert app.success[0].value == "Validated 9 shipment rows."
    assert len(app.dataframe[0].value) == 9

    with patch("streamlit.file_uploader", return_value=BytesIO(b"wrong_header\nvalue")):
        app.run()
    assert not app.exception
    assert "Validation failed" in app.error[0].value
    assert "Missing columns" in app.text[0].value
    assert len(app.dataframe) == 0

    with patch("streamlit.file_uploader", return_value=None):
        app.run()
    assert not app.exception
    assert len(app.error) == 0
    assert len(app.dataframe) == 0
