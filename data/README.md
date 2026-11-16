# Data README — Provenance, Schema & Synthetic Disclosure

> **SYNTHETIC DATA DISCLOSURE**: All datasets in `data/raw/`, `data/processed/`, and `data/sample/` are **100% deterministic synthetic records** generated for the fictional Indian skincare D2C brand **"AuraVeda Skincare"**. They contain zero real personal information (PII) and must never be represented as actual company performance.

---

## 1. Generator Metadata & Reproducibility
- **Generator Module**: `src/generate_data.py` (`v1.0.0`)
- **Random Seed**: `42` (`np.random.default_rng(42)`)
- **Date Window**: `2026-05-01` to `2026-10-31` (184 calendar days, `Asia/Kolkata` timezone)
- **Default Currency**: `INR` (`₹`)
- **Reproduction Command**:
  ```bash
  python -m src.generate_data
  ```

---

## 2. Generated Dataset Files & Row Counts (`data/raw/`)

| File | Grain / Primary Key | Row Count (Seed = 42) | Description |
|---|---|---:|---|
| `customers.csv` | `customer_id` | 3,200 | Pseudonymous customer records with signup date, first-touch channel/campaign, and city tier (`Tier 1`, `Tier 2`, `Tier 3`) |
| `products.csv` | `product_id` | 8 | Skincare SKU catalog (`Face Wash`, `Moisturiser`, `Sunscreen`, `Serum`, `Bundles`) with INR `unit_cogs` and `list_price` |
| `orders.csv` | `order_id` | 6,500 | Order headers with lifecycle status, payment mode (`cod` / `prepaid`), channel, campaign, discount, shipping revenue, and GST |
| `order_items.csv` | `order_item_id` | 9,722 | Order SKU line items with quantity, list price, unit discount, and line refund amount |
| `sessions.csv` | `session_id` | 48,000 | Website/storefront sessions with device (`mobile`, `desktop`, `tablet`), funnel flags (`product_view`, `add_to_cart`, `checkout_started`, `converted`), and `order_id` |
| `marketing_spend.csv` | `(date, platform, channel, campaign_id)` | 1,288 | Daily paid media spend, impressions, and clicks across 7 campaigns on `Meta Ads`, `Google Ads`, and `Creator Network` |
| `shipments.csv` | `shipment_id` | 5,402 | Courier fulfillment records (`Delhivery`, `BlueDart`, `Ecom Express`, `Shadowfax`) with timestamps, shipping cost, and RTO reasons |
| `returns.csv` | `return_id` | 643 | Post-delivery customer return and partial-refund cases linked to `order_id` and `order_item_id` |
| `inventory_snapshots.csv` | `(snapshot_date, product_id)` | 1,472 | Daily warehouse stock movements (`opening_stock + units_received - units_sold = closing_stock`) and SKU `reorder_point` |

---

## 3. Business & Simulation Assumptions
1. **Channel & Campaign Attribution**:
   - Paid channels (`Paid Social`, `Paid Search`, `Influencer`) carry explicit `campaign_id` tags (`CMP-META-PROSP-01`, `CMP-META-FLASH-02`, `CMP-META-RETARG-03`, `CMP-GGL-BRAND-01`, `CMP-GGL-NONBRAND-02`, `CMP-GGL-SHOP-03`, `CMP-INF-REELS-01`).
   - Non-paid and external channels (`Organic Search`, `Direct`, `Email/CRM`, `Marketplace`) have empty/unassigned `campaign_id`.
   - Repeat orders by previously acquired customers frequently arrive via `Direct`, `Email/CRM`, `Organic Search`, `CMP-META-RETARG-03`, or `CMP-GGL-BRAND-01`.
2. **Payment Modes, COD & RTO Dynamics**:
   - Cash-on-Delivery (`cod`) propensity is higher in `Tier 2` and `Tier 3` cities and during high-discount flash sales (`CMP-META-FLASH-02`), and lower on repeat and `Tier 1` orders.
   - `rto` (Return-to-Origin) occurs on undelivered shipped orders—significantly more often on `cod` orders than `prepaid` orders—and incurs both forward and reverse courier shipping charges (~1.65x–1.90x base shipping cost) while generating ₹0 net merchandise sales.
3. **Order Lifecycle & Financial Reconciliation**:
   - Order header `discount_amount` reconciles exactly with $\sum (\text{quantity} \times \text{unit\_discount})$ across its `order_items`.
   - `returned` (full return) and `partially_refunded` (partial return) orders occur only on delivered orders (`delivered_at IS NOT NULL`) and reconcile exactly with `returns.refund_amount` and `order_items.line_refund_amount`.
   - Orders with net merchandise value below ₹499 are charged ₹49 `shipping_revenue`; orders $\ge$ ₹499 receive free shipping (`shipping_revenue = 0.00`).
4. **Inventory Snapshot Arithmetic**:
   - Daily `units_sold` reflects non-cancelled order demand bounded by available stock (`opening_stock + units_received`).
   - Every row satisfies `opening_stock + units_received - units_sold = closing_stock`, and each day's `opening_stock` equals the prior day's `closing_stock`.
   - Selected fast-moving SKUs (`SKU-SS-01`, `SKU-FW-01`, `SKU-SR-01`) experience realistic replenishment lead-time lags (5 days below `reorder_point` before restock receipt).

---

## 4. Known Limitations
- **Observational Attribution**: Last-touch campaign IDs on sessions and orders reflect observational tracking, not randomized holdout incrementality.
- **Snapshot Granularity**: Inventory snapshots are recorded at a daily grain; intraday stockouts or unfulfilled backorder intent are not directly observed.
- **Synthetic Nature**: While calibrated to realistic Indian D2C skincare unit economics, all numbers are simulated.
