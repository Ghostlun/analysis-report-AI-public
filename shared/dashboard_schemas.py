"""Explicit JSON schemas, strict validator and public-safety scan for the dashboard JSON files.

Every object schema built with ``obj()`` lists all permitted keys, requires all of them, and forbids extra keys, so the
schemas double as the field allowlist. Unknown keys therefore fail validation.

Only the JSON-Schema subset used here is implemented (type, properties, required, additionalProperties, items, enum,
const, pattern, minimum, maximum). Schemas are plain dicts and are also valid for the ``jsonschema`` package.
"""
from __future__ import annotations

import json
import math
import re

SCHEMA_VERSION = "1.0.0"
TS_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
SHA_PATTERN = r"^[0-9a-f]{64}$"
PUBLICATION_STATUS = "public_portfolio_aggregate"
DASHBOARDS = ("market_overview", "technical_indicators", "prediction_analysis", "strategy_research")


# ----------------------------------------------------------------------------- schema builders
def obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def arr(items: dict) -> dict:
    return {"type": "array", "items": items}


STR = {"type": "string"}
BOOL = {"type": "boolean"}
INT = {"type": "integer"}
NUM = {"type": "number"}
INT_N = {"type": ["integer", "null"]}
NUM_N = {"type": ["number", "null"]}
STR_N = {"type": ["string", "null"]}
TS = {"type": "string", "pattern": TS_PATTERN}
TS_N = {"type": ["string", "null"], "pattern": TS_PATTERN}
DATE = {"type": "string", "pattern": DATE_PATTERN}


def enum(*values) -> dict:
    return {"type": "string", "enum": list(values)}


def const(value) -> dict:
    return {"const": value}


AVAILABILITY = enum("available", "unavailable")
UNAVAILABLE_STATE = obj({"status": const("unavailable"), "reason": STR})
STAT3 = obj({"n_valid": INT, "min": NUM_N, "median": NUM_N, "max": NUM_N})

SOURCE_FILE = obj({"name": STR, "role": STR, "sha256": {"type": "string", "pattern": SHA_PATTERN}})


def meta_schema(dashboard: str, sample_counts: dict) -> dict:
    return obj({
        "schema_version": const(SCHEMA_VERSION),
        "dashboard": const(dashboard),
        "generated_at": TS,
        "data_status": obj({
            "kind": const("historical_research_snapshot"),
            "is_live": const(False),
            "as_of": TS_N,
            "description": STR,
        }),
        "publication_status": obj({
            "status": const(PUBLICATION_STATUS),
            "approved_for_public_release": const(True),
            "notes": STR,
        }),
        "source_window": obj({"start": TS_N, "end": TS_N}),
        "sample_counts": obj(sample_counts),
        "source_files": arr(SOURCE_FILE),
        "disclaimers": arr(STR),
    })


def columnar(columns: dict) -> dict:
    return obj({k: arr(v) for k, v in columns.items()})


# ----------------------------------------------------------------------------- dashboard schemas
_BAR_SERIES = columnar({"time": TS, "close": NUM_N, "n_obs": INT, "partial": BOOL, "gap_affected": BOOL})

