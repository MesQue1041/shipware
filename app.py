"""Stage 1: upload, validate, and preview shipment data."""

import streamlit as st

from shipware.validation import COLUMNS, validate_csv


def main() -> None:
    """Display an upload form and show data only after the full file is valid."""
    st.set_page_config(page_title="Shipware", page_icon="📦")
    st.title("Shipware")
    st.write("Upload a shipment CSV to validate and preview it. Use synthetic data only.")
    st.caption("Stage 1 · CSV validation · No API key needed")

    with st.expander("CSV format and sample data"):
        st.write("Choose data/sample_shipments.csv from this repository to try the demo.")
        st.code(",".join(COLUMNS), language="text")
        st.write(
            "Use UTF-8 and exactly these six columns. Limit: 5 MiB and 10,000 shipment rows. "
            "All values except tracking_number are required. Shipment IDs must be unique. "
            "Statuses: pending, in_transit, delivered, cancelled. "
            "Dates: YYYY-MM-DD. Updates: ISO 8601 with Z or a numeric timezone offset."
        )
        st.caption("Surrounding whitespace is trimmed, statuses are lowercased, and updates are converted to UTC.")

    uploaded_file = st.file_uploader("Shipment CSV", type=["csv"])
    if uploaded_file is None:
        st.info("Upload a CSV to begin.")
        return

    # No cache or disk write: this upload is used only for the current preview.
    shipments, errors = validate_csv(uploaded_file.getvalue())
    if errors:
        st.error("Validation failed. Correct the issues below and upload the file again. No rows were processed.")
        # Plain text prevents uploaded header names from becoming Markdown or HTML.
        st.text("\n".join(errors))
        st.caption("Row numbers count CSV records, with the header as row 1, even when a quoted value contains newlines.")
        return

    st.success(f"Validated {len(shipments):,} shipment rows.")
    st.subheader("Normalized shipment preview")
    st.caption("last_update_at is shown in UTC. Blank tracking numbers are allowed.")
    st.dataframe(shipments, hide_index=True, width="stretch")


if __name__ == "__main__":
    main()
