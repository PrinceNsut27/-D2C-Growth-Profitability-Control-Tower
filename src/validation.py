"""Comprehensive data quality and schema validation module.

Validates schemas, nulls, primary-key duplicates, negative values, date formats,
chronological ordering, currency codes, referential integrity, order lifecycle
transitions, financial total reconciliation, and inventory arithmetic.
Never silently drops bad rows: produces an explicit ValidationReport with
rejected-row counts, reasons, and separated clean/rejected DataFrames.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import numpy as np
import pandas as pd

from src.ingestion import EXPECTED_COLUMNS, REQUIRED_TABLES

VALID_ORDER_STATUSES = {
    "placed",
    "confirmed",
    "shipped",
    "delivered",
    "cancelled",
    "rto",
    "returned",
    "partially_refunded",
}
VALID_PAYMENT_MODES = {"cod", "prepaid"}
VALID_SHIPMENT_STATUSES = {"in_transit", "delivered", "rto"}
VALID_RETURN_STATUSES = {"requested", "approved", "refunded", "rejected"}

PRIMARY_KEYS: dict[str, list[str]] = {
    "customers": ["customer_id"],
    "products": ["product_id"],
    "orders": ["order_id"],
    "order_items": ["order_item_id"],
    "sessions": ["session_id"],
    "marketing_spend": ["date", "platform", "channel", "campaign_id"],
    "shipments": ["shipment_id"],
    "returns": ["return_id"],
    "inventory_snapshots": ["snapshot_date", "product_id"],
}


@dataclass
class CheckResult:
    """Result of an individual validation check."""

    check_name: str
    table_name: str
    passed: bool
    failed_count: int
    severity: str  # "ERROR" or "WARNING"
    message: str


@dataclass
class ValidationReport:
    """Structured report of all data validation checks and rejected rows."""

    passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    rejected_rows: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(
            columns=["table_name", "row_index", "primary_key", "reason"]
        )
    )
    clean_tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    summary_by_table: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_summary_dataframe(self) -> pd.DataFrame:
        """Return a tabular summary of all executed validation checks."""
        if not self.checks:
            return pd.DataFrame(
                columns=["check_name", "table_name", "passed", "failed_count", "severity", "message"]
            )
        return pd.DataFrame([vars(c) for c in self.checks])


def _record_rejections(
    reject_tracker: dict[str, dict[int, list[str]]],
    table_name: str,
    bad_indices: pd.Index | list[int],
    reason: str,
) -> None:
    """Accumulate rejection reasons per (table_name, row_index)."""
    tbl_map = reject_tracker.setdefault(table_name, {})
    for idx in bad_indices:
        tbl_map.setdefault(int(idx), []).append(reason)


def validate_all_tables(
    tables: dict[str, pd.DataFrame],
    expected_currency: str = "INR",
) -> ValidationReport:
    """Run full validation suite across all 9 tables and build a ValidationReport."""
    checks: list[CheckResult] = []
    reject_tracker: dict[str, dict[int, list[str]]] = {t: {} for t in REQUIRED_TABLES}

    # 1. Table presence & schema checks
    missing_tables = [t for t in REQUIRED_TABLES if t not in tables]
    if missing_tables:
        for mt in missing_tables:
            checks.append(
                CheckResult(
                    check_name="table_exists",
                    table_name=mt,
                    passed=False,
                    failed_count=1,
                    severity="ERROR",
                    message=f"Required table '{mt}' is missing from input datasets.",
                )
            )
        return ValidationReport(passed=False, checks=checks)

    schema_ok = True
    for tbl in REQUIRED_TABLES:
        df = tables[tbl]
        expected_cols = EXPECTED_COLUMNS[tbl]
        missing_cols = [c for c in expected_cols if c not in df.columns]
        passed = len(missing_cols) == 0
        if not passed:
            schema_ok = False
        checks.append(
            CheckResult(
                check_name="schema_columns",
                table_name=tbl,
                passed=passed,
                failed_count=len(missing_cols),
                severity="ERROR",
                message="All required columns present."
                if passed
                else f"Missing required columns: {missing_cols}",
            )
        )

    if not schema_ok:
        return ValidationReport(passed=False, checks=checks)

    # 2. Primary key duplicate checks & required non-null checks
    required_non_null_cols: dict[str, list[str]] = {
        "customers": ["customer_id", "signup_date", "first_touch_channel", "city_tier"],
        "products": ["product_id", "product_name", "category", "unit_cogs", "list_price", "launch_date"],
        "orders": [
            "order_id",
            "customer_id",
            "order_date",
            "order_status",
            "payment_mode",
            "channel",
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
            "session_start",
            "channel",
            "device",
            "product_view",
            "add_to_cart",
            "checkout_started",
            "converted",
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
            "shipment_status",
            "shipping_cost",
            "courier_partner",
        ],
        "returns": [
            "return_id",
            "order_id",
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

    for tbl in REQUIRED_TABLES:
        df = tables[tbl]
        pk_cols = PRIMARY_KEYS[tbl]

        # Check nulls/empty strings in mandatory columns
        null_mask = pd.Series(False, index=df.index)
        for col in required_non_null_cols[tbl]:
            col_s = df[col]
            is_missing = col_s.isna() | (col_s.astype(str).str.strip() == "")
            null_mask = null_mask | is_missing

        null_bad_idx = df.index[null_mask]
        if len(null_bad_idx) > 0:
            _record_rejections(reject_tracker, tbl, null_bad_idx, "Missing mandatory column value")
        checks.append(
            CheckResult(
                check_name="mandatory_non_null",
                table_name=tbl,
                passed=len(null_bad_idx) == 0,
                failed_count=len(null_bad_idx),
                severity="ERROR",
                message="No missing values in mandatory columns."
                if len(null_bad_idx) == 0
                else f"{len(null_bad_idx)} row(s) have null/empty mandatory fields.",
            )
        )

        # Check duplicate primary keys (keep='first' marks subsequent duplicates as rejected)
        dup_mask = df.duplicated(subset=pk_cols, keep="first")
        dup_idx = df.index[dup_mask]
        if len(dup_idx) > 0:
            _record_rejections(reject_tracker, tbl, dup_idx, f"Duplicate primary key on {pk_cols}")
        checks.append(
            CheckResult(
                check_name="primary_key_uniqueness",
                table_name=tbl,
                passed=len(dup_idx) == 0,
                failed_count=len(dup_idx),
                severity="ERROR",
                message=f"Primary key {pk_cols} is unique."
                if len(dup_idx) == 0
                else f"{len(dup_idx)} duplicate primary key row(s) detected on {pk_cols}.",
            )
        )

    # 3. Negative / invalid numeric values
    numeric_rules: dict[str, list[tuple[str, bool]]] = {
        # (column_name, strictly_positive)
        "products": [("unit_cogs", False), ("list_price", True)],
        "orders": [("discount_amount", False), ("shipping_revenue", False), ("tax_amount", False)],
        "order_items": [
            ("quantity", True),
            ("unit_selling_price", True),
            ("unit_discount", False),
            ("line_refund_amount", False),
        ],
        "marketing_spend": [("spend", False), ("impressions", False), ("clicks", False)],
        "shipments": [("shipping_cost", False)],
        "returns": [("refund_amount", False)],
        "inventory_snapshots": [
            ("opening_stock", False),
            ("units_received", False),
            ("units_sold", False),
            ("closing_stock", False),
            ("reorder_point", False),
        ],
    }

    for tbl, col_rules in numeric_rules.items():
        df = tables[tbl]
        bad_num_mask = pd.Series(False, index=df.index)
        for col, strict_pos in col_rules:
            num_s = pd.to_numeric(df[col], errors="coerce")
            if strict_pos:
                invalid = num_s.isna() | (num_s <= 0)
            else:
                invalid = num_s.isna() | (num_s < 0)
            bad_num_mask = bad_num_mask | invalid

        bad_idx = df.index[bad_num_mask]
        if len(bad_idx) > 0:
            _record_rejections(reject_tracker, tbl, bad_idx, "Negative or non-numeric financial/quantity value")
        checks.append(
            CheckResult(
                check_name="non_negative_numerics",
                table_name=tbl,
                passed=len(bad_idx) == 0,
                failed_count=len(bad_idx),
                severity="ERROR",
                message="All numeric and monetary columns are valid and non-negative."
                if len(bad_idx) == 0
                else f"{len(bad_idx)} row(s) contain negative, zero, or non-numeric values.",
            )
        )

    # 4. Date parsing checks
    date_cols_by_table: dict[str, list[tuple[str, bool]]] = {
        # (column_name, allow_empty)
        "customers": [("signup_date", False)],
        "products": [("launch_date", False)],
        "orders": [("order_date", False)],
        "sessions": [("session_start", False)],
        "marketing_spend": [("date", False)],
        "shipments": [("shipped_at", False), ("delivered_at", True)],
        "returns": [("return_requested_at", False)],
        "inventory_snapshots": [("snapshot_date", False)],
    }

    for tbl, d_rules in date_cols_by_table.items():
        df = tables[tbl]
        bad_date_mask = pd.Series(False, index=df.index)
        for col, allow_empty in d_rules:
            raw_s = df[col].fillna("").astype(str).str.strip()
            parsed = pd.to_datetime(raw_s.replace("", pd.NA), format="mixed", errors="coerce")
            if allow_empty:
                invalid = (raw_s != "") & parsed.isna()
            else:
                invalid = parsed.isna()
            bad_date_mask = bad_date_mask | invalid

        bad_idx = df.index[bad_date_mask]
        if len(bad_idx) > 0:
            _record_rejections(reject_tracker, tbl, bad_idx, "Invalid date/timestamp format")
        checks.append(
            CheckResult(
                check_name="valid_dates",
                table_name=tbl,
                passed=len(bad_idx) == 0,
                failed_count=len(bad_idx),
                severity="ERROR",
                message="All date and timestamp columns parse cleanly."
                if len(bad_idx) == 0
                else f"{len(bad_idx)} row(s) have unparseable date/timestamp values.",
            )
        )

    # 5. Currency consistency checks
    for tbl in ("orders", "marketing_spend"):
        df = tables[tbl]
        bad_curr_idx = df.index[df["currency"].astype(str).str.strip() != expected_currency]
        if len(bad_curr_idx) > 0:
            _record_rejections(reject_tracker, tbl, bad_curr_idx, f"Unsupported currency (expected {expected_currency})")
        checks.append(
            CheckResult(
                check_name="currency_consistency",
                table_name=tbl,
                passed=len(bad_curr_idx) == 0,
                failed_count=len(bad_curr_idx),
                severity="ERROR",
                message=f"All rows use {expected_currency} currency."
                if len(bad_curr_idx) == 0
                else f"{len(bad_curr_idx)} row(s) do not match currency '{expected_currency}'.",
            )
        )

    # 6. Referential integrity (Foreign Keys)
    valid_cust_ids = set(tables["customers"]["customer_id"].dropna().astype(str))
    valid_prod_ids = set(tables["products"]["product_id"].dropna().astype(str))
    valid_order_ids = set(tables["orders"]["order_id"].dropna().astype(str))
    valid_item_ids = set(tables["order_items"]["order_item_id"].dropna().astype(str))

    fk_specs: list[tuple[str, str, set[str], bool, str]] = [
        ("orders", "customer_id", valid_cust_ids, False, "customers.customer_id"),
        ("order_items", "order_id", valid_order_ids, False, "orders.order_id"),
        ("order_items", "product_id", valid_prod_ids, False, "products.product_id"),
        ("sessions", "customer_id", valid_cust_ids, True, "customers.customer_id"),
        ("sessions", "order_id", valid_order_ids, True, "orders.order_id"),
        ("shipments", "order_id", valid_order_ids, False, "orders.order_id"),
        ("returns", "order_id", valid_order_ids, False, "orders.order_id"),
        ("returns", "order_item_id", valid_item_ids, True, "order_items.order_item_id"),
        ("inventory_snapshots", "product_id", valid_prod_ids, False, "products.product_id"),
    ]

    for tbl, col, target_set, allow_empty, ref_label in fk_specs:
        df = tables[tbl]
        vals = df[col].fillna("").astype(str).str.strip()
        if allow_empty:
            bad_fk_mask = (vals != "") & (~vals.isin(target_set))
        else:
            bad_fk_mask = ~vals.isin(target_set)
        bad_idx = df.index[bad_fk_mask]
        if len(bad_idx) > 0:
            _record_rejections(reject_tracker, tbl, bad_idx, f"Unknown foreign key {col} -> {ref_label}")
        checks.append(
            CheckResult(
                check_name=f"fk_{col}_to_{ref_label.split('.')[0]}",
                table_name=tbl,
                passed=len(bad_idx) == 0,
                failed_count=len(bad_idx),
                severity="ERROR",
                message=f"All {tbl}.{col} references exist in {ref_label}."
                if len(bad_idx) == 0
                else f"{len(bad_idx)} orphan foreign key row(s) in {tbl}.{col} -> {ref_label}.",
            )
        )

    # 7. Order status, payment mode & lifecycle transition checks
    orders_df = tables["orders"]
    shipments_df = tables["shipments"]
    returns_df = tables["returns"]
    items_df = tables["order_items"]

    bad_status_idx = orders_df.index[~orders_df["order_status"].isin(VALID_ORDER_STATUSES)]
    if len(bad_status_idx) > 0:
        _record_rejections(reject_tracker, "orders", bad_status_idx, "Invalid order_status value")
    checks.append(
        CheckResult(
            check_name="valid_order_status_domain",
            table_name="orders",
            passed=len(bad_status_idx) == 0,
            failed_count=len(bad_status_idx),
            severity="ERROR",
            message="All order_status values are valid."
            if len(bad_status_idx) == 0
            else f"{len(bad_status_idx)} order(s) have unknown order_status.",
        )
    )

    bad_pm_idx = orders_df.index[~orders_df["payment_mode"].isin(VALID_PAYMENT_MODES)]
    if len(bad_pm_idx) > 0:
        _record_rejections(reject_tracker, "orders", bad_pm_idx, "Invalid payment_mode value")
    checks.append(
        CheckResult(
            check_name="valid_payment_mode_domain",
            table_name="orders",
            passed=len(bad_pm_idx) == 0,
            failed_count=len(bad_pm_idx),
            severity="ERROR",
            message="All payment_mode values are valid (cod/prepaid)."
            if len(bad_pm_idx) == 0
            else f"{len(bad_pm_idx)} order(s) have invalid payment_mode.",
        )
    )

    # Check lifecycle transition consistency between orders, shipments, and returns
    shipped_order_ids = set(shipments_df["order_id"].astype(str))
    delivered_ship_order_ids = set(
        shipments_df.loc[shipments_df["shipment_status"] == "delivered", "order_id"].astype(str)
    )
    rto_ship_order_ids = set(
        shipments_df.loc[shipments_df["shipment_status"] == "rto", "order_id"].astype(str)
    )
    returned_order_ids = set(returns_df["order_id"].astype(str))

    o_ids = orders_df["order_id"].astype(str)
    o_stat = orders_df["order_status"].astype(str)

    # Cancelled/placed/confirmed orders should not have delivered shipments or returns
    impossible_pre_ship = o_stat.isin(["placed", "confirmed", "cancelled"]) & (
        o_ids.isin(delivered_ship_order_ids) | o_ids.isin(returned_order_ids)
    )
    # RTO orders should not have delivered shipments or customer returns, and must be in rto_ship_order_ids
    impossible_rto = (o_stat == "rto") & (
        o_ids.isin(delivered_ship_order_ids) | o_ids.isin(returned_order_ids) | (~o_ids.isin(rto_ship_order_ids))
    )
    # Delivered/returned/partially_refunded orders must have a delivered shipment
    impossible_deliv = o_stat.isin(["delivered", "returned", "partially_refunded"]) & (
        ~o_ids.isin(delivered_ship_order_ids)
    )
    # Returned/partially_refunded orders must have a return record
    impossible_ret = o_stat.isin(["returned", "partially_refunded"]) & (~o_ids.isin(returned_order_ids))
    # Shipped status must have a shipment record
    impossible_shipped = (o_stat == "shipped") & (~o_ids.isin(shipped_order_ids))

    lifecycle_bad_mask = (
        impossible_pre_ship | impossible_rto | impossible_deliv | impossible_ret | impossible_shipped
    )
    lifecycle_bad_idx = orders_df.index[lifecycle_bad_mask]
    if len(lifecycle_bad_idx) > 0:
        _record_rejections(
            reject_tracker,
            "orders",
            lifecycle_bad_idx,
            "Inconsistent order lifecycle transition across shipments/returns",
        )
    checks.append(
        CheckResult(
            check_name="order_lifecycle_consistency",
            table_name="orders",
            passed=len(lifecycle_bad_idx) == 0,
            failed_count=len(lifecycle_bad_idx),
            severity="ERROR",
            message="All order statuses align with shipment and return lifecycle records."
            if len(lifecycle_bad_idx) == 0
            else f"{len(lifecycle_bad_idx)} order(s) have contradictory shipment/return lifecycle states.",
        )
    )

    # Check shipment timestamp chronology (delivered_at >= shipped_at, RTO has no delivered_at)
    shp_shipped_dt = pd.to_datetime(shipments_df["shipped_at"], format="mixed", errors="coerce")
    shp_deliv_raw = shipments_df["delivered_at"].fillna("").astype(str).str.strip()
    shp_deliv_dt = pd.to_datetime(shp_deliv_raw.replace("", pd.NA), format="mixed", errors="coerce")
    shp_stat = shipments_df["shipment_status"].astype(str)

    bad_shp_chrono = (
        (~shp_stat.isin(VALID_SHIPMENT_STATUSES))
        | ((shp_deliv_raw != "") & (shp_deliv_dt < shp_shipped_dt))
        | ((shp_stat == "rto") & (shp_deliv_raw != ""))
        | ((shp_stat == "delivered") & (shp_deliv_raw == ""))
    )
    bad_shp_idx = shipments_df.index[bad_shp_chrono]
    if len(bad_shp_idx) > 0:
        _record_rejections(reject_tracker, "shipments", bad_shp_idx, "Invalid shipment status or timestamp chronology")
    checks.append(
        CheckResult(
            check_name="shipment_chronology_and_status",
            table_name="shipments",
            passed=len(bad_shp_idx) == 0,
            failed_count=len(bad_shp_idx),
            severity="ERROR",
            message="All shipment timestamps and statuses are chronologically valid."
            if len(bad_shp_idx) == 0
            else f"{len(bad_shp_idx)} shipment row(s) violate status or timestamp chronology.",
        )
    )

    # 8. Financial reconciliation: Order header discount vs sum of item discounts, and item refund bounds
    item_qty = pd.to_numeric(items_df["quantity"], errors="coerce").fillna(0)
    item_price = pd.to_numeric(items_df["unit_selling_price"], errors="coerce").fillna(0.0)
    item_disc = pd.to_numeric(items_df["unit_discount"], errors="coerce").fillna(0.0)
    item_ref = pd.to_numeric(items_df["line_refund_amount"], errors="coerce").fillna(0.0)

    item_net_before_ref = item_qty * (item_price - item_disc)
    bad_item_math = (item_disc > item_price) | (item_ref > (item_net_before_ref + 0.05))
    bad_item_idx = items_df.index[bad_item_math]
    if len(bad_item_idx) > 0:
        _record_rejections(
            reject_tracker,
            "order_items",
            bad_item_idx,
            "Unit discount exceeds unit price or line refund exceeds net line value",
        )
    checks.append(
        CheckResult(
            check_name="order_item_financial_bounds",
            table_name="order_items",
            passed=len(bad_item_idx) == 0,
            failed_count=len(bad_item_idx),
            severity="ERROR",
            message="All order_items satisfy discount <= selling price and refund <= net line amount."
            if len(bad_item_idx) == 0
            else f"{len(bad_item_idx)} order_item row(s) exceed discount or refund bounds.",
        )
    )

    # Reconcile order header discount_amount with sum(quantity * unit_discount)
    item_disc_sum = (
        pd.DataFrame({"order_id": items_df["order_id"].astype(str), "line_disc": item_qty * item_disc})
        .groupby("order_id", as_index=False)["line_disc"]
        .sum()
    )
    ord_disc_check = orders_df[["order_id", "discount_amount"]].copy()
    ord_disc_check["order_id"] = ord_disc_check["order_id"].astype(str)
    ord_disc_check["discount_amount"] = pd.to_numeric(ord_disc_check["discount_amount"], errors="coerce").fillna(0.0)
    ord_disc_merged = ord_disc_check.merge(item_disc_sum, on="order_id", how="left")
    ord_disc_merged["line_disc"] = ord_disc_merged["line_disc"].fillna(0.0)
    disc_mismatch_mask = (ord_disc_merged["discount_amount"] - ord_disc_merged["line_disc"]).abs() > 0.05
    disc_mismatch_idx = orders_df.index[disc_mismatch_mask.values]
    if len(disc_mismatch_idx) > 0:
        _record_rejections(
            reject_tracker,
            "orders",
            disc_mismatch_idx,
            "Order header discount_amount does not reconcile with sum of order_items discounts",
        )
    checks.append(
        CheckResult(
            check_name="order_discount_reconciliation",
            table_name="orders",
            passed=len(disc_mismatch_idx) == 0,
            failed_count=len(disc_mismatch_idx),
            severity="ERROR",
            message="Order header discount_amount reconciles with order_items."
            if len(disc_mismatch_idx) == 0
            else f"{len(disc_mismatch_idx)} order(s) have header vs line discount mismatch.",
        )
    )

    # 9. Inventory snapshot arithmetic check: opening_stock + units_received - units_sold == closing_stock
    inv_df = tables["inventory_snapshots"]
    op_s = pd.to_numeric(inv_df["opening_stock"], errors="coerce")
    rec_s = pd.to_numeric(inv_df["units_received"], errors="coerce")
    sold_s = pd.to_numeric(inv_df["units_sold"], errors="coerce")
    cl_s = pd.to_numeric(inv_df["closing_stock"], errors="coerce")
    bad_inv_math = (op_s + rec_s - sold_s) != cl_s
    bad_inv_idx = inv_df.index[bad_inv_math.fillna(True)]
    if len(bad_inv_idx) > 0:
        _record_rejections(
            reject_tracker,
            "inventory_snapshots",
            bad_inv_idx,
            "Impossible stock arithmetic: opening_stock + units_received - units_sold != closing_stock",
        )
    checks.append(
        CheckResult(
            check_name="inventory_stock_arithmetic",
            table_name="inventory_snapshots",
            passed=len(bad_inv_idx) == 0,
            failed_count=len(bad_inv_idx),
            severity="ERROR",
            message="All inventory snapshots satisfy opening + received - sold == closing."
            if len(bad_inv_idx) == 0
            else f"{len(bad_inv_idx)} inventory row(s) fail stock arithmetic.",
        )
    )

    # 10. Session funnel boolean sequence check: converted => checkout_started => add_to_cart => product_view
    sess_df = tables["sessions"]
    pv = sess_df["product_view"].astype(bool)
    atc = sess_df["add_to_cart"].astype(bool)
    chk = sess_df["checkout_started"].astype(bool)
    conv = sess_df["converted"].astype(bool)
    bad_funnel = (conv & ~chk) | (chk & ~atc) | (atc & ~pv)
    bad_funnel_idx = sess_df.index[bad_funnel]
    if len(bad_funnel_idx) > 0:
        _record_rejections(
            reject_tracker,
            "sessions",
            bad_funnel_idx,
            "Inconsistent session funnel sequence (later stage True while earlier stage False)",
        )
    checks.append(
        CheckResult(
            check_name="session_funnel_sequence",
            table_name="sessions",
            passed=len(bad_funnel_idx) == 0,
            failed_count=len(bad_funnel_idx),
            severity="ERROR",
            message="All sessions follow valid funnel progression."
            if len(bad_funnel_idx) == 0
            else f"{len(bad_funnel_idx)} session(s) have out-of-sequence funnel flags.",
        )
    )

    # Build rejected rows DataFrame and clean tables without silent dropping
    rejected_records: list[dict[str, Any]] = []
    clean_tables: dict[str, pd.DataFrame] = {}
    summary_by_table: dict[str, dict[str, int]] = {}

    for tbl in REQUIRED_TABLES:
        df = tables[tbl]
        pk_cols = PRIMARY_KEYS[tbl]
        tbl_rejects = reject_tracker.get(tbl, {})
        bad_indices_sorted = sorted(tbl_rejects.keys())

        for r_idx in bad_indices_sorted:
            row = df.loc[r_idx]
            pk_val = "|".join(str(row[c]) for c in pk_cols if c in row)
            rejected_records.append(
                {
                    "table_name": tbl,
                    "row_index": r_idx,
                    "primary_key": pk_val,
                    "reason": "; ".join(tbl_rejects[r_idx]),
                }
            )

        clean_df = df.drop(index=bad_indices_sorted).reset_index(drop=True)
        clean_tables[tbl] = clean_df
        summary_by_table[tbl] = {
            "total_rows": len(df),
            "valid_rows": len(clean_df),
            "rejected_rows": len(bad_indices_sorted),
        }

    rejected_df = (
        pd.DataFrame(rejected_records)
        if rejected_records
        else pd.DataFrame(columns=["table_name", "row_index", "primary_key", "reason"])
    )
    overall_passed = all(c.passed for c in checks if c.severity == "ERROR")

    return ValidationReport(
        passed=overall_passed,
        checks=checks,
        rejected_rows=rejected_df,
        clean_tables=clean_tables,
        summary_by_table=summary_by_table,
    )