MARKET_OVERVIEW = obj({
    "meta": meta_schema("market_overview", {
        "snapshot_rows": INT, "markets": INT, "reference_observations": INT, "settled_markets": INT}),
    "definitions": obj({
        "btc_reference_price": STR, "contract_price": STR, "contract_volume": STR, "implied_probability": STR,
        "time_to_close": STR}),
    "snapshot_counts": obj({
        "snapshot_rows": INT, "markets": INT, "rows_with_btc_reference": INT,
        "rows_with_two_sided_yes_quote": INT_N, "median_snapshot_interval_seconds": NUM_N,
        "collected_start": TS_N, "collected_end": TS_N}),
    "reference_price_summary": obj({
        "status": AVAILABILITY, "index": STR, "unit": STR, "n_observations": INT,
        "first_time": TS_N, "last_time": TS_N, "first_value": NUM_N, "last_value": NUM_N,
        "min": NUM_N, "max": NUM_N, "mean": NUM_N, "median": NUM_N, "change_pct_first_to_last": NUM_N}),
    "reference_coverage": obj({
        "rows_with_reference": INT, "rows_without_reference": INT, "share_rows_without_reference": NUM_N,
        "duplicate_reference_rows_removed": INT, "conflicting_reference_timestamps": INT,
        "collection_gap_min_seconds": NUM, "collection_gap_count": INT,
        "longest_collection_gap_seconds": NUM_N, "total_gap_seconds": NUM_N}),
    "reference_price_series": obj({
        "status": AVAILABILITY, "unit": STR, "note": STR,
        "15m": _BAR_SERIES, "1h": _BAR_SERIES}),
    "daily_reference_summary": arr(obj({
        "date": DATE, "n_observations": INT, "first": NUM, "last": NUM, "min": NUM, "max": NUM, "mean": NUM})),
    "settlement_outcomes": obj({
        "status": AVAILABILITY, "markets": INT, "settled_yes": INT, "settled_no": INT, "unsettled_or_unknown": INT,
        "markets_with_conflicting_outcome": INT, "yes_share_of_settled": NUM_N,
        "yes_share_ci95_lo": NUM_N, "yes_share_ci95_hi": NUM_N,
        "by_close_date": arr(obj({"date": DATE, "settled_markets": INT, "yes": INT, "no": INT}))}),
    "implied_probability": obj({
        "status": AVAILABILITY, "reason": STR_N, "unit": STR, "note": STR,
        "rows_used": INT, "rows_excluded_outside_time_range": INT,
        "by_time_to_close": arr(obj({
            "bin": STR, "seconds_lo": INT, "seconds_hi": INT, "n_snapshots": INT, "n_markets": INT,
            "mean_implied_prob_yes": NUM_N, "observed_yes_rate_snapshot_weighted": NUM_N})),
        "distribution": arr(obj({"p_lo": NUM, "p_hi": NUM, "n_snapshots": INT}))}),
    "contract_volume": UNAVAILABLE_STATE,
    "btc_spot_volume": UNAVAILABLE_STATE,
})

_IND_COLUMNS = {
    "time": TS, "close": NUM_N, "sma_20": NUM_N, "ema_20": NUM_N, "rsi_14": NUM_N, "roc_12_pct": NUM_N,
    "realized_vol_24_bar_pct": NUM_N, "realized_vol_24_ann_pct": NUM_N, "partial": BOOL, "gap_affected": BOOL,
}
_INTERVAL = obj({
    "status": AVAILABILITY, "bar_minutes": INT, "bars_per_year": NUM,
    "coverage": obj({
        "bars_total": INT, "bars_with_data": INT, "bars_missing": INT, "partial_bars": INT, "gap_affected_bars": INT,
        "bars_excluded_from_indicators": INT, "segments": INT, "first_bar_end": TS_N, "last_bar_end": TS_N,
        "missing_bar_share": NUM_N}),
    "valid_indicator_values": obj({k: INT for k in list(_IND_COLUMNS)[2:8]}),
    "series": columnar(_IND_COLUMNS),
})
_IND_STATUS = obj({"status": AVAILABILITY, "reason": STR_N})

TECHNICAL_INDICATORS = obj({
    "meta": meta_schema("technical_indicators", {"reference_observations": INT, "bars_1m": INT, "bars_5m": INT,
                                                 "bars_15m": INT, "bars_1h": INT}),
    "input_series": obj({
        "name": STR, "unit": STR, "type": STR, "note": STR}),
    "indicator_status": obj({
        "sma": _IND_STATUS, "ema": _IND_STATUS, "rsi": _IND_STATUS, "momentum_roc": _IND_STATUS,
        "realized_volatility": _IND_STATUS, "atr": _IND_STATUS, "vwap": _IND_STATUS, "volume_indicators": _IND_STATUS}),
    "parameters": obj({
        "sma_window_bars": INT, "ema_window_bars": INT, "rsi_window_bars": INT, "roc_window_bars": INT,
        "realized_vol_window_bars": INT, "rsi_smoothing": STR, "rsi_flat_price_value": NUM,
        "ema_seed": STR, "collection_gap_min_seconds": NUM, "bar_convention": STR,
        "volatility": obj({"estimator": STR, "formula": STR, "unit_bar": STR, "unit_annualized": STR,
                           "annualization": STR, "mean_assumption": STR}),
        "masking_rules": arr(STR)}),
    "intervals": obj({"1m": _INTERVAL, "5m": _INTERVAL, "15m": _INTERVAL, "1h": _INTERVAL}),
})

