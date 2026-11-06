-- adapt_dbt_mini：只读适配器演示 fixture 的最小 schema
-- 只用于 audit 的 R4 引用校验（orders.* / customers.* 列必须存在）
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    total_amount NUMERIC(12, 2) NOT NULL,
    net_amount NUMERIC(12, 2) NOT NULL,
    status TEXT NOT NULL,
    order_date TEXT NOT NULL
);

CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);
