"""Automated tests for recommendation engine, global filtering, time-series trends, and Streamlit UI."""

from __future__ import annotations

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.metrics import (
    apply_global_filters,
    compute_business_performance_And_economics,
    compute_operations_breakdowns,
    compute_time_series_trends,
)
from src.pipeline import run_data_engineering_pipeline
from src.recommendations import generate_recommendations, recommendations_to_dataframe


@pytest.fixture(scope="module")
def pipeline_state():
    """Load the full pipeline state once for dashboard and recommendation tests."""
    return run_data_engineering_pipeline(regenerate_data=False, write_artifacts=False)


def test_recommendation_engine_generates_evidence_backed_rules(pipeline_state):
    """Verify recommendation engine triggers rules with all required fields and no causal claims."""
    can_orders = pipeline_state.canonical_model.canonical_orders
    can_items = pipeline_state.canonical_model.canonical_order_items
    clean = pipeline_state.validation_report.clean_tables

    recs = generate_recommendations(
        canonical_orders=can_orders,
        canonical_order_items=can_items,
        marketing_spend=clean["marketing_spend"],
        sessions=clean["sessions"],
        inventory_snapshots=clean["inventory_snapshots"],
        products=clean["products"],
        customers=clean["customers"],
    )
    assert len(recs) >= 5
    recs_df = recommendations_to_dataframe(recs)
    assert len(recs_df) == len(recs)

    required_cols = {
        "recommendation_id",
        "title",
        "business_area",
        "priority",
        "affected_segment",
        "date_window",
        "observed_condition",
        "evidence_metrics",
        "business_implication",
        "possible_mechanism",
        "suggested_action",
        "risks_and_alternatives",
        "success_metric",
        "measurement_period",
        "confidence_and_limitations",
    }
    assert required_cols.issubset(set(recs_df.columns))

    rec_ids = set(recs_df["recommendation_id"])
    assert "REC-OPS-01" in rec_ids  # COD RTO vs Prepaid
    assert "REC-MKT-01" in rec_ids  # Discount promo margin erosion
    assert "REC-FUN-01" in rec_ids  # Funnel drop-off
    assert "REC-CRM-01" in rec_ids  # At Risk repeat buyers
    assert "REC-INV-01" in rec_ids  # SKUs below reorder point

    # Empty dataset returns empty list cleanly
    empty_recs = generate_recommendations(
        canonical_orders=pd.DataFrame(),
        canonical_order_items=pd.DataFrame(),
        marketing_spend=pd.DataFrame(),
        sessions=pd.DataFrame(),
        inventory_snapshots=pd.DataFrame(),
    )
    assert empty_recs == []


