import pandas as pd
import pytest
from pathlib import Path
from unittest import mock

from quantia.job import kronos_rolling_validation_job as job
from quantia.kronos.rolling_validation import (
    _evaluate,
    normalize_inference_parameters,
    run_rolling_validation,
)


def _frame():
    dates = pd.bdate_range("2026-01-01", periods=70)
    return pd.DataFrame({
        "date": dates,
        "open": range(100, 170),
        "high": range(102, 172),
        "low": range(99, 169),
        "close": range(101, 171),
        "volume": 1000,
    })


def _inference_echo(payload):
    return {
        field: payload[field]
        for field in ("sample_count", "temperature", "top_k", "top_p", "clip")
    }


def test_available_trade_dates_is_capped_by_actual_end():
    expected = pd.DataFrame({"trade_date": pd.to_datetime(["2026-07-01", "2026-07-02"])})
    with mock.patch.object(job.pd, "read_sql", return_value=expected) as read_sql, \
            mock.patch.object(job.mdb, "engine", return_value=object()):
        dates = job._available_trade_dates("2026-06-30", pd.Timestamp("2026-07-02").date())

    sql = read_sql.call_args.args[0]
    assert "trade_date <= %s" in sql
    assert read_sql.call_args.kwargs["params"] == (
        "2026-06-30", pd.Timestamp("2026-07-02").date(),
    )
    assert len(dates) == 2


def test_atomic_write_json_retries_transient_windows_file_lock(tmp_path):
    output = tmp_path / "artifact.json"
    original_replace = Path.replace
    attempts = 0

    def flaky_replace(path, target):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("transient file lock")
        return original_replace(path, target)

    with mock.patch.object(Path, "replace", flaky_replace), \
            mock.patch.object(job.time, "sleep") as sleep:
        job._atomic_write_json(output, {"complete": False})

    assert attempts == 3
    assert sleep.call_count == 2
    assert output.read_text(encoding="utf-8").startswith("{")


def test_rolling_validation_calls_each_horizon_independently_and_scores_baseline():
    frame = _frame()
    calls = []

    def provider(payload):
        calls.append(payload)
        return {
            **_inference_echo(payload),
            "model_version": "bundle-1",
            "predictor_version": "predictor-1",
            "tokenizer_version": "tokenizer-1",
            "lookback": payload["lookback"],
            "latencyMs": 5,
            "predictions": [
                {
                    "date": date,
                    "open": 150.0,
                    "high": 152.0,
                    "low": 149.0,
                    "close": 151.0 + index,
                }
                for index, date in enumerate(payload["future_timestamps"])
            ],
        }

    result = run_rolling_validation(
        ["300308"], frame["date"], lambda *args, **kwargs: frame,
        provider, anchor_start=frame.iloc[40]["date"], anchor_end=frame.iloc[40]["date"],
        lookbacks=[32], horizons=[1, 3, 5], anchor_step=1,
    )

    assert [call["days"] for call in calls] == [1, 3, 5]
    assert all(call["lookback"] == 32 for call in calls)
    assert len(result["records"]) == 3
    assert all(record["status"] == "observed" for record in result["records"])
    summary = result["summary"]["lookback=32,horizon=1"]
    assert summary["n_observed"] == 1
    assert "close_mae_vs_baseline" in summary
    assert "return_mae_vs_baseline" in summary


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0.0, -1.0])
def test_evaluate_rejects_invalid_prices(value):
    with pytest.raises(ValueError, match="must be finite and positive"):
        _evaluate(100.0, value, 99.0)


def test_rolling_validation_tracks_inference_parameters():
    frame = _frame()
    anchor = frame.iloc[40]["date"]
    calls = []

    def provider(payload):
        calls.append(payload)
        return {**_inference_echo(payload), "predictions": [{
            "date": payload["future_timestamps"][0],
            "open": 150.0, "high": 152.0, "low": 149.0, "close": 151.0,
        }]}

    result = run_rolling_validation(
        ["300308"], frame["date"], lambda *args, **kwargs: frame,
        provider, anchor_start=anchor, anchor_end=anchor,
        lookbacks=[32], horizons=[1], anchor_step=1,
        inference_parameters={
            "sample_count": 5,
            "temperature": 0.7,
            "top_k": 0,
            "top_p": 0.85,
            "clip": 5.0,
        },
    )

    assert calls[0]["sample_count"] == 5
    assert calls[0]["temperature"] == 0.7
    assert calls[0]["top_p"] == 0.85
    assert result["settings"]["inference_parameters"]["sample_count"] == 5
    assert result["records"][0]["inference_parameters"]["top_p"] == 0.85
    assert result["records"][0]["applied_inference_parameters"]["top_p"] == 0.85
    assert result["records"][0]["status"] == "observed"


