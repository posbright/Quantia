from quantia.job.kronos_parameter_search_job import (
    build_configurations,
    configuration_id,
    evaluate_candidate,
)


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
    assert result["failures"] == ["horizon=3: delta>=0"]


def test_evaluate_candidate_accepts_complete_negative_deltas():
    artifact = {
        "settings": {"lookbacks": [128]},
        "summary": {
            "lookback=128,horizon=1": {
                "coverage": 1.0,
                "n_provider_error": 0,
                "close_mae_vs_baseline": -0.2,
            },
        },
    }

    assert evaluate_candidate(artifact, [1]) == {
        "qualified": True,
        "failures": [],
    }
