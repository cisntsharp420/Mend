CREATE TABLE products (id SERIAL PRIMARY KEY, name TEXT NOT NULL, price NUMERIC(10,2) NOT NULL);
CREATE TABLE orders (
  id SERIAL PRIMARY KEY,
  product_id INT NOT NULL REFERENCES products(id),
  qty INT NOT NULL,
  total NUMERIC(10,2) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO products (name, price)
  SELECT 'product-' || g, round((random() * 200 + 5)::numeric, 2) FROM generate_series(1, 50) g;
INSERT INTO orders (product_id, qty, total)
  SELECT (random() * 49 + 1)::int, (random() * 3 + 1)::int, round((random() * 500)::numeric, 2)
  FROM generate_series(1, 1000);

-- Application role (non-superuser), so superuser_reserved_connections keep admin access possible.
CREATE ROLE shop_app LOGIN PASSWORD 'shop-secret';
GRANT SELECT, INSERT ON products, orders TO shop_app;
GRANT USAGE ON SEQUENCE orders_id_seq TO shop_app;
