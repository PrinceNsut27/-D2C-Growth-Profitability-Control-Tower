-- Core analytical SQL queries for D2C Growth & Profitability Control Tower (DuckDB).
-- All multi-fact joins pre-aggregate order_items, shipments, and returns to order_id grain
-- before joining to orders so row multiplication / revenue duplication cannot occur.

-- 1. Executive Business Performance & Unit Economics Summary
-- [QUERY: executive_kpis]
SELECT
    COUNT(DISTINCT order_id) AS placed_orders,
    COUNT(DISTINCT CASE WHEN is_shipped THEN order_id END) AS shipped_orders,
    COUNT(DISTINCT CASE WHEN is_delivered THEN order_id END) AS delivered_orders,
    COUNT(DISTINCT CASE WHEN is_retained_delivered THEN order_id END) AS retained_delivered_orders,
    COUNT(DISTINCT CASE WHEN is_cancelled THEN order_id END) AS cancelled_orders,
    COUNT(DISTINCT CASE WHEN is_rto THEN order_id END) AS rto_orders,
    COUNT(DISTINCT CASE WHEN is_returned_any THEN order_id END) AS returned_orders,
    COALESCE(SUM(total_units), 0) AS placed_units,
    COALESCE(SUM(CASE WHEN is_delivered THEN total_units ELSE 0 END), 0) AS delivered_units,
    COALESCE(ROUND(SUM(gross_item_revenue), 2), 0.0) AS placed_gmv,
    COALESCE(ROUND(SUM(CASE WHEN is_delivered THEN gross_item_revenue ELSE 0 END), 2), 0.0) AS delivered_gross_revenue,
    COALESCE(ROUND(SUM(CASE WHEN is_delivered THEN discount_amount ELSE 0 END), 2), 0.0) AS delivered_discounts,
    COALESCE(ROUND(SUM(CASE WHEN is_delivered THEN effective_refund_amount ELSE 0 END), 2), 0.0) AS refund_amount,
    COALESCE(ROUND(SUM(net_merchandise_sales), 2), 0.0) AS net_merchandise_sales,
    COALESCE(ROUND(SUM(net_cogs), 2), 0.0) AS net_cogs,
    COALESCE(ROUND(SUM(net_merchandise_sales - net_cogs), 2), 0.0) AS gross_profit,
    COALESCE(ROUND(SUM(shipping_cost), 2), 0.0) AS shipping_cost,
    COALESCE(ROUND(SUM(payment_fee), 2), 0.0) AS payment_fees,
    COALESCE(ROUND(SUM(contribution_profit), 2), 0.0) AS contribution_profit,
    CASE WHEN SUM(net_merchandise_sales) > 0
         THEN ROUND(SUM(contribution_profit) / SUM(net_merchandise_sales), 4)
         ELSE NULL END AS contribution_margin_pct,
    CASE WHEN COUNT(DISTINCT CASE WHEN is_delivered THEN order_id END) > 0
         THEN ROUND(SUM(net_merchandise_sales) / COUNT(DISTINCT CASE WHEN is_delivered THEN order_id END), 2)
         ELSE NULL END AS aov,
    CASE WHEN COUNT(DISTINCT order_id) > 0
         THEN ROUND(CAST(COUNT(DISTINCT CASE WHEN is_cancelled THEN order_id END) AS DOUBLE) / COUNT(DISTINCT order_id), 4)
         ELSE NULL END AS cancellation_rate,
    CASE WHEN COUNT(DISTINCT CASE WHEN is_shipped THEN order_id END) > 0
         THEN ROUND(CAST(COUNT(DISTINCT CASE WHEN is_rto THEN order_id END) AS DOUBLE) / COUNT(DISTINCT CASE WHEN is_shipped THEN order_id END), 4)
         ELSE NULL END AS rto_rate,
    CASE WHEN COUNT(DISTINCT CASE WHEN is_delivered THEN order_id END) > 0
         THEN ROUND(CAST(COUNT(DISTINCT CASE WHEN is_returned_any THEN order_id END) AS DOUBLE) / COUNT(DISTINCT CASE WHEN is_delivered THEN order_id END), 4)
         ELSE NULL END AS return_rate
FROM canonical_orders;

