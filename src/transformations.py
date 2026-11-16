"""Canonical data model transformations and DuckDB persistence layer.

Prevents many-to-many join fan-out by aggregating order_items, shipments, and
returns to the order_id grain before joining to the orders header table.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import duckdb
import numpy as np
import pandas as pd

from src.config import PROJECT_ROOT, load_settings

SHIPPED_STATUSES = {"shipped", "delivered", "rto", "returned", "partially_refunded"}
DELIVERED_COHORT_STATUSES = {"delivered", "returned", "partially_refunded"}
RETAINED_DELIVERED_STATUSES = {"delivered", "partially_refunded"}


@dataclass
class CanonicalModel:
    """Container for validated raw tables and fan-out-free canonical tables."""

    raw_tables: dict[str, pd.DataFrame]
    canonical_orders: pd.DataFrame
    canonical_order_items: pd.DataFrame
    join_audit: dict[str, Any]


def aggregate_order_items_to_order_grain(
    order_items: pd.DataFrame,
    products: pd.DataFrame,
) -> pd.DataFrame:
    """Pre-aggregate order_items + product unit_cogs to 1 row per order_id."""
    if order_items.empty:
        return pd.DataFrame(
            columns=[
                "order_id",
                "sku_count",
                "total_units",
                "gross_item_revenue",
                "item_discount_amount",
                "line_refund_amount",
                "net_item_value_before_refund",
                "gross_product_cogs",
                "retained_product_cogs",
            ]
        )

    items = order_items.copy()
    prods = products[["product_id", "unit_cogs", "category", "product_name"]].copy()
    items["order_id"] = items["order_id"].astype(str)
    items["product_id"] = items["product_id"].astype(str)
    prods["product_id"] = prods["product_id"].astype(str)

    items = items.merge(prods, on="product_id", how="left")
    items["quantity"] = pd.to_numeric(items["quantity"], errors="coerce").fillna(0).astype(int)
    items["unit_selling_price"] = pd.to_numeric(items["unit_selling_price"], errors="coerce").fillna(0.0)
    items["unit_discount"] = pd.to_numeric(items["unit_discount"], errors="coerce").fillna(0.0)
    items["line_refund_amount"] = pd.to_numeric(items["line_refund_amount"], errors="coerce").fillna(0.0)
    items["unit_cogs"] = pd.to_numeric(items["unit_cogs"], errors="coerce").fillna(0.0)

    items["gross_line_revenue"] = (items["quantity"] * items["unit_selling_price"]).round(2)
    items["line_discount_total"] = (items["quantity"] * items["unit_discount"]).round(2)
    items["net_line_before_refund"] = (items["gross_line_revenue"] - items["line_discount_total"]).round(2)
    items["gross_line_cogs"] = (items["quantity"] * items["unit_cogs"]).round(2)

    # Retained fraction of line item after refund
    retained_ratio = np.where(
        items["net_line_before_refund"] > 0,
        np.clip(1.0 - (items["line_refund_amount"] / items["net_line_before_refund"]), 0.0, 1.0),
        0.0,
    )
    items["retained_line_cogs"] = (items["gross_line_cogs"] * retained_ratio).round(2)

    agg = (
        items.groupby("order_id", as_index=False)
        .agg(
            sku_count=("product_id", "nunique"),
            total_units=("quantity", "sum"),
            gross_item_revenue=("gross_line_revenue", "sum"),
            item_discount_amount=("line_discount_total", "sum"),
            line_refund_amount=("line_refund_amount", "sum"),
            net_item_value_before_refund=("net_line_before_refund", "sum"),
            gross_product_cogs=("gross_line_cogs", "sum"),
            retained_product_cogs=("retained_line_cogs", "sum"),
        )
    )
    for col in (
        "gross_item_revenue",
        "item_discount_amount",
        "line_refund_amount",
        "net_item_value_before_refund",
        "gross_product_cogs",
        "retained_product_cogs",
    ):
        agg[col] = agg[col].round(2)
    return agg


def aggregate_shipments_to_order_grain(shipments: pd.DataFrame) -> pd.DataFrame:
    """Pre-aggregate shipments to 1 row per order_id to prevent multi-shipment fan-out."""
    if shipments.empty:
        return pd.DataFrame(
            columns=[
                "order_id",
                "shipment_count",
                "shipping_cost",
                "shipped_at",
                "delivered_at",
                "shipment_status",
                "courier_partner",
                "rto_reason",
            ]
        )

    shp = shipments.copy()
    shp["order_id"] = shp["order_id"].astype(str)
    shp["shipping_cost"] = pd.to_numeric(shp["shipping_cost"], errors="coerce").fillna(0.0)
    shp["delivered_at"] = shp["delivered_at"].fillna("").astype(str)
    shp["rto_reason"] = shp["rto_reason"].fillna("").astype(str)
    shp = shp.sort_values(["order_id", "shipped_at"])

    agg = (
        shp.groupby("order_id", as_index=False)
        .agg(
            shipment_count=("shipment_id", "count"),
            shipping_cost=("shipping_cost", "sum"),
            shipped_at=("shipped_at", "min"),
            delivered_at=("delivered_at", "max"),
            shipment_status=("shipment_status", "last"),
            courier_partner=("courier_partner", "first"),
            rto_reason=("rto_reason", "last"),
        )
    )
    agg["shipping_cost"] = agg["shipping_cost"].round(2)
    return agg


def aggregate_returns_to_order_grain(returns: pd.DataFrame) -> pd.DataFrame:
    """Pre-aggregate returns to 1 row per order_id to prevent multi-return fan-out."""
    if returns.empty:
        return pd.DataFrame(
            columns=[
                "order_id",
                "return_count",
                "return_refund_amount",
                "return_requested_at",
                "return_reason",
                "return_status",
            ]
        )

    ret = returns.copy()
    ret["order_id"] = ret["order_id"].astype(str)
    ret["refund_amount"] = pd.to_numeric(ret["refund_amount"], errors="coerce").fillna(0.0)
    ret = ret.sort_values(["order_id", "return_requested_at"])

    agg = (
        ret.groupby("order_id", as_index=False)
        .agg(
            return_count=("return_id", "count"),
            return_refund_amount=("refund_amount", "sum"),
            return_requested_at=("return_requested_at", "min"),
            return_reason=("return_reason", "first"),
            return_status=("return_status", "last"),
        )
    )
    agg["return_refund_amount"] = agg["return_refund_amount"].round(2)
    return agg


def build_canonical_model(
    clean_tables: dict[str, pd.DataFrame],
    prepaid_fee_rate: float = 0.02,
    cod_fee_fixed: float = 25.0,
) -> CanonicalModel:
    """Build fan-out-free canonical_orders and canonical_order_items tables."""
    orders = clean_tables["orders"].copy()
    customers = clean_tables["customers"].copy()
    products = clean_tables["products"].copy()
    order_items = clean_tables["order_items"].copy()
    shipments = clean_tables["shipments"].copy()
    returns = clean_tables["returns"].copy()

    items_agg = aggregate_order_items_to_order_grain(order_items, products)
    shipments_agg = aggregate_shipments_to_order_grain(shipments)
    returns_agg = aggregate_returns_to_order_grain(returns)

    if orders.empty:
        empty_orders = pd.DataFrame(
            columns=[
                "order_id",
                "customer_id",
                "order_date",
                "order_day",
                "order_month",
                "order_status",
                "payment_mode",
                "channel",
                "campaign_id",
                "currency",
                "discount_amount",
                "shipping_revenue",
                "tax_amount",
                "signup_date",
                "first_touch_channel",
                "first_touch_campaign_id",
                "city_tier",
                "sku_count",
                "total_units",
                "gross_item_revenue",
                "item_discount_amount",
                "line_refund_amount",
                "return_refund_amount",
                "effective_refund_amount",
                "is_shipped",
                "is_delivered",
                "is_retained_delivered",
                "is_rto",
                "is_cancelled",
                "is_returned_any",
                "net_merchandise_sales",
                "earned_shipping_revenue",
                "net_cogs",
                "shipping_cost",
                "payment_fee",
                "contribution_profit",
                "customer_delivered_seq",
                "is_new_customer_order",
                "first_delivered_date",
                "cohort_month",
            ]
        )
        return CanonicalModel(
            raw_tables=clean_tables,
            canonical_orders=empty_orders,
            canonical_order_items=pd.DataFrame(),
            join_audit={"orders_input": 0, "canonical_orders_output": 0, "fanout_detected": False},
        )

    orders["order_id"] = orders["order_id"].astype(str)
    orders["customer_id"] = orders["customer_id"].astype(str)
    customers["customer_id"] = customers["customer_id"].astype(str)

    # Merge 1:1 pre-aggregated facts onto orders
    can = (
        orders.merge(
            customers[
                ["customer_id", "signup_date", "first_touch_channel", "first_touch_campaign_id", "city_tier"]
            ],
            on="customer_id",
            how="left",
        )
        .merge(items_agg, on="order_id", how="left")
        .merge(shipments_agg, on="order_id", how="left")
        .merge(returns_agg, on="order_id", how="left")
    )

    # Fill numeric defaults for orders without shipments or returns
    for num_col in (
        "sku_count",
        "total_units",
        "shipment_count",
        "return_count",
    ):
        can[num_col] = pd.to_numeric(can[num_col], errors="coerce").fillna(0).astype(int)

    for flt_col in (
        "discount_amount",
        "shipping_revenue",
        "tax_amount",
        "gross_item_revenue",
        "item_discount_amount",
        "line_refund_amount",
        "net_item_value_before_refund",
        "gross_product_cogs",
        "retained_product_cogs",
        "shipping_cost",
        "return_refund_amount",
    ):
        can[flt_col] = pd.to_numeric(can[flt_col], errors="coerce").fillna(0.0).round(2)

    for str_col in (
        "campaign_id",
        "first_touch_campaign_id",
        "shipped_at",
        "delivered_at",
        "shipment_status",
        "courier_partner",
        "rto_reason",
        "return_requested_at",
        "return_reason",
        "return_status",
    ):
        if str_col in can.columns:
            can[str_col] = can[str_col].fillna("").astype(str)

    # Parse dates
    order_ts = pd.to_datetime(can["order_date"])
    can["order_day"] = order_ts.dt.strftime("%Y-%m-%d")
    can["order_month"] = order_ts.dt.strftime("%Y-%m")

    # Lifecycle flags
    status_s = can["order_status"].astype(str)
    can["is_shipped"] = status_s.isin(SHIPPED_STATUSES)
    can["is_delivered"] = status_s.isin(DELIVERED_COHORT_STATUSES)
    can["is_retained_delivered"] = status_s.isin(RETAINED_DELIVERED_STATUSES)
    can["is_rto"] = status_s == "rto"
    can["is_cancelled"] = status_s == "cancelled"
    can["is_returned_any"] = status_s.isin({"returned", "partially_refunded"})

    # Reconciled refund amount (matches line_refund_amount / return_refund_amount)
    can["effective_refund_amount"] = np.where(
        can["is_returned_any"],
        np.maximum(can["line_refund_amount"], can["return_refund_amount"]),
        0.0,
    ).round(2)

    # Net Merchandise Sales: (GMV - Discount - Refund) for delivered cohort orders; 0 for cancelled/RTO/pre-delivery
    can["net_merchandise_sales"] = np.where(
        can["is_delivered"],
        np.maximum(0.0, can["gross_item_revenue"] - can["discount_amount"] - can["effective_refund_amount"]),
        0.0,
    ).round(2)

    # Earned shipping revenue on retained delivered orders
    can["earned_shipping_revenue"] = np.where(
        can["is_retained_delivered"],
        can["shipping_revenue"],
        0.0,
    ).round(2)

    # Net COGS incurred on retained delivered items
    can["net_cogs"] = np.where(
        can["is_delivered"],
        can["retained_product_cogs"],
        0.0,
    ).round(2)

    # Payment gateway / COD collection fee
    order_collected_base = (
        can["gross_item_revenue"] - can["discount_amount"] + can["shipping_revenue"] + can["tax_amount"]
    )
    can["payment_fee"] = np.where(
        (can["payment_mode"] == "prepaid") & (~can["is_cancelled"]),
        (order_collected_base * prepaid_fee_rate).round(2),
        np.where(
            (can["payment_mode"] == "cod") & can["is_delivered"],
            cod_fee_fixed,
            0.0,
        ),
    ).round(2)

    # Contribution profit = Net Merchandise Sales + Earned Shipping Revenue - Net COGS - Shipping Cost - Payment Fee
    can["contribution_profit"] = (
        can["net_merchandise_sales"]
        + can["earned_shipping_revenue"]
        - can["net_cogs"]
        - can["shipping_cost"]
        - can["payment_fee"]
    ).round(2)

    # Compute customer delivered order sequence & first delivered purchase cohort
    can = can.sort_values(["order_date", "order_id"]).reset_index(drop=True)
    deliv_sub = can.loc[can["is_delivered"], ["order_id", "customer_id", "order_day", "order_month"]].copy()
    deliv_sub["customer_delivered_seq"] = deliv_sub.groupby("customer_id").cumcount() + 1

    first_deliv = (
        deliv_sub.loc[deliv_sub["customer_delivered_seq"] == 1, ["customer_id", "order_day", "order_month"]]
        .rename(columns={"order_day": "first_delivered_date", "order_month": "cohort_month"})
    )

    can = can.merge(
        deliv_sub[["order_id", "customer_delivered_seq"]],
        on="order_id",
        how="left",
    ).merge(
        first_deliv,
        on="customer_id",
        how="left",
    )
    can["customer_delivered_seq"] = can["customer_delivered_seq"].fillna(0).astype(int)
    can["is_new_customer_order"] = can["customer_delivered_seq"] == 1
    can["first_delivered_date"] = can["first_delivered_date"].fillna("")
    can["cohort_month"] = can["cohort_month"].fillna("")

    # Build enriched canonical_order_items with proportional cost allocation for SKU unit economics
    items_enr = order_items.copy()
    items_enr["order_id"] = items_enr["order_id"].astype(str)
    items_enr["product_id"] = items_enr["product_id"].astype(str)
    items_enr = items_enr.merge(
        products[["product_id", "product_name", "category", "unit_cogs", "list_price"]],
        on="product_id",
        how="left",
    ).merge(
        can[
            [
                "order_id",
                "customer_id",
                "order_date",
                "order_day",
                "order_month",
                "order_status",
                "payment_mode",
                "channel",
                "campaign_id",
                "city_tier",
                "is_shipped",
                "is_delivered",
                "is_retained_delivered",
                "is_rto",
                "is_cancelled",
                "is_returned_any",
                "gross_item_revenue",
                "earned_shipping_revenue",
                "shipping_cost",
                "payment_fee",
            ]
        ],
        on="order_id",
        how="left",
    )

    items_enr["quantity"] = pd.to_numeric(items_enr["quantity"], errors="coerce").fillna(0).astype(int)
    items_enr["unit_selling_price"] = pd.to_numeric(items_enr["unit_selling_price"], errors="coerce").fillna(0.0)
    items_enr["unit_discount"] = pd.to_numeric(items_enr["unit_discount"], errors="coerce").fillna(0.0)
    items_enr["line_refund_amount"] = pd.to_numeric(items_enr["line_refund_amount"], errors="coerce").fillna(0.0)
    items_enr["unit_cogs"] = pd.to_numeric(items_enr["unit_cogs"], errors="coerce").fillna(0.0)

    items_enr["gross_line_revenue"] = (items_enr["quantity"] * items_enr["unit_selling_price"]).round(2)
    items_enr["line_discount_amount"] = (items_enr["quantity"] * items_enr["unit_discount"]).round(2)
    items_enr["net_line_before_refund"] = (
        items_enr["gross_line_revenue"] - items_enr["line_discount_amount"]
    ).round(2)
    items_enr["line_net_merchandise_sales"] = np.where(
        items_enr["is_delivered"],
        np.maximum(0.0, items_enr["net_line_before_refund"] - items_enr["line_refund_amount"]),
        0.0,
    ).round(2)

    items_enr["gross_line_cogs"] = (items_enr["quantity"] * items_enr["unit_cogs"]).round(2)
    ret_ratio = np.where(
        items_enr["net_line_before_refund"] > 0,
        np.clip(1.0 - (items_enr["line_refund_amount"] / items_enr["net_line_before_refund"]), 0.0, 1.0),
        0.0,
    )
    items_enr["line_net_cogs"] = np.where(
        items_enr["is_delivered"],
        (items_enr["gross_line_cogs"] * ret_ratio).round(2),
        0.0,
    )

    # Allocate order-level shipping revenue, shipping cost, and payment fee by gross_line_revenue share
    rev_share = np.where(
        items_enr["gross_item_revenue"] > 0,
        items_enr["gross_line_revenue"] / items_enr["gross_item_revenue"],
        0.0,
    )
    items_enr["allocated_shipping_revenue"] = (items_enr["earned_shipping_revenue"] * rev_share).round(2)
    items_enr["allocated_shipping_cost"] = (items_enr["shipping_cost"] * rev_share).round(2)
    items_enr["allocated_payment_fee"] = (items_enr["payment_fee"] * rev_share).round(2)
    items_enr["line_contribution_profit"] = (
        items_enr["line_net_merchandise_sales"]
        + items_enr["allocated_shipping_revenue"]
        - items_enr["line_net_cogs"]
        - items_enr["allocated_shipping_cost"]
        - items_enr["allocated_payment_fee"]
    ).round(2)

    # Verify join cardinality (zero fan-out)
    fanout_detected = len(can) != len(orders) or can["order_id"].nunique() != len(orders)
    order_net_sales_sum = float(can["net_merchandise_sales"].sum())
    item_net_sales_sum = float(items_enr["line_net_merchandise_sales"].sum())
    sales_diff = abs(order_net_sales_sum - item_net_sales_sum)

    if fanout_detected:
        raise ValueError(
            f"Join fan-out detected: input orders={len(orders)}, canonical_orders={len(can)}"
        )

    join_audit = {
        "orders_input": len(orders),
        "canonical_orders_output": len(can),
        "unique_order_ids": int(can["order_id"].nunique()),
        "fanout_detected": fanout_detected,
        "order_net_sales_sum": round(order_net_sales_sum, 2),
        "item_net_sales_sum": round(item_net_sales_sum, 2),
        "order_vs_item_sales_diff": round(sales_diff, 4),
    }

    return CanonicalModel(
        raw_tables=clean_tables,
        canonical_orders=can,
        canonical_order_items=items_enr,
        join_audit=join_audit,
    )


def load_into_duckdb(
    model: CanonicalModel,
    db_path: Path | str | None = None,
    schema_sql_path: Path | str | None = None,
) -> Path:
    """Persist validated raw tables and canonical tables into a DuckDB database file."""
    settings = load_settings()
    if db_path is not None:
        target_db = Path(db_path)
    else:
        rel_db = settings.get("database", {}).get("path", "data/processed/d2c_analytics.duckdb")
        target_db = Path(rel_db) if Path(rel_db).is_absolute() else (PROJECT_ROOT / rel_db)

    target_db.parent.mkdir(parents=True, exist_ok=True)
    schema_file = Path(schema_sql_path) if schema_sql_path is not None else (PROJECT_ROOT / "sql" / "schema.sql")

    con = duckdb.connect(str(target_db))
    try:
        # Drop existing tables so reloads are idempotent
        for tbl_name in list(model.raw_tables.keys()) + ["canonical_orders", "canonical_order_items"]:
            con.execute(f"DROP TABLE IF EXISTS {tbl_name}")

        if schema_file.exists():
            ddl_sql = schema_file.read_text(encoding="utf-8")
            con.execute(ddl_sql)

        for tbl_name, df in model.raw_tables.items():
            df_to_load = df.copy()
            # Convert empty strings in optional date columns to None for SQL TIMESTAMP/DATE compatibility
            for dcol in ("delivered_at",):
                if dcol in df_to_load.columns:
                    df_to_load[dcol] = df_to_load[dcol].replace("", None)
            con.register(f"tmp_{tbl_name}", df_to_load)
            con.execute(f"INSERT INTO {tbl_name} SELECT * FROM tmp_{tbl_name}")
            con.unregister(f"tmp_{tbl_name}")

        con.register("tmp_canonical_orders", model.canonical_orders)
        con.execute("CREATE TABLE canonical_orders AS SELECT * FROM tmp_canonical_orders")
        con.unregister("tmp_canonical_orders")

        con.register("tmp_canonical_order_items", model.canonical_order_items)
        con.execute("CREATE TABLE canonical_order_items AS SELECT * FROM tmp_canonical_order_items")
        con.unregister("tmp_canonical_order_items")
    finally:
        con.close()

    return target_db


def save_processed_artifacts(
    model: CanonicalModel,
    processed_dir: Path | str | None = None,
    validation_summary_df: pd.DataFrame | None = None,
    rejected_rows_df: pd.DataFrame | None = None,
) -> dict[str, Path]:
    """Save canonical CSV artifacts and validation audit reports to data/processed/."""
    out_dir = Path(processed_dir) if processed_dir is not None else (PROJECT_ROOT / "data" / "processed")
    out_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}
    can_orders_path = out_dir / "canonical_orders.csv"
    model.canonical_orders.to_csv(can_orders_path, index=False)
    paths["canonical_orders"] = can_orders_path

    can_items_path = out_dir / "canonical_order_items.csv"
    model.canonical_order_items.to_csv(can_items_path, index=False)
    paths["canonical_order_items"] = can_items_path

    if validation_summary_df is not None:
        val_path = out_dir / "validation_checks.csv"
        validation_summary_df.to_csv(val_path, index=False)
        paths["validation_checks"] = val_path

    if rejected_rows_df is not None:
        rej_path = out_dir / "rejected_rows.csv"
        rejected_rows_df.to_csv(rej_path, index=False)
        paths["rejected_rows"] = rej_path

    return paths