@pytest.mark.parametrize("response_parameters", [
    {},
    {
        "sample_count": 5, "temperature": 0.7, "top_k": 0,
        "top_p": 0.95, "clip": 5.0,
    },
])
def test_rolling_validation_rejects_missing_or_mismatched_provider_parameters(
    response_parameters,
):
    frame = _frame()
    anchor = frame.iloc[40]["date"]

    def provider(payload):
        return {**response_parameters, "predictions": [{
            "date": payload["future_timestamps"][0],
            "open": 150.0, "high": 152.0, "low": 149.0, "close": 151.0,
        }]}

    result = run_rolling_validation(
        ["300308"], frame["date"], lambda *args, **kwargs: frame,
        provider, anchor_start=anchor, anchor_end=anchor,
        lookbacks=[32], horizons=[1], anchor_step=1,
        inference_parameters={
            "sample_count": 5, "temperature": 0.7, "top_k": 0,
            "top_p": 0.85, "clip": 5.0,
        },
    )

    assert result["records"][0]["status"] == "provider_error"
    assert result["records"][0]["error_code"] == "ValueError"


def test_inference_parameters_reject_fractional_integer_fields():
    with pytest.raises(ValueError, match="must be integers"):
        normalize_inference_parameters({"sample_count": 1.5})


def test_rolling_validation_resumes_without_repeating_completed_tasks():
    frame = _frame()
    anchor = frame.iloc[40]["date"]
    calls = []
    checkpoints = []

    def provider(payload):
        calls.append(payload["days"])
        return {**_inference_echo(payload), "predictions": [
            {
                "date": date, "open": 150.0, "high": 152.0,
                "low": 149.0, "close": 151.0,
            }
            for date in payload["future_timestamps"]
        ]}

    complete = run_rolling_validation(
        ["300308"], frame["date"], lambda *args, **kwargs: frame,
        provider, anchor_start=anchor, anchor_end=anchor,
        lookbacks=[32], horizons=[1, 3], anchor_step=1,
    )
    calls.clear()
    interrupted = {**complete, "complete": False, "records": complete["records"][:1]}
    resumed = run_rolling_validation(
        ["300308"], frame["date"], lambda *args, **kwargs: frame,
        provider, anchor_start=anchor, anchor_end=anchor,
        lookbacks=[32], horizons=[1, 3], anchor_step=1,
        resume_artifact=interrupted,
        checkpoint_callback=checkpoints.append,
    )

    assert calls == [3]
    assert len(resumed["records"]) == 2
    assert checkpoints[-1]["complete"] is False
    assert len(checkpoints[-1]["records"]) == 2


def test_rolling_validation_rejects_resume_with_different_configuration():
    frame = _frame()
    anchor = frame.iloc[40]["date"]
    initial = run_rolling_validation(
        ["300308"], frame["date"], lambda *args, **kwargs: frame,
        lambda payload: {**_inference_echo(payload), "predictions": [{
            "date": payload["future_timestamps"][0],
            "open": 150.0, "high": 152.0, "low": 149.0, "close": 151.0,
        }]},
        anchor_start=anchor, anchor_end=anchor,
        lookbacks=[32], horizons=[1], anchor_step=1,
    )

    with pytest.raises(ValueError, match="resume artifact configuration mismatch"):
        run_rolling_validation(
            ["300308"], frame["date"], lambda *args, **kwargs: frame,
            lambda payload: {}, anchor_start=anchor, anchor_end=anchor,
            lookbacks=[64], horizons=[1], anchor_step=1,
            resume_artifact=initial,
        )