-- 2. Channel Acquisition, CAC, Attributed ROAS & Contribution
-- [QUERY: channel_performance]
WITH spend_by_channel AS (
    SELECT
        channel,
        ROUND(SUM(spend), 2) AS ad_spend,
        SUM(impressions) AS impressions,
        SUM(clicks) AS clicks
    FROM marketing_spend
    GROUP BY channel
),
orders_by_channel AS (
    SELECT
        channel,
        COUNT(DISTINCT order_id) AS placed_orders,
        COUNT(DISTINCT CASE WHEN is_delivered THEN order_id END) AS delivered_orders,
        COUNT(DISTINCT CASE WHEN is_new_customer_order THEN customer_id END) AS new_customers,
        ROUND(SUM(net_merchandise_sales), 2) AS net_merchandise_sales,
        ROUND(SUM(net_cogs), 2) AS net_cogs,
        ROUND(SUM(net_merchandise_sales - net_cogs), 2) AS gross_profit,
        ROUND(SUM(shipping_cost), 2) AS shipping_cost,
        ROUND(SUM(payment_fee), 2) AS payment_fees,
        ROUND(SUM(contribution_profit), 2) AS contribution_profit
    FROM canonical_orders
    GROUP BY channel
)
SELECT
    COALESCE(o.channel, s.channel) AS channel,
    COALESCE(s.ad_spend, 0.0) AS ad_spend,
    COALESCE(o.placed_orders, 0) AS placed_orders,
    COALESCE(o.delivered_orders, 0) AS delivered_orders,
    COALESCE(o.new_customers, 0) AS new_customers,
    COALESCE(o.net_merchandise_sales, 0.0) AS net_merchandise_sales,
    COALESCE(o.gross_profit, 0.0) AS gross_profit,
    COALESCE(o.contribution_profit, 0.0) AS contribution_profit,
    CASE WHEN COALESCE(s.ad_spend, 0.0) > 0 AND COALESCE(o.new_customers, 0) > 0
         THEN ROUND(s.ad_spend / o.new_customers, 2)
         ELSE NULL END AS cac,
    CASE WHEN COALESCE(s.ad_spend, 0.0) > 0
         THEN ROUND(COALESCE(o.net_merchandise_sales, 0.0) / s.ad_spend, 4)
         ELSE NULL END AS attributed_roas
FROM orders_by_channel o
FULL OUTER JOIN spend_by_channel s ON o.channel = s.channel
ORDER BY net_merchandise_sales DESC;

-- 3. Campaign Attribution & Economics
-- [QUERY: campaign_performance]
WITH spend_by_campaign AS (
    SELECT
        campaign_id,
        platform,
        channel,
        ROUND(SUM(spend), 2) AS ad_spend,
        SUM(impressions) AS impressions,
        SUM(clicks) AS clicks
    FROM marketing_spend
    GROUP BY campaign_id, platform, channel
),
orders_by_campaign AS (
    SELECT
        campaign_id,
        COUNT(DISTINCT order_id) AS placed_orders,
        COUNT(DISTINCT CASE WHEN is_delivered THEN order_id END) AS delivered_orders,
        COUNT(DISTINCT CASE WHEN is_new_customer_order THEN customer_id END) AS new_customers,
        ROUND(SUM(net_merchandise_sales), 2) AS net_merchandise_sales,
        ROUND(SUM(contribution_profit), 2) AS contribution_profit
    FROM canonical_orders
    WHERE campaign_id IS NOT NULL AND campaign_id <> ''
    GROUP BY campaign_id
)
SELECT
    s.campaign_id,
    s.platform,
    s.channel,
    s.ad_spend,
    COALESCE(o.placed_orders, 0) AS placed_orders,
    COALESCE(o.delivered_orders, 0) AS delivered_orders,
    COALESCE(o.new_customers, 0) AS new_customers,
    COALESCE(o.net_merchandise_sales, 0.0) AS net_merchandise_sales,
    COALESCE(o.contribution_profit, 0.0) AS contribution_profit,
    CASE WHEN s.ad_spend > 0 AND COALESCE(o.new_customers, 0) > 0
         THEN ROUND(s.ad_spend / o.new_customers, 2)
         ELSE NULL END AS cac,
    CASE WHEN s.ad_spend > 0
         THEN ROUND(COALESCE(o.net_merchandise_sales, 0.0) / s.ad_spend, 4)
         ELSE NULL END AS attributed_roas,
    ROUND(COALESCE(o.contribution_profit, 0.0) - s.ad_spend, 2) AS net_contribution_after_ad_spend
FROM spend_by_campaign s
LEFT JOIN orders_by_campaign o ON s.campaign_id = o.campaign_id
ORDER BY s.ad_spend DESC;

