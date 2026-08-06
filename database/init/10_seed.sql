SET search_path TO commerce, public;

INSERT INTO customers (customer_id, email, full_name, region, country_code, created_at) VALUES
    (1, 'alice@example.test', 'Alice Nguyen', 'West', 'US', '2025-01-04 10:00:00+00'),
    (2, 'bob@example.test', 'Bob Martinez', 'Northeast', 'US', '2025-01-15 15:30:00+00'),
    (3, 'carol@example.test', 'Carol Singh', 'South', 'US', '2025-02-02 09:15:00+00'),
    (4, 'dan@example.test', 'Dan Okafor', 'Midwest', 'US', '2025-03-18 12:45:00+00'),
    (5, 'eva@example.test', 'Eva Rossi', 'International', 'IT', '2025-04-20 08:20:00+00'),
    (6, 'frank@example.test', 'Frank Brown', 'West', 'US', '2025-05-11 17:05:00+00')
ON CONFLICT (customer_id) DO NOTHING;

INSERT INTO categories (category_id, parent_category_id, name) VALUES
    (1, NULL, 'Electronics'),
    (2, NULL, 'Home'),
    (3, NULL, 'Outdoors'),
    (4, NULL, 'Apparel'),
    (5, 1, 'Accessories')
ON CONFLICT (category_id) DO NOTHING;

INSERT INTO products (product_id, category_id, sku, name, unit_price_cents, active, launched_at, discontinued_at) VALUES
    (1, 5, 'ACC-STAND-01', 'Adjustable Laptop Stand', 6500, true, '2025-01-01', NULL),
    (2, 5, 'ACC-KEY-02', 'Mechanical Keyboard', 12000, true, '2025-01-01', NULL),
    (3, 1, 'ELE-MON-27', '27 Inch Monitor', 25000, true, '2025-01-01', NULL),
    (4, 2, 'HOM-ESP-01', 'Compact Espresso Maker', 18000, true, '2025-01-01', NULL),
    (5, 3, 'OUT-MUG-24', 'Insulated Trail Mug', 2400, true, '2025-01-01', NULL),
    (6, 3, 'OUT-SHOE-09', 'Trail Running Shoes', 9000, true, '2025-01-01', NULL),
    (7, 4, 'APP-SHIRT-LN', 'Linen Shirt', 4500, true, '2025-01-01', NULL),
    (8, 1, 'ELE-CAM-RETRO', 'Retro Digital Camera', 15000, false, '2024-06-01', '2025-12-31')
ON CONFLICT (product_id) DO NOTHING;

INSERT INTO orders (
    order_id,
    customer_id,
    order_number,
    ordered_at,
    status,
    billing_region,
    currency,
    subtotal_cents,
    discount_cents,
    tax_cents,
    shipping_cents,
    total_cents
) VALUES
    (1, 1, 'ORD-1001', '2026-01-10 16:23:00+00', 'delivered', 'West', 'USD', 11300, 500, 864, 500, 12164),
    (2, 2, 'ORD-1002', '2026-02-15 20:11:00+00', 'delivered', 'Northeast', 'USD', 37000, 2000, 2800, 0, 37800),
    (3, 3, 'ORD-1003', '2026-03-05 14:05:00+00', 'cancelled', 'South', 'USD', 18000, 0, 0, 0, 18000),
    (4, 4, 'ORD-1004', '2026-04-20 18:40:00+00', 'shipped', 'Midwest', 'USD', 11400, 0, 912, 700, 13012),
    (5, 1, 'ORD-1005', '2026-05-12 11:19:00+00', 'delivered', 'West', 'USD', 9000, 0, 720, 500, 10220),
    (6, 5, 'ORD-1006', '2026-06-01 08:55:00+00', 'pending', 'International', 'USD', 12000, 0, 960, 0, 12960),
    (7, 6, 'ORD-1007', '2025-11-21 22:10:00+00', 'delivered', 'West', 'USD', 20400, 1000, 1552, 800, 21752),
    (8, 2, 'ORD-1008', '2026-07-08 19:30:00+00', 'delivered', 'Northeast', 'USD', 15500, 0, 1240, 500, 17240),
    (9, 5, 'ORD-1009', '2026-07-25 13:44:00+00', 'cancelled', 'International', 'USD', 25000, 0, 0, 0, 25000)
ON CONFLICT (order_id) DO NOTHING;

