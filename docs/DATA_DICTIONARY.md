# Data Dictionary — Source & Canonical Tables

All data is **100% deterministic synthetic data** (`random_seed = 42`, `Currency = INR`, `Timezone = Asia/Kolkata`). All customer, order, session, shipment, and return IDs are pseudonymous.

---

## 1. Source Tables (`data/raw/*.csv` & DuckDB)

### 1.1 `customers.csv` — Grain: 1 row per customer (`3,200` rows)
| Column | Type | Nullable | Description |
|---|---|---|---|
| `customer_id` | `VARCHAR` (PK) | No | Pseudonymous customer identifier (`CUST-00001`..`CUST-03200`) |
| `signup_date` | `DATE` | No | Customer registration date (`YYYY-MM-DD`) |
| `first_touch_channel` | `VARCHAR` | No | Initial acquisition channel (`Paid Social`, `Paid Search`, `Influencer`, `Organic Search`, `Direct`, `Marketplace`) |
| `first_touch_campaign_id` | `VARCHAR` | Yes | Initial paid campaign ID (`CMP-*`), empty for non-paid channels |
| `city_tier` | `VARCHAR` | No | Indian urban classification (`Tier 1`, `Tier 2`, `Tier 3`) |

### 1.2 `products.csv` — Grain: 1 row per SKU (`8` rows)
| Column | Type | Nullable | Description |
|---|---|---|---|
| `product_id` | `VARCHAR` (PK) | No | SKU identifier (`SKU-FW-01`, `SKU-FW-02`, `SKU-MO-01`, `SKU-MO-02`, `SKU-SS-01`, `SKU-SS-02`, `SKU-SR-01`, `SKU-KT-01`) |
| `product_name` | `VARCHAR` | No | Full skincare product name |
| `category` | `VARCHAR` | No | Product category (`Face Wash`, `Moisturiser`, `Sunscreen`, `Serum`, `Bundles`) |
| `unit_cogs` | `DECIMAL(12,2)` | No | Manufacturing & packaging cost per unit in `INR` |
| `list_price` | `DECIMAL(12,2)` | No | Standard MRP / selling price per unit in `INR` |
| `launch_date` | `DATE` | No | Product launch date (`YYYY-MM-DD`) |

### 1.3 `orders.csv` — Grain: 1 row per order header (`6,500` rows)
| Column | Type | Nullable | Description |
|---|---|---|---|
| `order_id` | `VARCHAR` (PK) | No | Unique order identifier (`ORD-000001`..`ORD-006500`) |
| `customer_id` | `VARCHAR` (FK) | No | References `customers.customer_id` |
| `order_date` | `TIMESTAMP` | No | Order creation timestamp (`YYYY-MM-DD HH:MM:SS`, `Asia/Kolkata`) |
| `order_status` | `VARCHAR` | No | Current lifecycle status: `placed`, `confirmed`, `shipped`, `delivered`, `cancelled`, `rto`, `returned`, `partially_refunded` |
| `payment_mode` | `VARCHAR` | No | Payment method: `prepaid` or `cod` (Cash on Delivery) |
| `channel` | `VARCHAR` | No | Order acquisition channel (`Paid Social`, `Paid Search`, `Influencer`, `Organic Search`, `Direct`, `Email/CRM`, `Marketplace`) |
| `campaign_id` | `VARCHAR` | Yes | Last-touch attributed campaign ID (`CMP-*`), empty for organic/direct/CRM/marketplace |
| `currency` | `VARCHAR` | No | Always `INR` |
| `discount_amount` | `DECIMAL(12,2)` | No | Total order promotional discount in `INR` (reconciles with `SUM(quantity * unit_discount)` in `order_items`) |
| `shipping_revenue` | `DECIMAL(12,2)` | No | Shipping fee charged to customer (`₹49.00` for net order value `< ₹499`, else `₹0.00`) |
| `tax_amount` | `DECIMAL(12,2)` | No | GST amount (`18%` of net merchandise value before refund) in `INR` |