_MODEL_RESULT = obj({"brier": NUM_N, "accuracy": NUM_N})
_MODEL_RESULT_VS = obj({"brier": NUM_N, "accuracy": NUM_N, "brier_skill_vs_market": NUM_N,
                        "brier_difference_vs_market": NUM_N})
_WEIGHTED_VS = obj({"brier": NUM_N, "accuracy": NUM_N, "brier_skill_vs_market": NUM_N})

PREDICTION_ANALYSIS = obj({
    "meta": meta_schema("prediction_analysis", {"test_snapshots": INT, "time_bins": INT, "test_markets": INT_N}),
    "evaluation": obj({
        "unit_of_analysis": STR, "evaluation_set": STR, "split_rule": STR, "test_period_start": TS,
        "test_period_end": TS_N, "models_fit_on": STR, "horizon_seconds_lo": INT, "horizon_seconds_hi": INT,
        "all_market_exported_models_used": const(False), "n_test_snapshots": INT,
        "n_test_markets": obj({"status": const("unavailable"), "reason": STR})}),
    "models": arr(obj({"id": enum("market_baseline", "logistic", "gradient_boosting", "knn_analog"),
                       "label": STR, "description": STR})),
    "by_time_bin": arr(obj({
        "time_bin": STR, "seconds_lo": INT, "seconds_hi": INT, "n_snapshots": INT,
        "n_markets": obj({"status": const("unavailable"), "value": const(None)}),
        "results": obj({"market_baseline": _MODEL_RESULT, "logistic": _MODEL_RESULT_VS,
                        "gradient_boosting": _MODEL_RESULT_VS, "knn_analog": _MODEL_RESULT_VS})})),
    "snapshot_weighted_overall": obj({"n_snapshots": INT, "market_baseline": _MODEL_RESULT, "logistic": _WEIGHTED_VS,
                                      "gradient_boosting": _WEIGHTED_VS, "knn_analog": _WEIGHTED_VS}),
    "comparison": obj({
        "time_bins_total": INT,
        "time_bins_model_brier_below_market": obj({"logistic": INT, "gradient_boosting": INT, "knn_analog": INT}),
        "max_abs_brier_difference_vs_market": NUM_N,
        "superiority_claim": const("none"), "statement": STR}),
    "calibration": obj({"status": const("unavailable"), "reason": STR, "bins": arr(NUM)}),
    "limitations": arr(STR),
})

_FAMILY = obj({
    "family_id": enum("pattern_model_entry_policy", "pattern_model_four_minute_gate", "gap_rule", "momentum_filter"),
    "label": STR,
    "model": {"type": ["string", "null"], "enum": ["logistic", "gradient_boosting", "knn_analog", None]},
    "scenario": enum("slip_0.01", "delay_15s"),
    "period": enum("dev", "test"),
    "n_configurations": INT,
    "simulated_trades_per_configuration": STAT3,
    "win_rate": STAT3,
    "ev_per_contract_usd": STAT3,
    "share_of_configurations_with_positive_ev": NUM_N,
    "median_ev_standard_error_usd": NUM_N,
    "net_pnl_usd_simulated": STAT3,
    "max_drawdown_usd_simulated": STAT3,
})

STRATEGY_RESEARCH = obj({
    "meta": meta_schema("strategy_research", {"family_rows": INT, "configurations_summarised": INT}),
    "results_type": obj({"kind": const("simulated"), "live_trading_data_included": const(False), "description": STR}),
    "assumptions": obj({
        "fee_formula": STR, "fee_rate": NUM, "fee_rounding": STR, "slippage_usd": NUM,
        "delayed_fill_scenario": STR, "contracts_per_trade_momentum_filter": INT, "dev_test_split": STR,
        "fill_model": STR}),
    "families": arr(_FAMILY),
    "equity_curve": UNAVAILABLE_STATE,
    "selection_note": STR,
    "limitations": arr(STR),
})

