"""Unit tests for RFM customer segmentation, repeat-purchase rate, and monthly cohort retention."""

from __future__ import annotations

import pandas as pd
import pytest

from src.cohorts import compute_monthly_cohort_retention
from src.segmentation import (
    compute_repeat_purchase_and_ltv_summary,
    compute_rfm_table,
    summarize_rfm_segments,
)


def _make_cohort_fixture() -> pd.DataFrame:
    """Create a canonical_orders fixture with 3 customers across May and June 2026."""
    return pd.DataFrame(
        [
            # C1: acquired in 2026-05, repeats in 2026-06
            {
                "order_id": "O1",
                "customer_id": "C1",
                "order_day": "2026-05-10",
                "order_month": "2026-05",
                "city_tier": "Tier 1",
                "first_touch_channel": "Paid Social",
                "is_delivered": True,
                "net_merchandise_sales": 600.0,
                "contribution_profit": 250.0,
            },
            {
                "order_id": "O2",
                "customer_id": "C1",
                "order_day": "2026-06-12",
                "order_month": "2026-06",
                "city_tier": "Tier 1",
                "first_touch_channel": "Paid Social",
                "is_delivered": True,
                "net_merchandise_sales": 800.0,
                "contribution_profit": 360.0,
            },
            # C2: acquired in 2026-05, never repeats
            {
                "order_id": "O3",
                "customer_id": "C2",
                "order_day": "2026-05-18",
                "order_month": "2026-05",
                "city_tier": "Tier 2",
                "first_touch_channel": "Organic Search",
                "is_delivered": True,
                "net_merchandise_sales": 450.0,
                "contribution_profit": 180.0,
            },
            # C3: acquired in 2026-06, no repeat in later month
            {
                "order_id": "O4",
                "customer_id": "C3",
                "order_day": "2026-06-20",
                "order_month": "2026-06",
                "city_tier": "Tier 3",
                "first_touch_channel": "Direct",
                "is_delivered": True,
                "net_merchandise_sales": 500.0,
                "contribution_profit": 200.0,
            },
        ]
    )


def test_rfm_and_repeat_purchase_summary():
    """Verify RFM recency, frequency, monetary calculations and repeat purchase rate."""
    can_orders = _make_cohort_fixture()
    rfm = compute_rfm_table(can_orders, snapshot_date="2026-06-30")

    assert len(rfm) == 3
    c1_row = rfm[rfm["customer_id"] == "C1"].iloc[0]
    assert c1_row["frequency"] == 2
    assert c1_row["monetary"] == 1400.0
    assert c1_row["recency_days"] == 18  # 2026-06-30 minus 2026-06-12
    assert c1_row["customer_type"] == "Repeat Customer"

    seg_summary = summarize_rfm_segments(rfm)
    assert seg_summary["customers"].sum() == 3
    assert pytest.approx(float(seg_summary["total_net_sales"].sum()), abs=0.01) == 2350.0

    ltv = compute_repeat_purchase_and_ltv_summary(can_orders)
    assert ltv["active_delivered_customers"] == 3
    assert ltv["repeat_customers"] == 1
    assert ltv["first_time_customers"] == 2
    assert ltv["repeat_purchase_rate"] == 0.3333
    assert ltv["total_net_sales"] == 2350.0


def test_monthly_cohort_retention_matrix():
    """Verify Month 0 and Month +1 cohort retention rates."""
    can_orders = _make_cohort_fixture()
    cohorts = compute_monthly_cohort_retention(can_orders)
    ret_mat = cohorts["retention_matrix"]

    # 2026-05 cohort has 2 customers (C1, C2); 1 (C1) returns in 2026-06 (period 1) -> 50% retention
    assert ret_mat.loc["2026-05", 0] == 1.0
    assert ret_mat.loc["2026-05", 1] == 0.50

    # 2026-06 cohort has 1 customer (C3) at period 0 -> 100% at period 0
    assert ret_mat.loc["2026-06", 0] == 1.0
