-- DuckDB-compatible analytical schema for D2C Growth & Profitability Control Tower.
-- Enforces one row per declared grain. Do not join raw 1:N tables without pre-aggregation.

CREATE TABLE IF NOT EXISTS customers (
  customer_id VARCHAR PRIMARY KEY,
  signup_date DATE NOT NULL,
  first_touch_channel VARCHAR NOT NULL,
  first_touch_campaign_id VARCHAR,
  city_tier VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
  product_id VARCHAR PRIMARY KEY,
  product_name VARCHAR NOT NULL,
  category VARCHAR NOT NULL,
  unit_cogs DECIMAL(12,2) NOT NULL,
  list_price DECIMAL(12,2) NOT NULL,
  launch_date DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
  order_id VARCHAR PRIMARY KEY,
  customer_id VARCHAR NOT NULL,
  order_date TIMESTAMP NOT NULL,
  order_status VARCHAR NOT NULL,
  payment_mode VARCHAR NOT NULL,
  channel VARCHAR NOT NULL,
  campaign_id VARCHAR,
  currency VARCHAR NOT NULL,
  discount_amount DECIMAL(12,2) NOT NULL,
  shipping_revenue DECIMAL(12,2) NOT NULL,
  tax_amount DECIMAL(12,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
  order_item_id VARCHAR PRIMARY KEY,
  order_id VARCHAR NOT NULL,
  product_id VARCHAR NOT NULL,
  quantity INTEGER NOT NULL,
  unit_selling_price DECIMAL(12,2) NOT NULL,
  unit_discount DECIMAL(12,2) NOT NULL,
  line_refund_amount DECIMAL(12,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  session_id VARCHAR PRIMARY KEY,
  customer_id VARCHAR,
  session_start TIMESTAMP NOT NULL,
  channel VARCHAR NOT NULL,
  campaign_id VARCHAR,
  device VARCHAR NOT NULL,
  product_view BOOLEAN NOT NULL,
  add_to_cart BOOLEAN NOT NULL,
  checkout_started BOOLEAN NOT NULL,
  converted BOOLEAN NOT NULL,
  order_id VARCHAR
);

CREATE TABLE IF NOT EXISTS marketing_spend (
  date DATE NOT NULL,
  platform VARCHAR NOT NULL,
  channel VARCHAR NOT NULL,
  campaign_id VARCHAR NOT NULL,
  spend DECIMAL(12,2) NOT NULL,
  impressions BIGINT NOT NULL,
  clicks BIGINT NOT NULL,
  currency VARCHAR NOT NULL,
  PRIMARY KEY (date, platform, channel, campaign_id)
);

CREATE TABLE IF NOT EXISTS shipments (
  shipment_id VARCHAR PRIMARY KEY,
  order_id VARCHAR NOT NULL,
  shipped_at TIMESTAMP NOT NULL,
  delivered_at TIMESTAMP,
  shipment_status VARCHAR NOT NULL,
  shipping_cost DECIMAL(12,2) NOT NULL,
  courier_partner VARCHAR NOT NULL,
  rto_reason VARCHAR
);

CREATE TABLE IF NOT EXISTS returns (
  return_id VARCHAR PRIMARY KEY,
  order_id VARCHAR NOT NULL,
  order_item_id VARCHAR,
  return_requested_at TIMESTAMP NOT NULL,
  return_reason VARCHAR NOT NULL,
  refund_amount DECIMAL(12,2) NOT NULL,
  return_status VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory_snapshots (
  snapshot_date DATE NOT NULL,
  product_id VARCHAR NOT NULL,
  opening_stock INTEGER NOT NULL,
  units_received INTEGER NOT NULL,
  units_sold INTEGER NOT NULL,
  closing_stock INTEGER NOT NULL,
  reorder_point INTEGER NOT NULL,
  PRIMARY KEY (snapshot_date, product_id)
);
