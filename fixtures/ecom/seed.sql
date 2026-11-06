-- Hygieia demo fixture（ecom）：原创合成电商小数据，可眼算核对
-- 参考日：2026-08-01；「上个月」= 2026-07；30 天活跃窗口 = order_date >= '2026-07-02'
-- 关键数字：全部订单总额 1860；非取消订单总额 1760；取消订单 100（均在 7 月）
-- 7 月总额 1210、7 月净额 1110；客单价 155（含取消）/ 176（不含取消）；活跃客户 5/6

INSERT INTO customers (id, name, city) VALUES
  (1, '张三', '北京'),
  (2, '李四', '上海'),
  (3, '王五', '广州'),
  (4, '赵六', '深圳'),
  (5, '孙七', '杭州'),
  (6, '周八', '成都');

INSERT INTO products (id, name, category, price, status) VALUES
  ('p1', '手机', '电子', 1999, 'active'),
  ('p2', '耳机', '电子', 399,  'active'),
  ('p3', '运动鞋', '服饰', 599, 'active'),
  ('p4', '背包', '箱包', 299,  'active'),
  ('p5', '相机', '电子', 4999, 'inactive');

INSERT INTO orders (id, customer_id, order_date, status, total_amount, net_amount) VALUES
  ('o101', 1, '2026-07-03', 'delivered', 200, 200),
  ('o102', 2, '2026-07-05', 'delivered', 150, 150),
  ('o103', 3, '2026-07-08', 'delivered', 180, 180),
  ('o104', 4, '2026-07-10', 'delivered', 120, 120),
  ('o105', 5, '2026-07-12', 'delivered', 90,  90),
  ('o106', 1, '2026-07-15', 'delivered', 130, 130),
  ('o107', 2, '2026-07-18', 'delivered', 110, 110),
  ('o108', 3, '2026-07-21', 'delivered', 130, 130),
  ('o109', 4, '2026-07-25', 'canceled', 60,  0),
  ('o110', 5, '2026-07-28', 'canceled', 40,  0),
  ('o201', 5, '2026-06-10', 'delivered', 300, 300),
  ('o202', 6, '2026-06-15', 'delivered', 350, 350);

INSERT INTO order_items (id, order_id, product_id, quantity, price) VALUES
  (1,  'o101', 'p1', 1, 200),
  (2,  'o102', 'p2', 1, 150),
  (3,  'o103', 'p3', 1, 180),
  (4,  'o104', 'p4', 1, 120),
  (5,  'o105', 'p1', 1, 90),
  (6,  'o106', 'p2', 1, 130),
  (7,  'o107', 'p3', 1, 110),
  (8,  'o108', 'p4', 1, 130),
  (9,  'o109', 'p1', 1, 60),
  (10, 'o110', 'p2', 1, 40),
  (11, 'o201', 'p3', 1, 300),
  (12, 'o202', 'p4', 1, 350);

INSERT INTO payments (id, order_id, method, amount, status) VALUES
  (1,  'o101', 'credit_card', 200, 'success'),
  (2,  'o102', 'wechat',      150, 'success'),
  (3,  'o103', 'alipay',      180, 'success'),
  (4,  'o104', 'credit_card', 120, 'success'),
  (5,  'o105', 'wechat',      90,  'success'),
  (6,  'o106', 'alipay',      130, 'success'),
  (7,  'o107', 'credit_card', 110, 'success'),
  (8,  'o108', 'wechat',      130, 'success'),
  (9,  'o109', 'credit_card', 60,  'refunded'),
  (10, 'o110', 'alipay',      40,  'refunded'),
  (11, 'o201', 'credit_card', 300, 'success'),
  (12, 'o202', 'wechat',      350, 'success');

INSERT INTO reviews (id, order_id, customer_id, product_id, rating, comment) VALUES
  (1, 'o101', 1, 'p1', 4, '很好'),
  (2, 'o102', 2, 'p2', 5, '不错'),
  (3, 'o103', 3, 'p1', 4, '满意'),
  (4, 'o104', 4, 'p3', 3, '一般'),
  (5, 'o105', 5, 'p4', 2, '不满意');