### 1.4 `order_items.csv` — Grain: 1 row per SKU line item per order (`9,722` rows)
| Column | Type | Nullable | Description |
|---|---|---|---|
| `order_item_id` | `VARCHAR` (PK) | No | Unique order line identifier (`ITEM-000001`..`ITEM-009722`) |
| `order_id` | `VARCHAR` (FK) | No | References `orders.order_id` |
| `product_id` | `VARCHAR` (FK) | No | References `products.product_id` |
| `quantity` | `INTEGER` | No | Units ordered on this line (`>= 1`) |
| `unit_selling_price` | `DECIMAL(12,2)` | No | Selling price per unit before discount (`INR`) |
| `unit_discount` | `DECIMAL(12,2)` | No | Promotional discount per unit (`INR`, `0 <= unit_discount <= unit_selling_price`) |
| `line_refund_amount` | `DECIMAL(12,2)` | No | Customer refund amount for this line (`INR`, `> 0` only on `returned` / `partially_refunded` orders) |

### 1.5 `sessions.csv` — Grain: 1 row per website/storefront session (`48,000` rows)
| Column | Type | Nullable | Description |
|---|---|---|---|
| `session_id` | `VARCHAR` (PK) | No | Unique session identifier (`SES-0000001`..`SES-0048000`) |
| `customer_id` | `VARCHAR` (FK) | Yes | References `customers.customer_id` when authenticated/known; empty for anonymous browsers |
| `session_start` | `TIMESTAMP` | No | Session start timestamp (`YYYY-MM-DD HH:MM:SS`) |
| `channel` | `VARCHAR` | No | Traffic source channel |
| `campaign_id` | `VARCHAR` | Yes | Campaign tag for paid traffic; empty for organic/direct |
| `device` | `VARCHAR` | No | User device category (`mobile`, `desktop`, `tablet`) |
| `product_view` | `BOOLEAN` | No | `True` if session viewed at least one product page |
| `add_to_cart` | `BOOLEAN` | No | `True` if session added at least one item to cart (implies `product_view = True`) |
| `checkout_started` | `BOOLEAN` | No | `True` if session initiated checkout (implies `add_to_cart = True`) |
| `converted` | `BOOLEAN` | No | `True` if session completed an order (implies `checkout_started = True`) |
| `order_id` | `VARCHAR` (FK) | Yes | References `orders.order_id` when `converted = True`; empty otherwise |

### 1.6 `marketing_spend.csv` — Grain: 1 row per campaign per date (`1,288` rows)
| Column | Type | Nullable | Description |
|---|---|---|---|
| `date` | `DATE` (PK) | No | Spend date (`2026-05-01` to `2026-10-31`) |
| `platform` | `VARCHAR` (PK) | No | Ad platform (`Meta Ads`, `Google Ads`, `Creator Network`) |
| `channel` | `VARCHAR` (PK) | No | Marketing channel (`Paid Social`, `Paid Search`, `Influencer`) |
| `campaign_id` | `VARCHAR` (PK) | No | Campaign identifier (`7` campaigns across 184 days) |
| `spend` | `DECIMAL(12,2)` | No | Daily media spend in `INR` |
| `impressions` | `BIGINT` | No | Ad impressions served |
| `clicks` | `BIGINT` | No | Ad clicks recorded (`clicks <= impressions`) |
| `currency` | `VARCHAR` | No | Always `INR` |