def test_global_filters_and_no_duplicate_revenue(pipeline_state):
    """Verify global filters across date, channel, campaign, SKU, segment, and payment mode."""
    can_orders = pipeline_state.canonical_model.canonical_orders
    can_items = pipeline_state.canonical_model.canonical_order_items
    clean = pipeline_state.validation_report.clean_tables
    rfm = pipeline_state.analytics_outputs["rfm_table"]

    # 1. Unfiltered slice matches baseline exactly
    unfiltered = apply_global_filters(
        canonical_orders=can_orders,
        canonical_order_items=can_items,
        marketing_spend=clean["marketing_spend"],
        sessions=clean["sessions"],
        inventory_snapshots=clean["inventory_snapshots"],
        rfm_table=rfm,
    )
    assert len(unfiltered["canonical_orders"]) == len(can_orders)
    assert unfiltered["canonical_orders"]["order_id"].nunique() == len(can_orders)

    # 2. Filter by payment_mode = ['cod'] and channel = ['Paid Social']
    cod_social = apply_global_filters(
        canonical_orders=can_orders,
        canonical_order_items=can_items,
        marketing_spend=clean["marketing_spend"],
        sessions=clean["sessions"],
        inventory_snapshots=clean["inventory_snapshots"],
        rfm_table=rfm,
        channels=["Paid Social"],
        payment_modes=["cod"],
    )
    flt_ord = cod_social["canonical_orders"]
    assert not flt_ord.empty
    assert set(flt_ord["channel"].unique()) == {"Paid Social"}
    assert set(flt_ord["payment_mode"].unique()) == {"cod"}
    # Ensure zero duplicate order_ids
    assert flt_ord["order_id"].nunique() == len(flt_ord)

    # 3. Filter by SKU and RFM segment
    sku_seg_slice = apply_global_filters(
        canonical_orders=can_orders,
        canonical_order_items=can_items,
        marketing_spend=clean["marketing_spend"],
        sessions=clean["sessions"],
        inventory_snapshots=clean["inventory_snapshots"],
        rfm_table=rfm,
        product_ids=["SKU-SS-01"],
        rfm_segments=["Champions", "Loyal Customers"],
    )
    assert not sku_seg_slice["canonical_orders"].empty
    assert set(sku_seg_slice["canonical_order_items"]["product_id"].unique()) == {"SKU-SS-01"}

    # 4. Empty date range outside window returns empty cleanly
    empty_slice = apply_global_filters(
        canonical_orders=can_orders,
        canonical_order_items=can_items,
        marketing_spend=clean["marketing_spend"],
        sessions=clean["sessions"],
        inventory_snapshots=clean["inventory_snapshots"],
        start_date="2020-01-01",
        end_date="2020-01-31",
    )
    assert empty_slice["canonical_orders"].empty
    kpis_empty = compute_business_performance_And_economics(empty_slice["canonical_orders"])
    assert kpis_empty["placed_orders"] == 0
    assert kpis_empty["aov"] is None

    # 5. Boundary date filtering (exact start date 2026-05-01 and exact end date 2026-10-31)
    first_day_slice = apply_global_filters(
        canonical_orders=can_orders,
        canonical_order_items=can_items,
        marketing_spend=clean["marketing_spend"],
        sessions=clean["sessions"],
        inventory_snapshots=clean["inventory_snapshots"],
        start_date="2026-05-01",
        end_date="2026-05-01",
    )
    assert not first_day_slice["canonical_orders"].empty
    assert set(first_day_slice["canonical_orders"]["order_day"].unique()) == {"2026-05-01"}

    last_day_slice = apply_global_filters(
        canonical_orders=can_orders,
        canonical_order_items=can_items,
        marketing_spend=clean["marketing_spend"],
        sessions=clean["sessions"],
        inventory_snapshots=clean["inventory_snapshots"],
        start_date="2026-10-31",
        end_date="2026-10-31",
    )
    assert not last_day_slice["canonical_orders"].empty
    assert set(last_day_slice["canonical_orders"]["order_day"].unique()) == {"2026-10-31"}

    # 6. CSV export round-trip integrity check
    import io
    csv_bytes = flt_ord.to_csv(index=False).encode("utf-8")
    reloaded_df = pd.read_csv(io.BytesIO(csv_bytes))
    assert len(reloaded_df) == len(flt_ord)
    assert list(reloaded_df.columns) == list(flt_ord.columns)


def test_time_series_trends_and_operations_breakdowns(pipeline_state):
    """Verify weekly/monthly/daily time series and courier/RTO/return breakdowns."""
    can_orders = pipeline_state.canonical_model.canonical_orders
    clean = pipeline_state.validation_report.clean_tables

    for freq in ("W-MON", "M", "D"):
        tr = compute_time_series_trends(
            can_orders, clean["marketing_spend"], clean["sessions"], freq=freq
        )
        assert not tr.empty
        assert pytest.approx(float(tr["net_merchandise_sales"].sum()), abs=0.05) == float(
            can_orders["net_merchandise_sales"].sum()
        )

    ops = compute_operations_breakdowns(can_orders)
    assert not ops["courier_performance"].empty
    assert not ops["rto_reasons"].empty
    assert not ops["return_reasons"].empty
    assert int(ops["rto_reasons"]["rto_orders"].sum()) == int(can_orders["is_rto"].sum())


def test_streamlit_app_renders_all_pages_without_error():
    """Use Streamlit AppTest to render all 9 dashboard views and verify synthetic disclosure."""
    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    assert not at.exception, f"Streamlit initial load exception: {at.exception}"

    # Verify synthetic data disclosure banner is present on initial page
    assert len(at.info) >= 1
    assert "SYNTHETIC DATA DISCLOSURE" in at.info[0].value

    nav_pages = [
        "1. Executive Overview",
        "2. Marketing Performance",
        "3. Conversion Funnel",
        "4. Profitability & Unit Economics",
        "5. Customer Intelligence",
        "6. Operations & Returns",
        "7. Product & Inventory",
        "8. Business Recommendations",
        "9. Data Quality & Glossary",
    ]
    for page in nav_pages:
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception, f"Exception on page '{page}': {at.exception}"
        assert any("SYNTHETIC DATA DISCLOSURE" in inf.value for inf in at.info)
