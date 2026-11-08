-- Minimal warehouse schema for the consumer CI example.
-- Hygieia uses it to verify that metric expressions reference real tables/columns.
CREATE TABLE orders (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    amount      REAL    NOT NULL,
    status      TEXT    NOT NULL,   -- 'paid' | 'cancelled'
    created_at  TEXT    NOT NULL
);
