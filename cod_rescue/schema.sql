-- COD Order Rescue - SQLite schema (schema version 3).
-- Simulated order system for a synthetic shop. Not a real merchant integration.
-- Money is stored as whole EGP integers (simulation assumption).

-- Marks a database as the synthetic demo store; seeding refuses to overwrite anything else.
CREATE TABLE db_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ---------- Authoritative reference data (simulated sources) ----------

CREATE TABLE products (
    product_id  TEXT PRIMARY KEY,
    name_ar     TEXT NOT NULL,
    name_en     TEXT NOT NULL
);

CREATE TABLE variants (
    sku              TEXT PRIMARY KEY,
    product_id       TEXT NOT NULL REFERENCES products(product_id),
    size             TEXT NOT NULL,
    color            TEXT NOT NULL,
    unit_price_egp   INTEGER NOT NULL CHECK (unit_price_egp > 0),
    price_updated_at TEXT NOT NULL,
    active           INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    UNIQUE (product_id, size, color)
);

CREATE TABLE inventory (
    sku        TEXT PRIMARY KEY REFERENCES variants(sku),
    available  INTEGER NOT NULL CHECK (available >= 0),
    updated_at TEXT NOT NULL
);

CREATE TABLE governorates (
    governorate TEXT PRIMARY KEY,          -- canonical key, e.g. 'cairo'
    name_ar     TEXT NOT NULL,
    name_en     TEXT NOT NULL
);

CREATE TABLE governorate_aliases (
    alias       TEXT PRIMARY KEY,          -- lower-cased spelling variant
    governorate TEXT NOT NULL REFERENCES governorates(governorate)
);

-- A governorate without a row here has NO trusted delivery fee (never guessed).
CREATE TABLE shipping_rates (
    governorate TEXT PRIMARY KEY REFERENCES governorates(governorate),
    fee_egp     INTEGER NOT NULL CHECK (fee_egp >= 0),
    updated_at  TEXT NOT NULL
);

CREATE TABLE discounts (
    code   TEXT PRIMARY KEY,
    kind   TEXT NOT NULL CHECK (kind IN ('PERCENT', 'FIXED')),
    value  INTEGER NOT NULL CHECK (value > 0),
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    CHECK (kind <> 'PERCENT' OR value <= 100)
);

-- ---------- Orders ----------