### 1.7 `shipments.csv` — Grain: 1 row per shipment (`5,402` rows)
| Column | Type | Nullable | Description |
|---|---|---|---|
| `shipment_id` | `VARCHAR` (PK) | No | Unique shipment identifier (`SHP-000001`..`SHP-005402`) |
| `order_id` | `VARCHAR` (FK) | No | References `orders.order_id` (present for all shipped lifecycle orders) |
| `shipped_at` | `TIMESTAMP` | No | Warehouse dispatch timestamp (`shipped_at >= order_date`) |
| `delivered_at` | `TIMESTAMP` | Yes | Doorstep delivery timestamp (`delivered_at >= shipped_at`); empty for `in_transit` and `rto` |
| `shipment_status` | `VARCHAR` | No | `in_transit`, `delivered`, or `rto` |
| `shipping_cost` | `DECIMAL(12,2)` | No | Courier logistics cost incurred by brand in `INR` (`rto` includes forward + reverse charges) |
| `courier_partner` | `VARCHAR` | No | Logistics provider (`Delhivery`, `BlueDart`, `Ecom Express`, `Shadowfax`) |
| `rto_reason` | `VARCHAR` | Yes | Populated when `shipment_status = 'rto'` (`Customer Refused Delivery`, `Address Incomplete / Unreachable`, etc.) |

### 1.8 `returns.csv` — Grain: 1 row per post-delivery return case (`643` rows)
| Column | Type | Nullable | Description |
|---|---|---|---|
| `return_id` | `VARCHAR` (PK) | No | Unique return case identifier (`RET-000001`..`RET-000643`) |
| `order_id` | `VARCHAR` (FK) | No | References `orders.order_id` |
| `order_item_id` | `VARCHAR` (FK) | Yes | References `order_items.order_item_id` |
| `return_requested_at` | `TIMESTAMP` | No | Timestamp of customer return request (`return_requested_at >= delivered_at`) |
| `return_reason` | `VARCHAR` | No | Reason (`Skin Sensitivity / Mild Reaction`, `Packaging Damaged in Transit`, `Product Texture / Fragrance Preference`, `Wrong Variant Ordered`) |
| `refund_amount` | `DECIMAL(12,2)` | No | Refund issued to customer in `INR` |
| `return_status` | `VARCHAR` | No | `refunded`, `approved`, `requested`, or `rejected` |

### 1.9 `inventory_snapshots.csv` — Grain: 1 row per SKU per date (`1,472` rows)
| Column | Type | Nullable | Description |
|---|---|---|---|
| `snapshot_date` | `DATE` (PK) | No | Daily snapshot date (`2026-05-01` to `2026-10-31`) |
| `product_id` | `VARCHAR` (PK, FK) | No | References `products.product_id` |
| `opening_stock` | `INTEGER` | No | Opening warehouse units at start of day |
| `units_received` | `INTEGER` | No | Replenishment batch units received on that day |
| `units_sold` | `INTEGER` | No | Units allocated/dispatched on that day |
| `closing_stock` | `INTEGER` | No | Exact identity: `opening_stock + units_received - units_sold` |
| `reorder_point` | `INTEGER` | No | Minimum safety threshold triggering replenishment alert |

---

## 2. Derived Canonical Tables (`data/processed/` & DuckDB)
- **`canonical_orders` (`6,500` rows, 1 row per `order_id`)**: Enriches `orders` with customer attributes (`city_tier`, `signup_date`, `first_touch_channel`), pre-aggregated item totals (`sku_count`, `total_units`, `gross_item_revenue`, `retained_product_cogs`), pre-aggregated shipment facts (`shipping_cost`, `courier_partner`, `rto_reason`), pre-aggregated return facts (`effective_refund_amount`, `return_reason`), lifecycle flags (`is_shipped`, `is_delivered`, `is_retained_delivered`, `is_rto`, `is_cancelled`, `is_returned_any`), unit economics (`net_merchandise_sales`, `earned_shipping_revenue`, `net_cogs`, `payment_fee`, `contribution_profit`), and customer cohort fields (`customer_delivered_seq`, `is_new_customer_order`, `first_delivered_date`, `cohort_month`).
- **`canonical_order_items` (`9,722` rows, 1 row per `order_item_id`)**: Enriches `order_items` with product metadata and allocates order-level shipping revenue, shipping cost, and payment fees proportionally by `gross_line_revenue` share so SKU-level `line_contribution_profit` sums to order-level `contribution_profit`.
