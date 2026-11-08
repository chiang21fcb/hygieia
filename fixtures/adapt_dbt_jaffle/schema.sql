-- Minimal schema for the jaffle-shaped dbt Semantic Layer fixture.
CREATE TABLE orders (
  order_id INTEGER PRIMARY KEY,
  customer_id INTEGER,
  order_date DATE,
  status TEXT,
  amount REAL,
  is_food_order BOOLEAN
);

CREATE TABLE customers (
  customer_id INTEGER PRIMARY KEY,
  first_name TEXT
);
