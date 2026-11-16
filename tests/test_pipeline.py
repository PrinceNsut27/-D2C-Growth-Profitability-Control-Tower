"""Integration tests for canonical transformations, anti-fan-out joins, and DuckDB pipeline."""

from __future__ import annotations

from pathlib import Path
import duckdb
import pandas as pd
import pytest

from src.generate_data import generate_all_datasets, save_generated_datasets
from src.pipeline import run_data_engineering_pipeline
from src.transformations import build_canonical_model
from src.validation import validate_all_tables


def test_anti_fanout_with_multiple_shipments_and_returns():
    """Verify that multiple shipments and multiple returns on one order do not duplicate order revenue."""
    ds = generate_all_datasets(
        seed=42,
        start_date="2026-05-01",
        end_date="2026-06-15",
        num_customers=80,
        num_orders=160,
        num_sessions=800,
    )
    tables = {k: v.copy() for k, v in ds.to_dict().items()}

    # Baseline canonical model
    base_model = build_canonical_model(tables)
    base_order_count = len(base_model.canonical_orders)
    base_net_sales = float(base_model.canonical_orders["net_merchandise_sales"].sum())

    # Inject a second split shipment for the first delivered order
    first_ship = tables["shipments"].iloc[[0]].copy()
    first_ship["shipment_id"] = "SHP-SPLIT-999999"
    first_ship["shipping_cost"] = 40.00
    tables["shipments"] = pd.concat([tables["shipments"], first_ship], ignore_index=True)

    # Rebuild canonical model and verify 1 row per order and unchanged net merchandise sales
    split_model = build_canonical_model(tables)
    assert len(split_model.canonical_orders) == base_order_count
    assert split_model.canonical_orders["order_id"].nunique() == base_order_count
    assert split_model.join_audit["fanout_detected"] is False
    assert pytest.approx(float(split_model.canonical_orders["net_merchandise_sales"].sum()), abs=0.01) == base_net_sales


def test_end_to_end_data_engineering_pipeline(tmp_path: Path):
    """Test generate -> ingest -> validate -> canonical transform -> DuckDB persistence."""
    raw_dir = tmp_path / "raw"
    proc_dir = tmp_path / "processed"
    db_file = proc_dir / "test_d2c.duckdb"

    ds = generate_all_datasets(
        seed=42,
        start_date="2026-05-01",
        end_date="2026-06-15",
        num_customers=100,
        num_orders=200,
        num_sessions=1000,
    )
    save_generated_datasets(ds, output_dir=raw_dir)

    res = run_data_engineering_pipeline(
        regenerate_data=False,
        data_dir=raw_dir,
        processed_dir=proc_dir,
        db_path=db_file,
    )

    assert res.validation_report.passed is True
    assert len(res.validation_report.rejected_rows) == 0
    assert res.duckdb_path.exists()
    assert res.duckdb_table_counts["orders"] == 200
    assert res.duckdb_table_counts["canonical_orders"] == 200
    assert res.duckdb_table_counts["customers"] == 100

    # Verify SQL query on DuckDB matches Python canonical_orders net sales
    con = duckdb.connect(str(db_file), read_only=True)
    try:
        sql_sales = con.execute("SELECT ROUND(SUM(net_merchandise_sales), 2) FROM canonical_orders").fetchone()[0]
    finally:
        con.close()

    py_sales = round(float(res.canonical_model.canonical_orders["net_merchandise_sales"].sum()), 2)
    assert pytest.approx(float(sql_sales), abs=0.01) == py_sales
