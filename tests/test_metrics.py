"""Unit tests for business performance, unit economics, funnel, operations, inventory, and SQL reconciliation."""

from __future__ import annotations

import pandas as pd
import pytest

from src.metrics import (
    compute_business_performance_And_economics,
    compute_cod_vs_prepaid_metrics,
    compute_funnel_metrics,
    compute_inventory_and_stockout_metrics,
    compute_sku_profitability,
    reconcile_sql_and_python_metrics,
)
from src.pipeline import run_data_engineering_pipeline
from src.transformations import build_canonical_model


def _make_hand_calculated_fixture() -> dict[str, pd.DataFrame]:
    """Build a small hand-calculated fixture with 4 orders covering delivered, partially_refunded, rto, and cancelled."""
    customers = pd.DataFrame(
        [
            {
                "customer_id": "C1",
                "signup_date": "2026-05-01",
                "first_touch_channel": "Paid Social",
                "first_touch_campaign_id": "CMP-1",
                "city_tier": "Tier 1",
            },
            {
                "customer_id": "C2",
                "signup_date": "2026-05-02",
                "first_touch_channel": "Direct",
                "first_touch_campaign_id": "",
                "city_tier": "Tier 2",
            },
        ]
    )
    products = pd.DataFrame(
        [
            {
                "product_id": "P1",
                "product_name": "Face Wash",
                "category": "Cleanser",
                "unit_cogs": 100.00,
                "list_price": 500.00,
                "launch_date": "2026-01-01",
            }
        ]
    )
    # 4 orders:
    # O1: delivered, prepaid, qty=2, list=500 (GMV=1000), discount=100, shipping_rev=0, tax=162 -> net_sales=900, cogs=200, ship_cost=60, pay_fee=0.02*(900+162)=21.24 -> contrib = 900 - 200 - 60 - 21.24 = 618.76
    # O2: partially_refunded, cod, qty=2, list=500 (GMV=1000), discount=0, refund=500, shipping_rev=0, tax=180 -> net_sales=500, retained_cogs=100, ship_cost=70, pay_fee=25.00 -> contrib = 500 - 100 - 70 - 25 = 305.00
    # O3: rto, cod, qty=1, list=500 (GMV=500), discount=0, shipping_rev=49, tax=90 -> net_sales=0, cogs=0, ship_cost=120, pay_fee=0 -> contrib = -120.00
    # O4: cancelled, prepaid, qty=1, list=500 (GMV=500), discount=0, shipping_rev=49, tax=90 -> net_sales=0, cogs=0, ship_cost=0, pay_fee=0 -> contrib = 0.00
    orders = pd.DataFrame(
        [
            {
                "order_id": "O1",
                "customer_id": "C1",
                "order_date": "2026-05-05 10:00:00",
                "order_status": "delivered",
                "payment_mode": "prepaid",
                "channel": "Paid Social",
                "campaign_id": "CMP-1",
                "currency": "INR",
                "discount_amount": 100.00,
                "shipping_revenue": 0.00,
                "tax_amount": 162.00,
            },
            {
                "order_id": "O2",
                "customer_id": "C2",
                "order_date": "2026-05-06 12:00:00",
                "order_status": "partially_refunded",
                "payment_mode": "cod",
                "channel": "Direct",
                "campaign_id": "",
                "currency": "INR",
                "discount_amount": 0.00,
                "shipping_revenue": 0.00,
                "tax_amount": 180.00,
            },
            {
                "order_id": "O3",
                "customer_id": "C2",
                "order_date": "2026-05-10 15:00:00",
                "order_status": "rto",
                "payment_mode": "cod",
                "channel": "Direct",
                "campaign_id": "",
                "currency": "INR",
                "discount_amount": 0.00,
                "shipping_revenue": 49.00,
                "tax_amount": 90.00,
            },
            {
                "order_id": "O4",
                "customer_id": "C1",
                "order_date": "2026-05-12 09:00:00",
                "order_status": "cancelled",
                "payment_mode": "prepaid",
                "channel": "Paid Social",
                "campaign_id": "CMP-1",
                "currency": "INR",
                "discount_amount": 0.00,
                "shipping_revenue": 49.00,
                "tax_amount": 90.00,
            },
        ]
    )
    order_items = pd.DataFrame(
        [
            {
                "order_item_id": "I1",
                "order_id": "O1",
                "product_id": "P1",
                "quantity": 2,
                "unit_selling_price": 500.00,
                "unit_discount": 50.00,
                "line_refund_amount": 0.00,
            },
            {
                "order_item_id": "I2",
                "order_id": "O2",
                "product_id": "P1",
                "quantity": 2,
                "unit_selling_price": 500.00,
                "unit_discount": 0.00,
                "line_refund_amount": 500.00,
            },
            {
                "order_item_id": "I3",
                "order_id": "O3",
                "product_id": "P1",
                "quantity": 1,
                "unit_selling_price": 500.00,
                "unit_discount": 0.00,
                "line_refund_amount": 0.00,
            },
            {
                "order_item_id": "I4",
                "order_id": "O4",
                "product_id": "P1",
                "quantity": 1,
                "unit_selling_price": 500.00,
                "unit_discount": 0.00,
                "line_refund_amount": 0.00,
            },
        ]
    )
    shipments = pd.DataFrame(
        [
            {
                "shipment_id": "S1",
                "order_id": "O1",
                "shipped_at": "2026-05-05 18:00:00",
                "delivered_at": "2026-05-08 14:00:00",
                "shipment_status": "delivered",
                "shipping_cost": 60.00,
                "courier_partner": "Delhivery",
                "rto_reason": "",
            },
            {
                "shipment_id": "S2",
                "order_id": "O2",
                "shipped_at": "2026-05-06 19:00:00",
                "delivered_at": "2026-05-09 11:00:00",
                "shipment_status": "delivered",
                "shipping_cost": 70.00,
                "courier_partner": "BlueDart",
                "rto_reason": "",
            },
            {
                "shipment_id": "S3",
                "order_id": "O3",
                "shipped_at": "2026-05-10 20:00:00",
                "delivered_at": "",
                "shipment_status": "rto",
                "shipping_cost": 120.00,
                "courier_partner": "Ecom Express",
                "rto_reason": "Customer Refused Delivery",
            },
        ]
    )
    returns = pd.DataFrame(
        [
            {
                "return_id": "R1",
                "order_id": "O2",
                "order_item_id": "I2",
                "return_requested_at": "2026-05-11 10:00:00",
                "return_reason": "Damaged",
                "refund_amount": 500.00,
                "return_status": "refunded",
            }
        ]
    )
    sessions = pd.DataFrame()
    marketing_spend = pd.DataFrame()
    inventory_snapshots = pd.DataFrame()

    return {
        "customers": customers,
        "products": products,
        "orders": orders,
        "order_items": order_items,
        "sessions": sessions,
        "marketing_spend": marketing_spend,
        "shipments": shipments,
        "returns": returns,
        "inventory_snapshots": inventory_snapshots,
    }