-- 4. Website Conversion Funnel by Channel and Device
-- [QUERY: funnel_by_channel_device]
SELECT
    channel,
    device,
    COUNT(DISTINCT session_id) AS sessions,
    SUM(CASE WHEN product_view THEN 1 ELSE 0 END) AS product_views,
    SUM(CASE WHEN add_to_cart THEN 1 ELSE 0 END) AS add_to_carts,
    SUM(CASE WHEN checkout_started THEN 1 ELSE 0 END) AS checkout_started,
    SUM(CASE WHEN converted THEN 1 ELSE 0 END) AS purchases,
    CASE WHEN COUNT(DISTINCT session_id) > 0
         THEN ROUND(CAST(SUM(CASE WHEN add_to_cart THEN 1 ELSE 0 END) AS DOUBLE) / COUNT(DISTINCT session_id), 4)
         ELSE NULL END AS add_to_cart_rate,
    CASE WHEN SUM(CASE WHEN checkout_started THEN 1 ELSE 0 END) > 0
         THEN ROUND(CAST(SUM(CASE WHEN converted THEN 1 ELSE 0 END) AS DOUBLE) / SUM(CASE WHEN checkout_started THEN 1 ELSE 0 END), 4)
         ELSE NULL END AS checkout_completion_rate,
    CASE WHEN COUNT(DISTINCT session_id) > 0
         THEN ROUND(CAST(SUM(CASE WHEN converted THEN 1 ELSE 0 END) AS DOUBLE) / COUNT(DISTINCT session_id), 4)
         ELSE NULL END AS session_conversion_rate
FROM sessions
GROUP BY channel, device
ORDER BY sessions DESC;

-- 5. SKU Unit Economics & Profitability
-- [QUERY: sku_profitability]
SELECT
    product_id,
    product_name,
    category,
    COUNT(DISTINCT order_id) AS orders_count,
    SUM(CASE WHEN is_delivered THEN quantity ELSE 0 END) AS delivered_units,
    ROUND(SUM(line_net_merchandise_sales), 2) AS net_merchandise_sales,
    ROUND(SUM(line_net_cogs), 2) AS net_cogs,
    ROUND(SUM(line_net_merchandise_sales - line_net_cogs), 2) AS gross_profit,
    ROUND(SUM(line_contribution_profit), 2) AS contribution_profit,
    CASE WHEN SUM(line_net_merchandise_sales) > 0
         THEN ROUND(SUM(line_contribution_profit) / SUM(line_net_merchandise_sales), 4)
         ELSE NULL END AS contribution_margin_pct
FROM canonical_order_items
GROUP BY product_id, product_name, category
ORDER BY net_merchandise_sales DESC;

-- 6. COD vs Prepaid Operational Comparison
-- [QUERY: cod_vs_prepaid]
SELECT
    payment_mode,
    COUNT(DISTINCT order_id) AS placed_orders,
    COUNT(DISTINCT CASE WHEN is_shipped THEN order_id END) AS shipped_orders,
    COUNT(DISTINCT CASE WHEN is_delivered THEN order_id END) AS delivered_orders,
    COUNT(DISTINCT CASE WHEN is_cancelled THEN order_id END) AS cancelled_orders,
    COUNT(DISTINCT CASE WHEN is_rto THEN order_id END) AS rto_orders,
    COUNT(DISTINCT CASE WHEN is_returned_any THEN order_id END) AS returned_orders,
    CASE WHEN COUNT(DISTINCT order_id) > 0
         THEN ROUND(CAST(COUNT(DISTINCT CASE WHEN is_cancelled THEN order_id END) AS DOUBLE) / COUNT(DISTINCT order_id), 4)
         ELSE NULL END AS cancellation_rate,
    CASE WHEN COUNT(DISTINCT CASE WHEN is_shipped THEN order_id END) > 0
         THEN ROUND(CAST(COUNT(DISTINCT CASE WHEN is_rto THEN order_id END) AS DOUBLE) / COUNT(DISTINCT CASE WHEN is_shipped THEN order_id END), 4)
         ELSE NULL END AS rto_rate,
    CASE WHEN COUNT(DISTINCT CASE WHEN is_delivered THEN order_id END) > 0
         THEN ROUND(CAST(COUNT(DISTINCT CASE WHEN is_returned_any THEN order_id END) AS DOUBLE) / COUNT(DISTINCT CASE WHEN is_delivered THEN order_id END), 4)
         ELSE NULL END AS return_rate,
    ROUND(SUM(net_merchandise_sales), 2) AS net_merchandise_sales,
    ROUND(SUM(shipping_cost), 2) AS shipping_cost,
    ROUND(SUM(contribution_profit), 2) AS contribution_profit
FROM canonical_orders
GROUP BY payment_mode
ORDER BY placed_orders DESC;
