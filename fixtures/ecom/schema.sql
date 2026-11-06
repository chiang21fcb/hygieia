-- Hygieia demo fixture（ecom）：原创合成演示数据，无外部数据来源
-- 6 表电商 DDL（SQLite 友好子集；v0 只支持单 schema 目录、单方言）

CREATE TABLE customers (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  city TEXT
);

CREATE TABLE products (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  category TEXT,
  price REAL,
  status TEXT NOT NULL
);

CREATE TABLE orders (
  id TEXT PRIMARY KEY,
  customer_id INTEGER NOT NULL,
  order_date TEXT NOT NULL,
  status TEXT NOT NULL,
  total_amount REAL NOT NULL,
  net_amount REAL NOT NULL
);

CREATE TABLE order_items (
  id INTEGER PRIMARY KEY,
  order_id TEXT NOT NULL,
  product_id TEXT NOT NULL,
  quantity INTEGER NOT NULL,
  price REAL NOT NULL
);

CREATE TABLE payments (
  id INTEGER PRIMARY KEY,
  order_id TEXT NOT NULL,
  method TEXT NOT NULL,
  amount REAL NOT NULL,
  status TEXT NOT NULL
);

CREATE TABLE reviews (
  id INTEGER PRIMARY KEY,
  order_id TEXT NOT NULL,
  customer_id INTEGER NOT NULL,
  product_id TEXT NOT NULL,
  rating INTEGER NOT NULL,
  comment TEXT
);