def test_hand_calculated_business_performance_and_contribution():
    """Verify exact hand-calculated results for orders, AOV, RTO rate, return rate, and contribution."""
    tables = _make_hand_calculated_fixture()
    model = build_canonical_model(tables, prepaid_fee_rate=0.02, cod_fee_fixed=25.0)
    kpis = compute_business_performance_And_economics(model.canonical_orders)

    assert kpis["placed_orders"] == 4
    assert kpis["shipped_orders"] == 3  # O1, O2, O3
    assert kpis["delivered_orders"] == 2  # O1, O2
    assert kpis["cancelled_orders"] == 1  # O4
    assert kpis["rto_orders"] == 1  # O3
    assert kpis["returned_orders"] == 1  # O2 (partially_refunded)

    # Financials:
    # Delivered GMV = 1000 (O1) + 1000 (O2) = 2000.00
    # Delivered Discounts = 100.00
    # Refunds = 500.00
    # Net Merchandise Sales = 2000 - 100 - 500 = 1400.00
    # AOV = 1400.00 / 2 = 700.00
    assert kpis["delivered_gross_revenue"] == 2000.00
    assert kpis["delivered_discounts"] == 100.00
    assert kpis["refund_amount"] == 500.00
    assert kpis["net_merchandise_sales"] == 1400.00
    assert kpis["aov"] == 700.00

    # Variable Costs & Contribution:
    # Net COGS = 200 (O1) + 100 (O2 retained half) = 300.00
    # Gross Profit = 1400 - 300 = 1100.00
    # Shipping Cost = 60 (O1) + 70 (O2) + 120 (O3 RTO) = 250.00
    # Payment Fees = 21.24 (O1) + 25.00 (O2 COD) = 46.24
    # Contribution Profit = 1100.00 - 250.00 - 46.24 = 803.76
    assert kpis["net_cogs"] == 300.00
    assert kpis["gross_profit"] == 1100.00
    assert kpis["shipping_cost"] == 250.00
    assert kpis["rto_shipping_cost"] == 120.00
    assert kpis["payment_fees"] == 46.24
    assert kpis["contribution_profit"] == pytest.approx(803.76, abs=0.01)

    # Rates:
    # Cancellation rate = 1 / 4 = 0.25
    # RTO rate = 1 / 3 = 0.3333 (divided by shipped_orders = 3, NOT placed_orders = 4!)
    # Return rate = 1 / 2 = 0.50 (divided by delivered_orders = 2)
    assert kpis["cancellation_rate"] == 0.25
    assert kpis["rto_rate"] == 0.3333
    assert kpis["return_rate"] == 0.50


