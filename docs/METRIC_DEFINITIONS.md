# Metric Definitions, Formulas, Verified Results & Required Caveats

Every metric in the **D2C Growth & Profitability Control Tower** is implemented identically in Python (`src/metrics.py`, `src/attribution.py`, `src/segmentation.py`, `src/cohorts.py`) and DuckDB SQL (`sql/core_metrics.sql`), returning `NA` (`None` / `NULL`) whenever a denominator is zero.

---

## 1. Master KPI Reference & Computed Baseline (`2026-05-01` to `2026-10-31`, Synthetic Seed = 42)

| Metric | Formula | Numerator & Denominator Scope | Computed Baseline | Required Caveat |
|---|---|---|---|---|
| **Placed Orders** | `COUNT(DISTINCT order_id)` | All order rows in `orders` | `6,500` | Operational order volume across all statuses; not completed sales. |
| **Shipped Orders** | `COUNT(DISTINCT order_id) WHERE is_shipped` | Statuses: `shipped`, `delivered`, `rto`, `returned`, `partially_refunded` | `5,402` | Denominator for Delivery Rate and RTO Rate. |
| **Delivered Orders (Cohort)** | `COUNT(DISTINCT order_id) WHERE is_delivered` | Statuses: `delivered`, `partially_refunded`, `returned` | `4,424` | Orders that physically delivered to the customer; excludes `cancelled`, `rto`, and in-transit orders. |
| **Retained Delivered Orders** | `COUNT(DISTINCT order_id) WHERE is_retained_delivered` | Statuses: `delivered`, `partially_refunded` | `4,106` | Delivered orders excluding full post-delivery returns (`318` full returns). |
| **Order Cancellation Rate** | `Cancelled Orders / Placed Orders` | `477 / 6,500` | `7.34%` | Pre-shipment cancellations divided by total placed orders. |
| **RTO Rate** | `RTO Orders / Shipped Orders` | `754 / 5,402` | `13.96%` | Divided strictly by shipped orders (`COD RTO = 25.03%`, `Prepaid RTO = 4.18%`). |
| **Post-Delivery Return Rate** | `(Returned + Partially Refunded Orders) / Delivered Orders` | `474 / 4,424` | `10.71%` | Includes both full (`318`) and partial (`156`) post-delivery returns. |
| **Placed GMV** | `SUM(quantity * unit_selling_price)` | All placed orders (`11,271` units) | `₹6,752,129.00` | Gross top-line value before cancellations, RTO, discounts, and refunds. |
| **Delivered Gross Revenue** | `SUM(gross_item_revenue) WHERE is_delivered` | Delivered cohort (`7,740` units) | `₹4,652,960.00` | Gross merchandise value of delivered orders before discounts and refunds. |
| **Delivered Discounts** | `SUM(discount_amount) WHERE is_delivered` | Delivered cohort orders | `₹284,604.12` | Promotional discount cost on delivered orders (`₹403,093.65` across all placed orders). |
| **Refund Impact** | `SUM(effective_refund_amount) WHERE is_delivered` | Approved/refunded returns | `₹418,629.91` | Reconciled between `order_items.line_refund_amount` and `returns.refund_amount`. |
| **Net Merchandise Sales** | `Delivered Gross Revenue - Delivered Discounts - Refunds` | `₹4,652,960.00 - ₹284,604.12 - ₹418,629.91` | `₹3,949,725.97` | Excludes GST tax and shipping revenue; `₹0.00` for `cancelled`, `rto`, and fully `returned` orders. |
| **Average Order Value (AOV)** | `Net Merchandise Sales / Delivered Orders` | `₹3,949,725.97 / 4,424` | `₹892.80` | Retained AOV (`Net Sales / 4,106 Retained Orders`) is `₹961.94`. |
| **Net Product COGS** | `SUM(retained_product_cogs) WHERE is_delivered` | Retained units on delivered orders | `₹1,174,973.00` | Product manufacturing cost of net retained units. |
| **Gross Profit & Margin %** | `Net Merchandise Sales - Net COGS` | `₹3,949,725.97 - ₹1,174,973.00` | `₹2,774,752.97` (`70.25%`) | Product margin before logistics, payment gateway fees, and ad spend. |
| **Total Shipping Cost** | `SUM(shipments.shipping_cost)` | All `5,402` shipped orders | `₹407,932.32` | Includes `₹95,217.95` dead-weight forward + reverse shipping cost on `754` RTO orders. |
| **Payment Processing Fees** | `2.0%` Prepaid non-cancelled + `₹25` COD delivered | All applicable orders | `₹121,100.47` | Gateway fee on prepaid (`₹75,875.47`) + COD collection fee (`₹45,225.00`). |
| **Contribution Profit (CM2)** | `Gross Profit + Earned Shipping Rev (₹40,033) - Shipping Cost - Payment Fees` | All orders in scope | `₹2,285,753.18` | Variable profit before fixed overhead and marketing spend. |
| **Contribution Margin %** | `Contribution Profit / Net Merchandise Sales` | `₹2,285,753.18 / ₹3,949,725.97` | `57.87%` | Returns `NA` when Net Merchandise Sales $\le 0$. |
| **Paid Media Spend** | `SUM(marketing_spend.spend)` | `7` campaigns across `184` days | `₹7,265,150.14` | `33,211,538` impressions, `723,919` clicks (`CTR = 2.18%`, `CPC = ₹10.04`). |
| **New Customers Acquired** | `COUNT(DISTINCT customer_id) WHERE is_new_customer_order` | First delivered order in window | `2,466` (`1,544` paid) | First eligible purchase defined using delivered cohort order. |
| **Blended vs Paid CAC** | `Ad Spend / New Customers` | Blended: `2,466`; Paid: `1,544` | `₹2,946.13` / `₹4,705.41` | Blended divides total paid spend by all new customers; Paid CAC divides by campaign-tagged new customers. |
| **Attributed ROAS** | `Campaign-Attributed Net Sales / Paid Media Spend` | `₹1,827,890.65 / ₹7,265,150.14` | `0.2516x` | Observational last-touch order campaign tag; **not** causal incremental lift. |
| **Blended MER** | `Total Net Merchandise Sales / Total Paid Media Spend` | `₹3,949,725.97 / ₹7,265,150.14` | `0.5437x` | Blended top-line efficiency ratio across paid and organic/direct channels. |
| **Session Conversion Rate** | `Converted Sessions / Eligible Sessions` | `6,500 / 48,000` | `13.54%` | Session-level denominator (`78.42%` view rate, `32.22%` ATC rate, `65.94%` checkout completion). |
| **Repeat Purchase Rate** | `Customers with 2+ Delivered Orders / Customers with 1+ Delivered Order` | `1,298 / 2,466` | `52.64%` | Evaluated within the 6-month observation window (`2026-05-01` to `2026-10-31`). |
| **Observed 6M Customer LTV** | `Total Net Merchandise Sales / Active Delivered Customers` | `₹3,949,725.97 / 2,466` | `₹1,601.67` | Historical cumulative revenue in window (`₹859.25` first-time vs `₹2,269.74` repeat), not predictive CLV. |
| **Inventory Sell-Through Rate** | `Total Units Sold / (Initial Opening Stock + Total Units Received)` | SKU grain across 184 days | `77.06%` – `99.50%` | Snapshot stock turnover; `closing_stock <= reorder_point` is an operational signal, not proof of lost sales. |
