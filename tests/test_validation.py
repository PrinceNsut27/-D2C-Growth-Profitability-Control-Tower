"""Unit tests for data generation, ingestion, and validation rules."""

from __future__ import annotations

import pandas as pd
import pytest

from src.generate_data import generate_all_datasets
from src.ingestion import EXPECTED_COLUMNS, REQUIRED_TABLES
from src.validation import validate_all_tables


@pytest.fixture(scope="module")
def sample_generated_dataset():
    """Generate a small deterministic synthetic dataset for fast test execution."""
    return generate_all_datasets(
        seed=42,
        start_date="2026-05-01",
        end_date="2026-06-15",
        num_customers=120,
        num_orders=250,
        num_sessions=1200,
        currency="INR",
    )


def test_deterministic_reproducibility():
    """Verify fixed random seed produces bit-for-bit identical tables."""
    ds1 = generate_all_datasets(
        seed=99,
        start_date="2026-05-01",
        end_date="2026-05-31",
        num_customers=60,
        num_orders=100,
        num_sessions=500,
    )
    ds2 = generate_all_datasets(
        seed=99,
        start_date="2026-05-01",
        end_date="2026-05-31",
        num_customers=60,
        num_orders=100,
        num_sessions=500,
    )

    for tbl in REQUIRED_TABLES:
        pd.testing.assert_frame_equal(ds1.to_dict()[tbl], ds2.to_dict()[tbl])


def test_generated_schema_and_clean_validation(sample_generated_dataset):
    """Verify all 9 generated tables match expected schemas and pass all validation checks."""
    tables = sample_generated_dataset.to_dict()
    assert set(tables.keys()) == set(REQUIRED_TABLES)

    for tbl, expected_cols in EXPECTED_COLUMNS.items():
        assert list(tables[tbl].columns) == expected_cols, f"Schema mismatch on {tbl}"
        assert len(tables[tbl]) > 0, f"Table {tbl} should not be empty"

    report = validate_all_tables(tables, expected_currency="INR")
    assert report.passed is True
    assert len(report.rejected_rows) == 0


def test_validation_catches_duplicate_primary_keys(sample_generated_dataset):
    """Verify duplicate primary keys are flagged and recorded in rejected_rows."""
    tables = {k: v.copy() for k, v in sample_generated_dataset.to_dict().items()}
    dup_row = tables["customers"].iloc[[0]].copy()
    tables["customers"] = pd.concat([tables["customers"], dup_row], ignore_index=True)

    report = validate_all_tables(tables)
    assert report.passed is False
    pk_checks = [
        c for c in report.checks if c.table_name == "customers" and c.check_name == "primary_key_uniqueness"
    ]
    assert len(pk_checks) == 1
    assert pk_checks[0].passed is False
    assert pk_checks[0].failed_count == 1
    assert len(report.rejected_rows) == 1
    assert "Duplicate primary key" in report.rejected_rows.iloc[0]["reason"]


def test_validation_catches_missing_mandatory_columns(sample_generated_dataset):
    """Verify missing required schema columns fail validation immediately."""
    tables = {k: v.copy() for k, v in sample_generated_dataset.to_dict().items()}
    tables["orders"] = tables["orders"].drop(columns=["payment_mode"])

    report = validate_all_tables(tables)
    assert report.passed is False
    schema_checks = [
        c for c in report.checks if c.table_name == "orders" and c.check_name == "schema_columns"
    ]
    assert schema_checks[0].passed is False


def test_validation_catches_negative_values_and_invalid_currency(sample_generated_dataset):
    """Verify negative spend, negative quantity, and invalid currency are caught and reported."""
    tables = {k: v.copy() for k, v in sample_generated_dataset.to_dict().items()}
    tables["marketing_spend"].loc[0, "spend"] = -150.0
    tables["marketing_spend"].loc[1, "currency"] = "USD"
    tables["order_items"].loc[0, "quantity"] = 0

    report = validate_all_tables(tables)
    assert report.passed is False
    assert len(report.rejected_rows) >= 3
    reasons = " | ".join(report.rejected_rows["reason"].tolist())
    assert "Negative or non-numeric" in reasons
    assert "Unsupported currency" in reasons


def test_validation_catches_invalid_dates_and_foreign_keys(sample_generated_dataset):
    """Verify invalid dates and orphan foreign keys are caught and reported."""
    tables = {k: v.copy() for k, v in sample_generated_dataset.to_dict().items()}
    tables["orders"].loc[0, "customer_id"] = "CUST-NONEXISTENT-999"
    tables["shipments"].loc[0, "shipped_at"] = "not-a-valid-timestamp"

    report = validate_all_tables(tables)
    assert report.passed is False
    reasons = " | ".join(report.rejected_rows["reason"].tolist())
    assert "Unknown foreign key customer_id -> customers.customer_id" in reasons
    assert "Invalid date/timestamp format" in reasons


def test_validation_catches_impossible_lifecycle_and_discount_mismatch(sample_generated_dataset):
    """Verify impossible order status transitions and header-vs-line discount mismatch fail validation."""
    tables = {k: v.copy() for k, v in sample_generated_dataset.to_dict().items()}
    # Force first delivered order to be labelled 'cancelled' while keeping its delivered shipment
    delivered_ord_idx = tables["orders"].index[tables["orders"]["order_status"] == "delivered"][0]
    tables["orders"].loc[delivered_ord_idx, "order_status"] = "cancelled"
    # Corrupt discount_amount on second order so it mismatches line item discounts
    tables["orders"].loc[1, "discount_amount"] = 99999.00

    report = validate_all_tables(tables)
    assert report.passed is False
    reasons = " | ".join(report.rejected_rows["reason"].tolist())
    assert "Inconsistent order lifecycle transition" in reasons
    assert "Order header discount_amount does not reconcile" in reasons


def test_validation_catches_bad_inventory_arithmetic_and_funnel_sequence(sample_generated_dataset):
    """Verify impossible stock arithmetic and out-of-sequence funnel flags are caught."""
    tables = {k: v.copy() for k, v in sample_generated_dataset.to_dict().items()}
    tables["inventory_snapshots"].loc[0, "closing_stock"] = 999999
    tables["sessions"].loc[0, "product_view"] = False
    tables["sessions"].loc[0, "add_to_cart"] = True

    report = validate_all_tables(tables)
    assert report.passed is False
    reasons = " | ".join(report.rejected_rows["reason"].tolist())
    assert "Impossible stock arithmetic" in reasons
    assert "Inconsistent session funnel sequence" in reasons