INSERT INTO order_items (
    order_item_id,
    order_id,
    product_id,
    quantity,
    unit_price_cents,
    discount_cents,
    line_total_cents
) VALUES
    (1, 1, 1, 1, 6500, 0, 6500),
    (2, 1, 5, 2, 2400, 0, 4800),
    (3, 2, 3, 1, 25000, 0, 25000),
    (4, 2, 2, 1, 12000, 0, 12000),
    (5, 3, 4, 1, 18000, 0, 18000),
    (6, 4, 6, 1, 9000, 0, 9000),
    (7, 4, 5, 1, 2400, 0, 2400),
    (8, 5, 7, 2, 4500, 0, 9000),
    (9, 6, 2, 1, 12000, 0, 12000),
    (10, 7, 4, 1, 18000, 0, 18000),
    (11, 7, 5, 1, 2400, 0, 2400),
    (12, 8, 1, 1, 6500, 0, 6500),
    (13, 8, 6, 1, 9000, 0, 9000),
    (14, 9, 3, 1, 25000, 0, 25000)
ON CONFLICT (order_item_id) DO NOTHING;

INSERT INTO payments (
    payment_id,
    order_id,
    provider_payment_id,
    payment_method,
    status,
    amount_cents,
    paid_at
) VALUES
    (1, 1, 'pay_1001_capture', 'card', 'captured', 12164, '2026-01-10 16:24:00+00'),
    (2, 2, 'pay_1002_capture', 'paypal', 'captured', 37800, '2026-02-15 20:12:00+00'),
    (3, 3, 'pay_1003_failed', 'card', 'failed', 18000, NULL),
    (4, 4, 'pay_1004_capture', 'card', 'captured', 13012, '2026-04-20 18:42:00+00'),
    (5, 5, 'pay_1005_capture', 'card', 'partially_refunded', 10220, '2026-05-12 11:20:00+00'),
    (6, 6, 'pay_1006_auth', 'bank_transfer', 'authorized', 12960, NULL),
    (7, 7, 'pay_1007_capture', 'gift_card', 'refunded', 21752, '2025-11-21 22:11:00+00'),
    (8, 8, 'pay_1008_failed', 'card', 'failed', 17240, NULL),
    (9, 8, 'pay_1008_retry_capture', 'card', 'captured', 17240, '2026-07-08 19:36:00+00'),
    (10, 9, 'pay_1009_failed', 'paypal', 'failed', 25000, NULL)
ON CONFLICT (payment_id) DO NOTHING;

INSERT INTO refunds (
    refund_id,
    payment_id,
    external_refund_id,
    status,
    reason,
    amount_cents,
    refunded_at
) VALUES
    (1, 5, 'ref_1005_partial', 'succeeded', 'damaged_item', 4500, '2026-05-18 09:00:00+00'),
    (2, 7, 'ref_1007_full', 'succeeded', 'customer_return', 21752, '2025-11-29 12:00:00+00')
ON CONFLICT (refund_id) DO NOTHING;

INSERT INTO shipments (
    shipment_id,
    order_id,
    shipment_number,
    carrier,
    tracking_number,
    status,
    shipped_at,
    delivered_at
) VALUES
    (1, 1, 'SHP-1001', 'UPS', '1Z1001', 'delivered', '2026-01-11 09:00:00+00', '2026-01-13 17:10:00+00'),
    (2, 2, 'SHP-1002', 'FedEx', 'FX1002', 'delivered', '2026-02-16 10:00:00+00', '2026-02-18 15:30:00+00'),
    (3, 3, 'SHP-1003', 'USPS', NULL, 'cancelled', NULL, NULL),
    (4, 4, 'SHP-1004', 'UPS', '1Z1004', 'shipped', '2026-04-21 13:00:00+00', NULL),
    (5, 5, 'SHP-1005', 'USPS', 'US1005', 'delivered', '2026-05-13 09:25:00+00', '2026-05-16 18:40:00+00'),
    (6, 7, 'SHP-1007', 'DHL', 'DHL1007', 'returned', '2025-11-22 08:00:00+00', '2025-11-25 14:00:00+00'),
    (7, 8, 'SHP-1008', 'LocalCourier', 'LC1008', 'delivered', '2026-07-09 08:30:00+00', '2026-07-09 18:45:00+00')
ON CONFLICT (shipment_id) DO NOTHING;

SELECT setval(pg_get_serial_sequence('customers', 'customer_id'), (SELECT max(customer_id) FROM customers));
SELECT setval(pg_get_serial_sequence('categories', 'category_id'), (SELECT max(category_id) FROM categories));
SELECT setval(pg_get_serial_sequence('products', 'product_id'), (SELECT max(product_id) FROM products));
SELECT setval(pg_get_serial_sequence('orders', 'order_id'), (SELECT max(order_id) FROM orders));
SELECT setval(pg_get_serial_sequence('order_items', 'order_item_id'), (SELECT max(order_item_id) FROM order_items));
SELECT setval(pg_get_serial_sequence('payments', 'payment_id'), (SELECT max(payment_id) FROM payments));
SELECT setval(pg_get_serial_sequence('refunds', 'refund_id'), (SELECT max(refund_id) FROM refunds));
SELECT setval(pg_get_serial_sequence('shipments', 'shipment_id'), (SELECT max(shipment_id) FROM shipments));
