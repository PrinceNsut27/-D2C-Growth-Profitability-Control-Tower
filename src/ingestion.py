"""Data ingestion module for loading raw CSV datasets into typed DataFrames."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import pandas as pd

from src.config import PROJECT_ROOT, load_settings

REQUIRED_TABLES: tuple[str, ...] = (
    "customers",
    "products",
    "orders",
    "order_items",
    "sessions",
    "marketing_spend",
    "shipments",
    "returns",
    "inventory_snapshots",
)

EXPECTED_COLUMNS: dict[str, list[str]] = {
    "customers": [
        "customer_id",
        "signup_date",
        "first_touch_channel",
        "first_touch_campaign_id",
        "city_tier",
    ],
    "products": [
        "product_id",
        "product_name",
        "category",
        "unit_cogs",
        "list_price",
        "launch_date",
    ],
    "orders": [
        "order_id",
        "customer_id",
        "order_date",
        "order_status",
        "payment_mode",
        "channel",
        "campaign_id",
        "currency",
        "discount_amount",
        "shipping_revenue",
        "tax_amount",
    ],
    "order_items": [
        "order_item_id",
        "order_id",
        "product_id",
        "quantity",
        "unit_selling_price",
        "unit_discount",
        "line_refund_amount",
    ],
    "sessions": [
        "session_id",
        "customer_id",
        "session_start",
        "channel",
        "campaign_id",
        "device",
        "product_view",
        "add_to_cart",
        "checkout_started",
        "converted",
        "order_id",
    ],
    "marketing_spend": [
        "date",
        "platform",
        "channel",
        "campaign_id",
        "spend",
        "impressions",
        "clicks",
        "currency",
    ],
    "shipments": [
        "shipment_id",
        "order_id",
        "shipped_at",
        "delivered_at",
        "shipment_status",
        "shipping_cost",
        "courier_partner",
        "rto_reason",
    ],
    "returns": [
        "return_id",
        "order_id",
        "order_item_id",
        "return_requested_at",
        "return_reason",
        "refund_amount",
        "return_status",
    ],
    "inventory_snapshots": [
        "snapshot_date",
        "product_id",
        "opening_stock",
        "units_received",
        "units_sold",
        "closing_stock",
        "reorder_point",
    ],
}


def resolve_table_paths(
    data_dir: Path | str | None = None,
    config_path: Path | str | None = None,
) -> dict[str, Path]:
    """Resolve CSV file paths for all 9 required tables."""
    if data_dir is not None:
        base_dir = Path(data_dir)
        return {tbl: base_dir / f"{tbl}.csv" for tbl in REQUIRED_TABLES}

    settings = load_settings(config_path)
    data_cfg = settings.get("data", {})
    paths: dict[str, Path] = {}
    for tbl in REQUIRED_TABLES:
        rel_path = data_cfg.get(tbl, f"data/raw/{tbl}.csv")
        p = Path(rel_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        paths[tbl] = p
    return paths


def load_table_csv(path: Path | str, table_name: str | None = None) -> pd.DataFrame:
    """Load a single CSV file with safe string handling for IDs and nullable string columns."""
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Dataset file not found for {table_name or csv_path.name}: {csv_path}")

    df = pd.read_csv(csv_path, keep_default_na=True)
    return normalize_dataframe_types(df, table_name=table_name)


def normalize_dataframe_types(df: pd.DataFrame, table_name: str | None = None) -> pd.DataFrame:
    """Coerce standard string/boolean/numeric columns without dropping invalid rows."""
    out = df.copy()
    nullable_str_cols = {
        "first_touch_campaign_id",
        "campaign_id",
        "customer_id",
        "order_id",
        "order_item_id",
        "delivered_at",
        "rto_reason",
    }
    for col in out.columns:
        if col in nullable_str_cols:
            out[col] = out[col].fillna("").astype(str).str.strip()

    if table_name == "sessions":
        for bcol in ("product_view", "add_to_cart", "checkout_started", "converted"):
            if bcol in out.columns:
                if out[bcol].dtype != bool:
                    out[bcol] = (
                        out[bcol]
                        .astype(str)
                        .str.strip()
                        .str.lower()
                        .map({"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False})
                    )
    return out


def ingest_all_tables(
    data_dir: Path | str | None = None,
    config_path: Path | str | None = None,
) -> dict[str, pd.DataFrame]:
    """Load all 9 source CSV tables into a dictionary of DataFrames."""
    paths = resolve_table_paths(data_dir=data_dir, config_path=config_path)
    datasets: dict[str, pd.DataFrame] = {}
    for tbl, csv_path in paths.items():
        datasets[tbl] = load_table_csv(csv_path, table_name=tbl)
    return datasets