CREATE TABLE orders (
    order_id          TEXT PRIMARY KEY,
    channel           TEXT NOT NULL CHECK (channel IN ('instagram', 'whatsapp', 'facebook')),
    lifecycle_state   TEXT NOT NULL CHECK (lifecycle_state IN
                        ('PENDING', 'VERIFIED', 'READY_FOR_DISPATCH', 'SHIPPED', 'DELIVERED', 'CANCELLED')),
    version           INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    customer_name     TEXT,
    phone_raw         TEXT,
    address_raw       TEXT,
    governorate       TEXT,                -- canonical key once validated; free text never trusted
    city              TEXT,
    district          TEXT,
    street            TEXT,
    building          TEXT,
    floor             TEXT,
    apartment         TEXT,
    landmark          TEXT,
    discount_code     TEXT,
    -- Last quote shown to the customer, bound to the version it was computed for.
    quoted_version    INTEGER,
    quoted_subtotal_egp INTEGER,
    quoted_discount_egp INTEGER,
    quoted_shipping_egp INTEGER,
    quoted_total_egp  INTEGER,
    -- Agent outcome is separate from the authoritative lifecycle state.
    agent_outcome     TEXT CHECK (agent_outcome IN ('READY_FOR_DISPATCH', 'ON_HOLD', 'ESCALATE_TO_HUMAN')),
    outcome_reason    TEXT,
    clarification_attempts INTEGER NOT NULL DEFAULT 0 CHECK (clarification_attempts >= 0),
    synthetic         INTEGER NOT NULL DEFAULT 1 CHECK (synthetic = 1),
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE order_items (
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    line_no  INTEGER NOT NULL CHECK (line_no >= 1),
    sku      TEXT NOT NULL REFERENCES variants(sku),
    quantity INTEGER NOT NULL CHECK (quantity >= 1),
    PRIMARY KEY (order_id, line_no)
);

-- Defense in depth (BR-06): even a buggy tool cannot make these changes.
-- Agent-permitted lifecycle transitions only.
CREATE TRIGGER guard_lifecycle_transition
BEFORE UPDATE OF lifecycle_state ON orders
WHEN NEW.lifecycle_state <> OLD.lifecycle_state AND NOT (
       (OLD.lifecycle_state = 'PENDING'  AND NEW.lifecycle_state IN ('VERIFIED', 'READY_FOR_DISPATCH'))
    OR (OLD.lifecycle_state = 'VERIFIED' AND NEW.lifecycle_state IN ('PENDING', 'READY_FOR_DISPATCH')))
BEGIN
    SELECT RAISE(ABORT, 'lifecycle transition not permitted');
END;

-- Order content is frozen from READY_FOR_DISPATCH onwards.
CREATE TRIGGER guard_locked_order_content
BEFORE UPDATE OF version, customer_name, phone_raw, address_raw, governorate, city, district, street,
                 building, floor, apartment, landmark, discount_code ON orders
WHEN OLD.lifecycle_state NOT IN ('PENDING', 'VERIFIED')
BEGIN
    SELECT RAISE(ABORT, 'order content is locked in this lifecycle state');
END;

CREATE TRIGGER guard_locked_items_update
BEFORE UPDATE ON order_items
WHEN (SELECT lifecycle_state FROM orders WHERE order_id = OLD.order_id) NOT IN ('PENDING', 'VERIFIED')
BEGIN
    SELECT RAISE(ABORT, 'order items are locked in this lifecycle state');
END;

CREATE TRIGGER guard_locked_items_delete
BEFORE DELETE ON order_items
WHEN (SELECT lifecycle_state FROM orders WHERE order_id = OLD.order_id) NOT IN ('PENDING', 'VERIFIED')
BEGIN
    SELECT RAISE(ABORT, 'order items are locked in this lifecycle state');
END;

-- ---------- Confirmation binding ----------

CREATE TABLE confirmation_requests (
    confirmation_request_id TEXT PRIMARY KEY,
    order_id         TEXT NOT NULL REFERENCES orders(order_id),
    order_version    INTEGER NOT NULL CHECK (order_version >= 1),
    summary_hash     TEXT NOT NULL,
    total_egp        INTEGER NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('OPEN', 'ACCEPTED', 'SUPERSEDED', 'INVALIDATED')),
    accepted_event_id TEXT,
    created_at       TEXT NOT NULL,
    resolved_at      TEXT
);
-- At most one OPEN confirmation request per order.
CREATE UNIQUE INDEX one_open_confirmation_per_order
    ON confirmation_requests(order_id) WHERE status = 'OPEN';

-- ---------- Conversation (simulated channel) ----------
-- seq gives a total order, so "first inbound reply after the latest request" is decidable.

CREATE TABLE messages (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        TEXT NOT NULL REFERENCES orders(order_id),
    direction       TEXT NOT NULL CHECK (direction IN ('INBOUND', 'OUTBOUND')),
    kind            TEXT NOT NULL CHECK (kind IN
                      ('CUSTOMER', 'CLARIFICATION', 'CONFIRMATION_REQUEST', 'DUPLICATE_INTENT_REQUEST', 'INFO',
                       'ESCALATION_NOTICE')),
    body            TEXT NOT NULL,
    event_id        TEXT UNIQUE,           -- inbound idempotency key (same event delivered twice)
    idempotency_key TEXT UNIQUE,           -- outbound dedupe key
    confirmation_request_id TEXT REFERENCES confirmation_requests(confirmation_request_id),
    delivery        TEXT NOT NULL DEFAULT 'SIMULATED' CHECK (delivery = 'SIMULATED'),
    created_at      TEXT NOT NULL,
    CHECK ((direction = 'INBOUND') = (kind = 'CUSTOMER')),
    CHECK (direction = 'OUTBOUND' OR event_id IS NOT NULL),
    CHECK (kind <> 'CONFIRMATION_REQUEST' OR confirmation_request_id IS NOT NULL)
);

