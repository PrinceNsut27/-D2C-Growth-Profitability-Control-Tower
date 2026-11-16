"""Unit tests for marketing attribution, CAC, campaign ROAS, and blended MER."""

from __future__ import annotations

import pandas as pd
import pytest

from src.attribution import (
    compute_acquisition_summary,
    compute_campaign_performance,
    compute_channel_acquisition_and_profitability,
)
from src.transformations import build_canonical_model
from tests.test_metrics import _make_hand_calculated_fixture


def test_cac_roas_and_mer_alignment_and_distinction():
    """Verify CAC, Attributed ROAS, and Blended MER keep paid and organic revenue distinct."""
    tables = _make_hand_calculated_fixture()
    # In fixture:
    # O1 (C1, Paid Social, CMP-1, delivered): Net Merchandise Sales = 900.00 (New customer C1)
    # O2 (C2, Direct, unassigned campaign, partially_refunded): Net Merchandise Sales = 500.00 (New customer C2)
    # Total Net Sales = 1400.00; Campaign-attributed Net Sales = 900.00; Unassigned Net Sales = 500.00
    tables["marketing_spend"] = pd.DataFrame(
        [
            {
                "date": "2026-05-05",
                "platform": "Meta Ads",
                "channel": "Paid Social",
                "campaign_id": "CMP-1",
                "spend": 300.00,
                "impressions": 10000,
                "clicks": 200,
                "currency": "INR",
            }
        ]
    )
    model = build_canonical_model(tables)
    summary = compute_acquisition_summary(model.canonical_orders, tables["marketing_spend"])

    assert summary["ad_spend"] == 300.00
    assert summary["total_new_customers"] == 2  # C1 and C2
    assert summary["paid_new_customers"] == 1  # C1
    assert summary["attributed_net_sales"] == 900.00
    assert summary["unassigned_net_sales"] == 500.00
    assert summary["total_net_sales"] == 1400.00

    # Blended CAC = 300 / 2 = 150.00; Paid Channel CAC = 300 / 1 = 300.00
    assert summary["blended_cac"] == 150.00
    assert summary["paid_channel_cac"] == 300.00

    # Attributed ROAS = 900 / 300 = 3.0; Blended MER = 1400 / 300 = 4.6667
    assert summary["attributed_roas"] == 3.0
    assert summary["blended_mer"] == 4.6667


def test_zero_spend_and_zero_new_customers_return_na():
    """Verify zero spend and zero new customers return None (NA) for ROAS, MER, and CAC."""
    tables = _make_hand_calculated_fixture()
    model = build_canonical_model(tables)

    # Zero spend
    empty_spend = pd.DataFrame(
        columns=["date", "platform", "channel", "campaign_id", "spend", "impressions", "clicks", "currency"]
    )
    summary_no_spend = compute_acquisition_summary(model.canonical_orders, empty_spend)
    assert summary_no_spend["attributed_roas"] is None
    assert summary_no_spend["blended_mer"] is None

    # Channel table: Direct has 0 spend -> CAC and Attributed ROAS must be None
    spend_df = pd.DataFrame(
        [
            {
                "date": "2026-05-05",
                "platform": "Meta Ads",
                "channel": "Paid Social",
                "campaign_id": "CMP-1",
                "spend": 300.00,
                "impressions": 10000,
                "clicks": 200,
                "currency": "INR",
            }
        ]
    )
    ch_df = compute_channel_acquisition_and_profitability(model.canonical_orders, spend_df)
    direct_row = ch_df[ch_df["channel"] == "Direct"].iloc[0]
    assert pd.isna(direct_row["cac"])
    assert pd.isna(direct_row["attributed_roas"])

    # Campaign table with unassigned row included
    cmp_df = compute_campaign_performance(model.canonical_orders, spend_df, include_unassigned=True)
    assert len(cmp_df) == 2