SCHEMAS = {
    "market_overview": MARKET_OVERVIEW,
    "technical_indicators": TECHNICAL_INDICATORS,
    "prediction_analysis": PREDICTION_ANALYSIS,
    "strategy_research": STRATEGY_RESEARCH,
}


# ----------------------------------------------------------------------------- validator
def _type_ok(value, t: str) -> bool:
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "null":
        return value is None
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    return False


def validate(instance, schema: dict, path: str = "$") -> list[str]:
    """Return a list of error strings (empty = valid). Unknown keys, non-finite numbers and wrong types are errors."""
    errors: list[str] = []
    if "const" in schema and (instance != schema["const"] or type(instance) is not type(schema["const"])):
        return [f"{path}: expected constant {schema['const']!r}"]
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_type_ok(instance, x) for x in types):
            return [f"{path}: expected {types}, got {type(instance).__name__}"]
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: value not in allowed enum")
    if isinstance(instance, str) and "pattern" in schema and not re.search(schema["pattern"], instance):
        errors.append(f"{path}: string does not match pattern")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: below minimum")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: above maximum")
    if isinstance(instance, dict) and "properties" in schema:
        props = schema["properties"]
        for k in instance:
            if k not in props:
                errors.append(f"{path}: unexpected key {k!r}")
        for k in schema.get("required", []):
            if k not in instance:
                errors.append(f"{path}: missing key {k!r}")
        for k, sub in props.items():
            if k in instance:
                errors.extend(validate(instance[k], sub, f"{path}.{k}"))
    if isinstance(instance, list) and "items" in schema:
        for i, item in enumerate(instance):
            errors.extend(validate(item, schema["items"], f"{path}[{i}]"))
            if len(errors) > 50:
                errors.append(f"{path}: too many errors, stopping")
                break
    return errors


# ----------------------------------------------------------------------------- public-safety scan
FORBIDDEN_KEY_RE = re.compile(
    r"ticker|(^|_)orders?(_|$)|balance|account|api_?key|token|secret|password|coef|intercept|margin|zmin|persist|maxp|"
    r"threshold|credential", re.I)
FORBIDDEN_VALUE_RE = re.compile(
    r"KXBTC15M-\d|live_orders|outputs[/\\]actual|localhost|/api/|bearer|exchange_order|client_order|"
    r"[A-Za-z]:\\|/Users/|/home/", re.I)
ALLOWED_SOURCE_FILES = (
    "KXBTC15M_all.csv", "pattern_model_by_time.csv", "pattern_model_policy_grid.csv", "pattern_model_4min_gate.csv",
    "gap_rule_results.csv", "momentum_v2_dev_grid.csv",
)


def safety_scan(node, path: str = "$") -> list[str]:
    """Flag forbidden key names / string values anywhere in the document (defence in depth on top of the schema)."""
    problems: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if FORBIDDEN_KEY_RE.search(str(k)):
                problems.append(f"{path}: forbidden key name {k!r}")
            problems.extend(safety_scan(v, f"{path}.{k}"))
    elif isinstance(node, list):
        if len(node) <= 2000:  # long numeric/time columns are covered by the schema pattern
            for i, v in enumerate(node):
                problems.extend(safety_scan(v, f"{path}[{i}]"))
    elif isinstance(node, str):
        if FORBIDDEN_VALUE_RE.search(node):
            problems.append(f"{path}: forbidden string content")
    return problems


def validate_dashboard(name: str, doc: dict) -> None:
    """Raise ``ValueError`` unless ``doc`` passes the schema, the safety scan and the source-file allowlist."""
    if name not in SCHEMAS:
        raise ValueError(f"unknown dashboard {name!r}")
    errors = validate(doc, SCHEMAS[name])
    errors += safety_scan(doc)
    for sf in doc.get("meta", {}).get("source_files", []) if isinstance(doc, dict) else []:
        if sf.get("name") not in ALLOWED_SOURCE_FILES:
            errors.append(f"source file not on allowlist: {sf.get('name')!r}")
    if not errors:
        try:
            json.dumps(doc, allow_nan=False)
        except ValueError as exc:
            errors.append(f"non-finite number: {exc}")
    if errors:
        raise ValueError(f"{name} failed validation: " + "; ".join(errors[:10]))
