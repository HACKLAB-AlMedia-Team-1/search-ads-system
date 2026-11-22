-- RootSight database (DuckDB). Every table is created if missing.

CREATE TABLE IF NOT EXISTS fact_hourly (
    ts TIMESTAMP, market VARCHAR, platform VARCHAR, source VARCHAR,
    sessions DOUBLE, searches DOUBLE, zero_result_searches DOUBLE, results_total DOUBLE,
    searches_with_click DOUBLE, clicks_top3 DOUBLE,
    sum_relevance10 DOUBLE, sum_ndcg10 DOUBLE, sum_first_exact_pos DOUBLE,
    latency_ms_sum DOUBLE, latency_ms_p95 DOUBLE,
    carts DOUBLE, cart_unavailable_errors DOUBLE, price_mismatch_clicks DOUBLE,
    checkouts DOUBLE, orders DOUBLE, revenue_eur DOUBLE,
    sum_click_position DOUBLE, refinements DOUBLE, bounces DOUBLE
);

CREATE TABLE IF NOT EXISTS ads_hourly (
    ts TIMESTAMP, market VARCHAR, campaign_id VARCHAR,
    budget_daily_eur DOUBLE, planned_spend_eur DOUBLE, spend_eur DOUBLE, impressions DOUBLE,
    paid_clicks DOUBLE, cpc_eur DOUBLE, paid_sessions DOUBLE, paid_orders DOUBLE, paid_revenue_eur DOUBLE
);

CREATE TABLE IF NOT EXISTS component_hourly (
    ts TIMESTAMP, component VARCHAR, scope VARCHAR, metric VARCHAR, value DOUBLE
);

CREATE TABLE IF NOT EXISTS search_samples (
    ts TIMESTAMP, market VARCHAR, platform VARCHAR, source VARCHAR, query VARCHAR, filters_json VARCHAR,
    result_ids_json VARCHAR, zero_result BOOLEAN, latency_ms DOUBLE, clicked_pos INTEGER
);

CREATE SEQUENCE IF NOT EXISTS event_seq START 1;
CREATE TABLE IF NOT EXISTS events (
    event_id BIGINT DEFAULT nextval('event_seq'),
    ts TIMESTAMP, type VARCHAR, component VARCHAR, detail VARCHAR, scope_json VARCHAR
);

CREATE TABLE IF NOT EXISTS data_arrivals (
    ts TIMESTAMP, table_name VARCHAR, rows_expected DOUBLE, rows_received DOUBLE, arrived_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS calendar (
    start_ts TIMESTAMP, end_ts TIMESTAMP, name VARCHAR, kind VARCHAR, scope_json VARCHAR, expected_effect_json VARCHAR
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id VARCHAR, market VARCHAR, supplier VARCHAR, created_at TIMESTAMP, due_at TIMESTAMP,
    qty_needed BIGINT, qty_ordered BIGINT, qty_received BIGINT, received_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS catalogue_state (
    market VARCHAR, product_id VARCHAR, price_eur DOUBLE, stock BIGINT, delisted BOOLEAN
);

CREATE TABLE IF NOT EXISTS metric_registry (
    name VARCHAR, definition VARCHAR, sql VARCHAR, added_at TIMESTAMP, added_by VARCHAR
);

CREATE SEQUENCE IF NOT EXISTS incident_seq START 1;
CREATE TABLE IF NOT EXISTS incidents (
    incident_id BIGINT DEFAULT nextval('incident_seq'),
    fingerprint VARCHAR, status VARCHAR, first_seen TIMESTAMP, last_seen TIMESTAMP, resolved_at TIMESTAMP,
    root_metric VARCHAR, segment_json VARCHAR, cause_component VARCHAR, evidence_status VARCHAR,
    impact_orders DOUBLE, impact_revenue_eur DOUBLE, wasted_ad_spend_eur DOUBLE,
    report_md VARCHAR, report_json VARCHAR
);

CREATE TABLE IF NOT EXISTS investigations (
    case_id VARCHAR, step INTEGER, ts TIMESTAMP, tool VARCHAR, args_json VARCHAR, result_json VARCHAR, reasoning VARCHAR
);

CREATE TABLE IF NOT EXISTS llm_calls (
    ts TIMESTAMP, case_id VARCHAR, role VARCHAR, model VARCHAR, mode VARCHAR, input_tokens BIGINT, output_tokens BIGINT
);

CREATE TABLE IF NOT EXISTS anomalies (
    ts TIMESTAMP, metric VARCHAR, segment_json VARCHAR, actual DOUBLE, expected DOUBLE, z DOUBLE,
    attention DOUBLE, n_consecutive INTEGER, planned BOOLEAN, case_id VARCHAR
);

CREATE TABLE IF NOT EXISTS cases (
    case_id VARCHAR, ts TIMESTAMP, kind VARCHAR, status VARCHAR, headline VARCHAR, root_metric VARCHAR,
    segment_json VARCHAR, onset_ts TIMESTAMP, attention DOUBLE, detail_json VARCHAR
);

CREATE TABLE IF NOT EXISTS ux_events (
    ts TIMESTAMP, session_id VARCHAR, market VARCHAR, platform VARCHAR, event VARCHAR,
    query VARCHAR, position INTEGER, value DOUBLE
);

CREATE TABLE IF NOT EXISTS watches (
    watch_id VARCHAR, created TIMESTAMP, request VARCHAR, kind VARCHAR, metric VARCHAR, segment_json VARCHAR,
    every_hours INTEGER, reason VARCHAR, active BOOLEAN, last_check TIMESTAMP, last_verdict VARCHAR, last_note VARCHAR
);