def test_zero_denominator_and_empty_dataset_edge_cases():
    """Verify empty datasets and zero-revenue orders return None (NA) for ratios, never 0.0."""
    empty_df = pd.DataFrame()
    kpis = compute_business_performance_And_economics(empty_df)
    assert kpis["placed_orders"] == 0
    assert kpis["aov"] is None
    assert kpis["rto_rate"] is None
    assert kpis["return_rate"] is None
    assert kpis["contribution_margin_pct"] is None

    # Funnel with empty sessions
    f_df = compute_funnel_metrics(empty_df)
    assert f_df.iloc[0]["sessions"] == 0
    assert f_df.iloc[0]["session_conversion_rate"] is None
    assert f_df.iloc[0]["checkout_completion_rate"] is None


def test_funnel_stage_rates_and_dropoffs():
    """Verify funnel stage-to-stage rates and drop-off calculations on a hand-crafted session table."""
    sessions = pd.DataFrame(
        [
            {"session_id": "S1", "channel": "Paid Social", "device": "mobile", "product_view": True, "add_to_cart": True, "checkout_started": True, "converted": True},
            {"session_id": "S2", "channel": "Paid Social", "device": "mobile", "product_view": True, "add_to_cart": True, "checkout_started": False, "converted": False},
            {"session_id": "S3", "channel": "Paid Social", "device": "mobile", "product_view": True, "add_to_cart": False, "checkout_started": False, "converted": False},
            {"session_id": "S4", "channel": "Paid Social", "device": "mobile", "product_view": False, "add_to_cart": False, "checkout_started": False, "converted": False},
        ]
    )
    res = compute_funnel_metrics(sessions).iloc[0]
    assert res["sessions"] == 4
    assert res["product_views"] == 3
    assert res["add_to_carts"] == 2
    assert res["checkout_started"] == 1
    assert res["purchases"] == 1
    assert res["session_to_view_rate"] == 0.75
    assert res["add_to_cart_rate"] == 0.50
    assert res["cart_to_checkout_rate"] == 0.50
    assert res["checkout_completion_rate"] == 1.0
    assert res["session_conversion_rate"] == 0.25
    assert res["dropoff_cart_to_checkout"] == 0.50


def test_inventory_sell_through_and_stockout_signals():
    """Verify sell-through denominator and stockout/reorder point signals."""
    inv = pd.DataFrame(
        [
            {"snapshot_date": "2026-05-01", "product_id": "P1", "opening_stock": 100, "units_received": 50, "units_sold": 120, "closing_stock": 30, "reorder_point": 40},
            {"snapshot_date": "2026-05-02", "product_id": "P1", "opening_stock": 30, "units_received": 0, "units_sold": 30, "closing_stock": 0, "reorder_point": 40},
        ]
    )
    res = compute_inventory_and_stockout_metrics(inv).iloc[0]
    # Total sold = 150, Initial opening (100) + total received (50) = 150 -> sell-through = 1.0
    assert res["sell_through_rate"] == 1.0
    assert res["days_below_reorder_point"] == 2
    assert res["stockout_days"] == 1
    assert res["latest_status"] == "STOCKOUT_SIGNAL"


def test_sql_and_python_full_reconciliation():
    """Verify that all 23 SQL and Python KPIs reconcile within 0.01 tolerance on the DuckDB database."""
    pipe_res = run_data_engineering_pipeline(regenerate_data=False)
    rec = reconcile_sql_and_python_metrics(
        db_path=str(pipe_res.duckdb_path),
        canonical_orders=pipe_res.canonical_model.canonical_orders,
        marketing_spend=pipe_res.canonical_model.raw_tables["marketing_spend"],
        sessions=pipe_res.canonical_model.raw_tables["sessions"],
        tolerance=0.01,
    )
    assert rec["reconciled"] is True, f"Mismatched metrics:\n{rec['comparisons'][~rec['comparisons']['reconciled']]}"