def test_rolling_validation_resume_retries_and_replaces_provider_errors():
    frame = _frame()
    anchor = frame.iloc[40]["date"]
    complete = run_rolling_validation(
        ["300308"], frame["date"], lambda *args, **kwargs: frame,
        lambda payload: {**_inference_echo(payload), "predictions": [{
            "date": payload["future_timestamps"][0],
            "open": 150.0, "high": 152.0, "low": 149.0, "close": 151.0,
        }]},
        anchor_start=anchor, anchor_end=anchor,
        lookbacks=[32], horizons=[1], anchor_step=1,
    )
    failed_record = {
        **complete["records"][0],
        "status": "provider_error",
        "error_code": "PROVIDER_TIMEOUT",
    }

    resumed = run_rolling_validation(
        ["300308"], frame["date"], lambda *args, **kwargs: frame,
        lambda payload: {**_inference_echo(payload), "predictions": [{
            "date": payload["future_timestamps"][0],
            "open": 150.0, "high": 152.0, "low": 149.0, "close": 151.0,
        }]},
        anchor_start=anchor, anchor_end=anchor,
        lookbacks=[32], horizons=[1], anchor_step=1,
        resume_artifact={**complete, "complete": False, "records": [failed_record]},
        resume_retry_statuses={"provider_error"},
    )

    assert len(resumed["records"]) == 1
    assert resumed["records"][0]["status"] == "observed"


def test_rolling_validation_marks_missing_stock_bar_not_traded():
    frame = _frame()
    anchor = frame.iloc[40]["date"]
    missing_target = frame.iloc[41]["date"]
    sparse = frame[frame["date"] != missing_target]

    def provider(payload):
        return {
            **_inference_echo(payload),
            "predictions": [{
                "date": payload["future_timestamps"][0],
                "open": 150.0, "high": 152.0, "low": 149.0, "close": 151.0,
            }],
        }

    result = run_rolling_validation(
        ["300308"], frame["date"], lambda *args, **kwargs: sparse,
        provider, anchor_start=anchor, anchor_end=anchor,
        lookbacks=[32], horizons=[1], anchor_step=1,
    )

    assert result["records"][0]["status"] == "not_traded"
    assert result["summary"]["lookback=32,horizon=1"]["n_not_traded"] == 1


def test_rolling_validation_marks_tail_bar_actual_missing():
    frame = _frame()
    anchor = frame.iloc[40]["date"]
    target = frame.iloc[41]["date"]
    truncated = frame[frame["date"] < target]

    result = run_rolling_validation(
        ["300308"], frame["date"], lambda *args, **kwargs: truncated,
        lambda payload: {**_inference_echo(payload), "predictions": [{
            "date": payload["future_timestamps"][0],
            "open": 150.0, "high": 152.0, "low": 149.0, "close": 151.0,
        }]},
        anchor_start=anchor, anchor_end=anchor,
        lookbacks=[32], horizons=[1], anchor_step=1,
    )

    assert result["records"][0]["status"] == "actual_missing"
    assert result["summary"]["lookback=32,horizon=1"]["n_actual_missing"] == 1


def test_rolling_validation_audits_immature_trailing_anchors():
    frame = _frame()
    trailing_anchor = frame.iloc[-2]["date"]

    result = run_rolling_validation(
        ["300308"], frame["date"], lambda *args, **kwargs: frame,
        lambda payload: {}, anchor_start=trailing_anchor, anchor_end=trailing_anchor,
        lookbacks=[32], horizons=[3], anchor_step=1,
    )

    assert result["records"] == []
    assert result["anchor_audit"] == {
        "selected": 1, "mature": 0, "skipped_insufficient_future": 1,
    }


def test_rolling_validation_rejects_terminal_date_mismatch_as_provider_error():
    frame = _frame()
    anchor = frame.iloc[40]["date"]

    result = run_rolling_validation(
        ["300308"], frame["date"], lambda *args, **kwargs: frame,
        lambda payload: {**_inference_echo(payload), "predictions": [{
            "date": "2099-01-01", "open": 1, "high": 1, "low": 1, "close": 1,
        }]},
        anchor_start=anchor, anchor_end=anchor,
        lookbacks=[32], horizons=[1], anchor_step=1,
    )

    assert result["records"][0]["status"] == "provider_error"


def test_rolling_validation_deduplicates_repeated_codes():
    frame = _frame()
    anchor = frame.iloc[40]["date"]

    result = run_rolling_validation(
        ["300308", "300308"], frame["date"], lambda *args, **kwargs: frame,
        lambda payload: {**_inference_echo(payload), "predictions": [{
            "date": payload["future_timestamps"][0],
            "open": 150.0, "high": 152.0, "low": 149.0, "close": 151.0,
        }]},
        anchor_start=anchor, anchor_end=anchor,
        lookbacks=[32], horizons=[1], anchor_step=1,
    )

    assert len(result["records"]) == 1
    assert result["summary"]["lookback=32,horizon=1"]["n_observed"] == 1