-- Saved result per processed inbound event; a redelivered event returns this, no new side effects.
CREATE TABLE event_results (
    event_id    TEXT PRIMARY KEY REFERENCES messages(event_id),
    result_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- ---------- Duplicates ----------

CREATE TABLE duplicate_flags (
    order_id_a  TEXT NOT NULL REFERENCES orders(order_id),
    order_id_b  TEXT NOT NULL REFERENCES orders(order_id),
    match_basis TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('OPEN', 'CLEARED_BOTH_INTENDED', 'ESCALATED')),
    -- Evidence binding: the deterministic question asked about THIS pair, on which order's conversation.
    intent_order_id    TEXT,
    intent_request_seq INTEGER,
    cleared_by_event_id TEXT,
    created_at  TEXT NOT NULL,
    resolved_at TEXT,
    PRIMARY KEY (order_id_a, order_id_b),
    CHECK (order_id_a < order_id_b)
);

-- ---------- Side-effect ledger (idempotency + timeout recovery) ----------

CREATE TABLE operations (
    op_id       TEXT PRIMARY KEY,          -- stable key, e.g. 'ready:ORD-1001:v3'
    order_id    TEXT NOT NULL REFERENCES orders(order_id),
    op_type     TEXT NOT NULL CHECK (op_type IN ('COMMIT_READY', 'APPLY_CHANGE')),
    status      TEXT NOT NULL CHECK (status IN ('SUCCEEDED', 'FAILED')),
    request_json TEXT NOT NULL,
    result_json TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE stock_reservations (
    op_id    TEXT NOT NULL REFERENCES operations(op_id),
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    sku      TEXT NOT NULL REFERENCES variants(sku),
    quantity INTEGER NOT NULL CHECK (quantity >= 1),
    PRIMARY KEY (op_id, sku)
);

CREATE TABLE escalations (
    escalation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id      TEXT NOT NULL REFERENCES orders(order_id),
    reason_code   TEXT NOT NULL,
    detail        TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'RESOLVED')),
    created_at    TEXT NOT NULL
);

-- ---------- Observability ----------

CREATE TABLE agent_runs (
    run_id        TEXT PRIMARY KEY,
    mode          TEXT NOT NULL CHECK (mode IN ('LIVE', 'REPLAY')),   -- never mixed in reports
    model         TEXT,
    order_id      TEXT REFERENCES orders(order_id),
    event_id      TEXT,
    status        TEXT NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'STOPPED', 'FAILED')),
    error_class   TEXT CHECK (error_class IN
                    ('LLM_ERROR', 'TOOL_ERROR', 'VALIDATION_ERROR', 'BUSINESS_RULE', 'BUDGET_EXCEEDED', 'TIMEOUT')),
    error_detail  TEXT,
    llm_calls     INTEGER NOT NULL DEFAULT 0,
    tool_calls    INTEGER NOT NULL DEFAULT 0,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0,
    -- REPLAY runs make no API calls: cost is not applicable, never reported as model cost.
    cost_basis    TEXT NOT NULL CHECK (cost_basis IN ('NOT_APPLICABLE_REPLAY', 'ESTIMATED_FROM_TOKEN_USAGE')),
    final_outcome TEXT,
    final_lifecycle TEXT,
    agent_summary TEXT,
    latency_ms    INTEGER,
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    CHECK ((mode = 'REPLAY') = (cost_basis = 'NOT_APPLICABLE_REPLAY'))
);

-- One row per LLM call / tool call / stop, in order (inputs and outputs PII-redacted).
CREATE TABLE agent_steps (
    run_id      TEXT NOT NULL REFERENCES agent_runs(run_id),
    step_no     INTEGER NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('LLM_CALL', 'TOOL_CALL', 'STOP')),
    name        TEXT,
    input_json  TEXT,
    output_json TEXT,
    latency_ms  INTEGER,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, step_no)
);

CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    run_id      TEXT,
    order_id    TEXT,
    actor       TEXT NOT NULL CHECK (actor IN ('AGENT', 'POLICY', 'TOOL', 'SYSTEM', 'HUMAN')),
    event_type  TEXT NOT NULL,
    detail_json TEXT NOT NULL              -- PII-redacted before write
);
