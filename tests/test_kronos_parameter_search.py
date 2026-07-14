from quantia.job.kronos_parameter_search_job import (
    build_configurations,
    configuration_id,
    evaluate_candidate,
)


def _observed(code, *, close_error=0.8, baseline_error=1.0, anchor="2026-03-02"):
    return {
        "code": code,
        "anchor_date": anchor,
        "lookback": 64,
        "horizon": 1,
        "status": "observed",
        "close_abs_error": close_error,
        "baseline_close_abs_error": baseline_error,
        "return_abs_error": close_error / 10.0,
        "baseline_return_abs_error": baseline_error / 10.0,
        "model_version": "model",
        "predictor_version": "predictor",
        "tokenizer_version": "tokenizer",
    }


def _artifact(records, delta):
    codes = list(dict.fromkeys(record["code"] for record in records))
    return {
        "complete": True,
        "config_hash": "test",
        "settings": {"codes": codes, "lookbacks": [64]},
        "anchor_audit": {"mature": 1},
        "mixed_model_versions": False,
        "records": records,
        "summary": {
            "lookback=64,horizon=1": {
                "n_expected": len(records),
                "n_observed": len(records),
                "coverage": 1.0,
                "n_provider_error": 0,
                "close_mae_vs_baseline": delta,
            },
        },
    }


def test_build_configurations_is_deterministic_and_deduplicated():
    configurations = build_configurations(
        [128, 64, 64], [10, 5], [1.0, 0.7], [0], [0.95, 0.85], [5.0],
    )

    assert len(configurations) == 16
    assert configurations[0] == {
        "lookback": 64,
        "sample_count": 5,
        "temperature": 0.7,
        "top_k": 0,
        "top_p": 0.85,
        "clip": 5.0,
    }
    run_id = configuration_id(configurations[0])
    assert run_id.startswith("lb064_sc05_t070_k0000_p085_c0500_")
    assert len(run_id.rsplit("_", 1)[-1]) == 8


def test_evaluate_candidate_requires_every_horizon_to_beat_baseline():
    artifact = {
        "settings": {"lookbacks": [64]},
        "summary": {
            "lookback=64,horizon=1": {
                "coverage": 1.0,
                "n_provider_error": 0,
                "close_mae_vs_baseline": -0.2,
            },
            "lookback=64,horizon=3": {
                "coverage": 1.0,
                "n_provider_error": 0,
                "close_mae_vs_baseline": 0.1,
            },
        },
    }

    result = evaluate_candidate(artifact, [1, 3])

    assert result["qualified"] is False
    assert result["operational_qualified"] is False
    assert "horizon=3: delta>=0" in result["operational_failures"]


def test_evaluate_candidate_accepts_complete_negative_deltas():
    records = [_observed(f"{index:06d}") for index in range(8)]
    artifact = _artifact(records, -0.2)

    result = evaluate_candidate(artifact, [1], bootstrap_samples=100)

    assert result["qualified"] is True
    assert result["operational_qualified"] is True
    assert result["robust_qualified"] is True
    assert result["failures"] == []
    assert result["robustness"]["horizon=1"]["symbol_win_rate"] == 1.0
    assert result["robustness"]["horizon=1"]["bootstrap_metric"] == "return_mae_delta"


def test_evaluate_candidate_rejects_single_symbol_concentration():
    records = [
        _observed(
            f"{index:06d}", close_error=0.0 if index == 0 else 1.1,
            baseline_error=10.0 if index == 0 else 1.0,
        )
        for index in range(8)
    ]
    artifact = _artifact(records, (-10.0 + 7 * 0.1) / 8)

    result = evaluate_candidate(artifact, [1], bootstrap_samples=100)

    assert result["operational_qualified"] is True
    assert result["robust_qualified"] is False
    assert result["qualified"] is False
    assert result["robustness"]["horizon=1"]["symbol_win_rate"] == 0.125
    assert "horizon=1: symbol_win_rate<=0.5" in result["robustness_failures"]


def test_evaluate_candidate_rejects_unequal_symbol_clusters():
    records = [
        _observed(
            "000001", close_error=0.0, baseline_error=10.0,
            anchor=f"2026-03-{index + 1:02d}",
        )
        for index in range(20)
    ]
    records.extend(
        _observed(f"{index:06d}", close_error=1.1, baseline_error=1.0)
        for index in range(2, 9)
    )
    artifact = _artifact(records, (-200.0 + 0.7) / 27)
    artifact["anchor_audit"]["mature"] = 20

    result = evaluate_candidate(artifact, [1], bootstrap_samples=100)

    robust = result["robustness"]["horizon=1"]
    assert robust["n_symbols"] == 8
    assert robust["symbol_win_rate"] == 0.125
    assert result["operational_qualified"] is False
    assert result["robust_qualified"] is False
    assert "horizon=1: unequal anchors by symbol" in result["artifact_failures"]


def test_evaluate_candidate_rejects_incomplete_or_duplicate_artifact():
    records = [_observed(f"{index:06d}") for index in range(8)]
    artifact = _artifact(records, -0.2)
    artifact["complete"] = False
    artifact["records"].append(dict(records[0]))

    result = evaluate_candidate(artifact, [1], bootstrap_samples=100)

    assert result["qualified"] is False
    assert "artifact: incomplete" in result["artifact_failures"]
    assert "artifact: duplicate task keys" in result["artifact_failures"]


def test_evaluate_candidate_rejects_nonfinite_and_summary_mismatch():
    records = [_observed(f"{index:06d}") for index in range(8)]
    artifact = _artifact(records, -0.2)
    artifact["records"][0]["return_abs_error"] = float("nan")
    artifact["summary"]["lookback=64,horizon=1"]["close_mae_vs_baseline"] = -0.3

    result = evaluate_candidate(artifact, [1], bootstrap_samples=100)

    assert result["qualified"] is False
    assert "horizon=1: invalid observed errors" in result["artifact_failures"]
    assert "horizon=1: summary mismatch" in result["artifact_failures"]


def test_evaluate_candidate_rejects_stale_summary_counts():
    records = [_observed(f"{index:06d}") for index in range(8)]
    artifact = _artifact(records, -0.2)
    artifact["records"][0]["status"] = "provider_error"

    result = evaluate_candidate(artifact, [1], bootstrap_samples=100)

    assert result["qualified"] is False
    assert "horizon=1: summary counts mismatch" in result["artifact_failures"]
