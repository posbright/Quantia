"""Kronos 生产等价的多锚点滚动验证。"""

from __future__ import annotations

import hashlib
import json
import math
import urllib.error
import urllib.request
from collections import defaultdict
from typing import Any, Callable, Iterable, Mapping, Sequence

import pandas as pd

DEFAULT_HORIZONS = (1, 3, 5, 10, 15, 30)
DEFAULT_INFERENCE_PARAMETERS: dict[str, Any] = {
    "sample_count": 1,
    "temperature": 1.0,
    "top_k": 1,
    "top_p": 1.0,
    "clip": 5.0,
}


class ProviderCallError(RuntimeError):
    def __init__(self, message: str, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def normalize_inference_parameters(
    parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = {**DEFAULT_INFERENCE_PARAMETERS, **(parameters or {})}
    unknown = sorted(set(normalized) - set(DEFAULT_INFERENCE_PARAMETERS))
    if unknown:
        raise ValueError(f"unsupported inference parameters: {unknown}")
    normalized["sample_count"] = int(normalized["sample_count"])
    normalized["temperature"] = float(normalized["temperature"])
    normalized["top_k"] = int(normalized["top_k"])
    normalized["top_p"] = float(normalized["top_p"])
    normalized["clip"] = float(normalized["clip"])
    if normalized["sample_count"] < 1 or normalized["sample_count"] > 64:
        raise ValueError("sample_count must be within 1..64")
    if normalized["temperature"] <= 0:
        raise ValueError("temperature must be positive")
    if normalized["top_k"] < 0 or normalized["top_k"] > 1024:
        raise ValueError("top_k must be within 0..1024")
    if not 0 < normalized["top_p"] <= 1:
        raise ValueError("top_p must be within (0, 1]")
    if normalized["clip"] <= 0:
        raise ValueError("clip must be positive")
    return normalized


def _smape(predicted: float, actual: float) -> float:
    denominator = abs(predicted) + abs(actual)
    return 0.0 if denominator == 0 else 2.0 * abs(predicted - actual) / denominator


def _post_json(url: str, payload: Mapping[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            error = json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            error = {}
        raise ProviderCallError(
            str(error.get("msg") or exc.reason),
            str(error.get("error_code") or f"HTTP_{exc.code}"),
        ) from exc
    except TimeoutError as exc:
        raise ProviderCallError(str(exc), "PROVIDER_TIMEOUT") from exc
    except urllib.error.URLError as exc:
        raise ProviderCallError(str(exc.reason), "PROVIDER_UNAVAILABLE") from exc
    if not isinstance(result, dict):
        raise ProviderCallError("Kronos response must be a JSON object", "INVALID_RESPONSE")
    if result.get("error_code") or result.get("code") not in (None, 0, "0"):
        raise ProviderCallError(
            str(result.get("msg") or "Kronos provider rejected request"),
            str(result.get("error_code") or "PROVIDER_REJECTED"),
        )
    return result


def _history_rows(frame: pd.DataFrame, lookback: int) -> list[dict[str, Any]]:
    history = frame.tail(lookback).copy()
    if len(history) < lookback:
        raise ValueError(f"history requires {lookback} rows, got {len(history)}")
    required = ("date", "open", "high", "low", "close", "volume")
    missing = [column for column in required if column not in history.columns]
    if missing:
        raise ValueError(f"history missing columns: {missing}")
    if "amount" not in history.columns:
        history["amount"] = history["volume"] * history[
            ["open", "high", "low", "close"]
        ].mean(axis=1)
    else:
        missing_amount = pd.to_numeric(history["amount"], errors="coerce").isna()
        fallback = history["volume"] * history[["open", "high", "low", "close"]].mean(axis=1)
        history.loc[missing_amount, "amount"] = fallback[missing_amount]

    rows = []
    for _, row in history.iterrows():
        values = {column: float(row[column]) for column in (*required[1:], "amount")}
        if not all(math.isfinite(value) for value in values.values()):
            raise ValueError("history contains non-finite values")
        rows.append({
            "date": pd.Timestamp(row["date"]).date().isoformat(),
            **values,
        })
    return rows


def _validate_terminal_prediction(response: Mapping[str, Any], horizon: int,
                                  target_date: str) -> Mapping[str, Any]:
    predictions = response.get("predictions")
    if not isinstance(predictions, list) or len(predictions) != horizon:
        raise ValueError(f"expected {horizon} predictions")
    terminal = predictions[-1]
    if str(terminal.get("date"))[:10] != target_date:
        raise ValueError("terminal prediction date does not match target trade date")
    for column in ("open", "high", "low", "close"):
        value = float(terminal[column])
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"prediction.{column} must be finite and positive")
    return terminal


def _evaluate(predicted_close: float, actual_close: float,
              last_actual_close: float) -> dict[str, Any]:
    predicted_return = predicted_close / last_actual_close - 1.0
    actual_return = actual_close / last_actual_close - 1.0
    return {
        "actual_close": actual_close,
        "predicted_return": predicted_return,
        "actual_return": actual_return,
        "close_abs_error": abs(predicted_close - actual_close),
        "close_smape": _smape(predicted_close, actual_close),
        "return_abs_error": abs(predicted_return - actual_return),
        "direction_correct": int(
            (predicted_return > 0) == (actual_return > 0)
            if predicted_return != 0 and actual_return != 0
            else predicted_return == actual_return
        ),
        "baseline_close_abs_error": abs(last_actual_close - actual_close),
        "baseline_close_smape": _smape(last_actual_close, actual_close),
        "baseline_return_abs_error": abs(actual_return),
    }


def aggregate_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[int, int], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(int(record["lookback"]), int(record["horizon"]))].append(record)

    result: dict[str, Any] = {}
    for (lookback, horizon), rows in sorted(grouped.items()):
        observed = [row for row in rows if row.get("status") == "observed"]
        key = f"lookback={lookback},horizon={horizon}"
        metrics: dict[str, Any] = {
            "lookback": lookback,
            "horizon": horizon,
            "n_expected": len(rows),
            "n_observed": len(observed),
            "n_not_traded": sum(row.get("status") == "not_traded" for row in rows),
            "n_actual_missing": sum(row.get("status") == "actual_missing" for row in rows),
            "n_provider_error": sum(row.get("status") == "provider_error" for row in rows),
            "coverage": len(observed) / len(rows) if rows else 0.0,
        }
        if observed:
            count = len(observed)
            for source, target in (
                ("close_abs_error", "close_mae"),
                ("close_smape", "close_smape"),
                ("return_abs_error", "return_mae"),
                ("baseline_close_abs_error", "baseline_close_mae"),
                ("baseline_close_smape", "baseline_close_smape"),
                ("baseline_return_abs_error", "baseline_return_mae"),
            ):
                metrics[target] = sum(float(row[source]) for row in observed) / count
            metrics["directional_accuracy"] = (
                sum(int(row["direction_correct"]) for row in observed) / count
            )
            metrics["close_mae_vs_baseline"] = (
                metrics["close_mae"] - metrics["baseline_close_mae"]
            )
        result[key] = metrics
    return result


def _config_hash(settings: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(settings, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def _artifact(
    settings: Mapping[str, Any],
    anchor_audit: Mapping[str, int],
    records: list[dict[str, Any]],
    *,
    complete: bool,
) -> dict[str, Any]:
    artifact_versions = sorted({
        str(record["model_version"])
        for record in records if record.get("model_version")
    })
    return {
        "schema_version": 2,
        "mode": "production_equivalent_independent_horizons",
        "complete": complete,
        "config_hash": _config_hash(settings),
        "settings": dict(settings),
        "anchor_audit": dict(anchor_audit),
        "artifact_versions": artifact_versions,
        "mixed_model_versions": len(artifact_versions) > 1,
        "records": records,
        "summary": aggregate_records(records) if complete else {},
    }


def run_rolling_validation(
    codes: Sequence[str],
    trade_dates: Iterable[Any],
    data_loader: Callable[..., pd.DataFrame | None],
    provider: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    *,
    anchor_start: Any,
    anchor_end: Any,
    lookbacks: Sequence[int],
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    anchor_step: int = 5,
    max_anchors: int = 0,
    inference_parameters: Mapping[str, Any] | None = None,
    resume_artifact: Mapping[str, Any] | None = None,
    resume_retry_statuses: Iterable[str] = (),
    checkpoint_callback: Callable[[Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """运行滚动验证；每个 horizon 独立请求，匹配 Quantia 线上语义。"""
    normalized_dates = sorted({pd.Timestamp(value).normalize() for value in trade_dates})
    start = pd.Timestamp(anchor_start).normalize()
    end = pd.Timestamp(anchor_end).normalize()
    horizons = tuple(sorted({int(value) for value in horizons}))
    lookbacks = tuple(sorted({int(value) for value in lookbacks}))
    if not normalized_dates or not horizons or horizons[0] < 1:
        raise ValueError("trade_dates and positive horizons are required")
    if not lookbacks or lookbacks[0] < 32 or lookbacks[-1] > 512:
        raise ValueError("lookbacks must be within 32..512")
    if anchor_step < 1:
        raise ValueError("anchor_step must be positive")
    inference_parameters = normalize_inference_parameters(inference_parameters)

    date_position = {date: index for index, date in enumerate(normalized_dates)}
    max_horizon = max(horizons)
    candidates = [date for date in normalized_dates if start <= date <= end]
    anchors = candidates[::anchor_step]
    if max_anchors > 0:
        anchors = anchors[:max_anchors]
    mature_anchors = [
        anchor for anchor in anchors
        if date_position[anchor] + max_horizon < len(normalized_dates)
    ]

    settings = {
        "codes": sorted(set(codes)),
        "anchor_start": start.date().isoformat(),
        "anchor_end": end.date().isoformat(),
        "actual_data_end": normalized_dates[-1].date().isoformat(),
        "anchor_step": anchor_step,
        "max_anchors": max_anchors,
        "lookbacks": list(lookbacks),
        "horizons": list(horizons),
        "inference_parameters": inference_parameters,
    }
    anchor_audit = {
        "selected": len(anchors),
        "mature": len(mature_anchors),
        "skipped_insufficient_future": len(anchors) - len(mature_anchors),
    }
    if resume_artifact and resume_artifact.get("settings") != settings:
        raise ValueError("resume artifact configuration mismatch")
    resumed_records = resume_artifact.get("records", []) if resume_artifact else []
    if not isinstance(resumed_records, list):
        raise ValueError("resume artifact records must be a list")
    retry_statuses = set(resume_retry_statuses)
    records: list[dict[str, Any]] = [
        dict(record) for record in resumed_records
        if record.get("status") not in retry_statuses
    ]
    completed_tasks = {
        (
            str(record.get("code")),
            str(record.get("anchor_date")),
            int(record.get("lookback", 0)),
            int(record.get("horizon", 0)),
        )
        for record in records
    }

    def append_record(record: dict[str, Any]) -> None:
        records.append(record)
        if checkpoint_callback:
            checkpoint_callback(_artifact(
                settings, anchor_audit, records, complete=False,
            ))

    for code in dict.fromkeys(codes):
        frame = data_loader(code, end_date=normalized_dates[-1], cache_only=True)
        if frame is None or len(frame) == 0:
            continue
        frame = frame.copy()
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
        frame = frame.sort_values("date").drop_duplicates("date", keep="last")
        actual_by_date = frame.set_index("date")

        for anchor in mature_anchors:
            position = date_position[anchor]
            future_dates = normalized_dates[position + 1:position + 1 + max_horizon]
            history = frame[frame["date"] <= anchor]
            if anchor not in actual_by_date.index:
                continue
            last_actual_close = float(actual_by_date.loc[anchor]["close"])

            for lookback in lookbacks:
                if len(history) < lookback:
                    continue
                serialized_history = _history_rows(history, lookback)
                for horizon in horizons:
                    task_key = (
                        code, anchor.date().isoformat(), lookback, horizon,
                    )
                    if task_key in completed_tasks:
                        continue
                    target = future_dates[horizon - 1]
                    target_text = target.date().isoformat()
                    base = {
                        "code": code,
                        "anchor_date": anchor.date().isoformat(),
                        "target_date": target_text,
                        "lookback": lookback,
                        "horizon": horizon,
                        "last_actual_close": last_actual_close,
                        "inference_parameters": inference_parameters,
                    }
                    payload = {
                        "code": code,
                        "days": horizon,
                        "lookback": lookback,
                        "history": serialized_history,
                        "future_timestamps": [
                            date.date().isoformat() for date in future_dates[:horizon]
                        ],
                        "history_stale": False,
                        **inference_parameters,
                    }
                    try:
                        response = provider(payload)
                        terminal = _validate_terminal_prediction(response, horizon, target_text)
                    except Exception as exc:  # noqa: BLE001
                        append_record({
                            **base, "status": "provider_error",
                            "error_code": getattr(exc, "error_code", type(exc).__name__),
                            "error": f"{type(exc).__name__}: {exc}",
                        })
                        continue
                    predicted_close = float(terminal["close"])
                    metadata = {
                        "predicted_close": predicted_close,
                        "model_version": response.get("model_version"),
                        "predictor_version": response.get("predictor_version"),
                        "tokenizer_version": response.get("tokenizer_version"),
                        "latency_ms": response.get("latencyMs"),
                    }
                    if target not in actual_by_date.index:
                        # 仅当后续又恢复交易时，才能确认目标日是未交易；数据尾端缺失
                        # 也可能是缓存过期/价格基准断裂，必须保守标记 actual_missing。
                        has_later_bar = bool((frame["date"] > target).any())
                        status = "not_traded" if has_later_bar else "actual_missing"
                        append_record({**base, **metadata, "status": status})
                        continue
                    actual_close = float(actual_by_date.loc[target]["close"])
                    append_record({
                        **base, **metadata, "status": "observed",
                        **_evaluate(predicted_close, actual_close, last_actual_close),
                    })

    return _artifact(settings, anchor_audit, records, complete=True)


def http_provider(url: str, timeout: float = 60.0) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    return lambda payload: _post_json(url, payload, timeout)