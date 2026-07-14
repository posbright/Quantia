#!/usr/bin/env python3
"""Kronos Phase 1 resumable parameter-grid coordinator."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import random
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from quantia.job.kronos_rolling_validation_job import _atomic_write_json


def _csv_ints(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _csv_floats(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def build_configurations(
    lookbacks: Iterable[int],
    sample_counts: Iterable[int],
    temperatures: Iterable[float],
    top_ks: Iterable[int],
    top_ps: Iterable[float],
    clips: Iterable[float],
) -> list[dict[str, Any]]:
    configurations = []
    for values in itertools.product(
        sorted(set(lookbacks)),
        sorted(set(sample_counts)),
        sorted(set(temperatures)),
        sorted(set(top_ks)),
        sorted(set(top_ps)),
        sorted(set(clips)),
    ):
        lookback, sample_count, temperature, top_k, top_p, clip = values
        configurations.append({
            "lookback": int(lookback),
            "sample_count": int(sample_count),
            "temperature": float(temperature),
            "top_k": int(top_k),
            "top_p": float(top_p),
            "clip": float(clip),
        })
    return configurations


def configuration_id(configuration: dict[str, Any]) -> str:
    readable = (
        f"lb{configuration['lookback']:03d}"
        f"_sc{configuration['sample_count']:02d}"
        f"_t{round(configuration['temperature'] * 100):03d}"
        f"_k{configuration['top_k']:04d}"
        f"_p{round(configuration['top_p'] * 100):03d}"
        f"_c{round(configuration['clip'] * 100):04d}"
    )
    digest = hashlib.sha256(
        json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:8]
    return f"{readable}_{digest}"


def _robustness_metrics(
    artifact: dict[str, Any], horizon: int, bootstrap_samples: int,
) -> dict[str, Any]:
    close_deltas_by_code: dict[str, list[float]] = defaultdict(list)
    return_deltas_by_code: dict[str, list[float]] = defaultdict(list)
    for record in artifact.get("records", []):
        if record.get("status") != "observed" or record.get("horizon") != horizon:
            continue
        code = str(record["code"])
        close_deltas_by_code[code].append(
            float(record["close_abs_error"]) - float(record["baseline_close_abs_error"])
        )
        return_deltas_by_code[code].append(
            float(record["return_abs_error"])
            - float(record["baseline_return_abs_error"])
        )
    symbol_close_deltas = {
        code: sum(values) / len(values)
        for code, values in close_deltas_by_code.items()
    }
    symbol_return_deltas = {
        code: sum(values) / len(values)
        for code, values in return_deltas_by_code.items()
    }
    values = list(symbol_return_deltas.values())
    if not values:
        return {
            "n_symbols": 0,
            "symbol_win_rate": None,
            "close_delta_mean": None,
            "return_delta_mean": None,
            "bootstrap_metric": "return_mae_delta",
            "bootstrap_ci_upper": None,
        }

    rng = random.Random(f"{artifact.get('config_hash', '')}:{horizon}")
    bootstrap_means = sorted(
        sum(values[rng.randrange(len(values))] for _ in values) / len(values)
        for _ in range(bootstrap_samples)
    )
    upper_index = min(
        bootstrap_samples - 1,
        max(0, math.ceil(bootstrap_samples * 0.975) - 1),
    )
    return {
        "n_symbols": len(values),
        "symbol_win_rate": (
            sum(delta < 0 for delta in symbol_close_deltas.values()) / len(values)
        ),
        "close_delta_mean": sum(symbol_close_deltas.values()) / len(values),
        "return_delta_mean": sum(values) / len(values),
        "bootstrap_metric": "return_mae_delta",
        "bootstrap_ci_upper": bootstrap_means[upper_index],
    }


def _artifact_audit_failures(
    artifact: dict[str, Any], horizons: Iterable[int],
) -> list[str]:
    failures = []
    if artifact.get("complete") is not True:
        failures.append("artifact: incomplete")

    settings = artifact.get("settings")
    if not isinstance(settings, dict):
        return [*failures, "artifact: missing settings"]
    lookbacks = settings.get("lookbacks")
    if not isinstance(lookbacks, list) or len(lookbacks) != 1:
        failures.append("artifact: expected exactly one lookback")
        return failures
    lookback = int(lookbacks[0])

    codes = settings.get("codes")
    if not isinstance(codes, list) or not codes or len(set(map(str, codes))) != len(codes):
        failures.append("artifact: invalid codes")
        return failures
    mature_anchors = artifact.get("anchor_audit", {}).get("mature")
    if not isinstance(mature_anchors, int) or mature_anchors < 1:
        failures.append("artifact: invalid mature anchor count")
        return failures

    records = artifact.get("records")
    if not isinstance(records, list):
        return [*failures, "artifact: records must be a list"]
    task_keys = [
        (
            str(record.get("code")), str(record.get("anchor_date")),
            record.get("lookback"), record.get("horizon"),
        )
        for record in records
    ]
    if len(task_keys) != len(set(task_keys)):
        failures.append("artifact: duplicate task keys")

    observed = [record for record in records if record.get("status") == "observed"]
    fingerprint_fields = ("model_version", "predictor_version", "tokenizer_version")
    for field in fingerprint_fields:
        values = {record.get(field) for record in observed}
        if len(values) != 1 or None in values or "" in values:
            failures.append(f"artifact: inconsistent {field}")

    expected_per_horizon = len(codes) * mature_anchors
    summary = artifact.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    finite_fields = (
        "close_abs_error", "baseline_close_abs_error",
        "return_abs_error", "baseline_return_abs_error",
    )
    for horizon in horizons:
        rows = [
            record for record in records
            if record.get("lookback") == lookback and record.get("horizon") == horizon
        ]
        if len(rows) != expected_per_horizon:
            failures.append(
                f"horizon={horizon}: records!={expected_per_horizon}"
            )
        counts_by_code = {
            str(code): sum(str(row.get("code")) == str(code) for row in rows)
            for code in codes
        }
        if any(count != mature_anchors for count in counts_by_code.values()):
            failures.append(f"horizon={horizon}: unequal anchors by symbol")

        horizon_observed = [row for row in rows if row.get("status") == "observed"]
        for row in horizon_observed:
            try:
                finite = all(math.isfinite(float(row[field])) for field in finite_fields)
            except (KeyError, TypeError, ValueError):
                finite = False
            if not finite:
                failures.append(f"horizon={horizon}: invalid observed errors")
                break

        key = f"lookback={lookback},horizon={horizon}"
        metrics = summary.get(key)
        if not isinstance(metrics, dict):
            failures.append(f"horizon={horizon}: missing summary")
            continue
        expected_summary = {
            "n_expected": len(rows),
            "n_observed": len(horizon_observed),
            "n_provider_error": sum(
                row.get("status") == "provider_error" for row in rows
            ),
            "coverage": len(horizon_observed) / len(rows) if rows else 0.0,
        }
        if any(
            not isinstance(metrics.get(field), (int, float))
            or not math.isclose(
                float(metrics[field]), float(expected), abs_tol=1e-12
            )
            for field, expected in expected_summary.items()
        ):
            failures.append(f"horizon={horizon}: summary counts mismatch")
        if horizon_observed:
            record_delta = sum(
                float(row["close_abs_error"])
                - float(row["baseline_close_abs_error"])
                for row in horizon_observed
            ) / len(horizon_observed)
            summary_delta = metrics.get("close_mae_vs_baseline")
            if (
                not isinstance(summary_delta, (int, float))
                or not math.isfinite(float(summary_delta))
                or not math.isclose(record_delta, float(summary_delta), abs_tol=1e-12)
            ):
                failures.append(f"horizon={horizon}: summary mismatch")
    return failures


def evaluate_candidate(
    artifact: dict[str, Any], horizons: Iterable[int], *,
    bootstrap_samples: int = 5000, min_symbols: int = 8,
    min_symbol_win_rate: float = 0.5,
) -> dict[str, Any]:
    horizons = list(horizons)
    artifact_failures = _artifact_audit_failures(artifact, horizons)
    operational_failures = list(artifact_failures)
    robustness_failures = []
    robustness = {}
    lookbacks = artifact.get("settings", {}).get("lookbacks", [])
    lookback = lookbacks[0] if len(lookbacks) == 1 else None
    for horizon in horizons:
        metrics = artifact.get("summary", {}).get(
            f"lookback={lookback},horizon={horizon}", {}
        )
        if metrics.get("coverage") != 1.0:
            operational_failures.append(f"horizon={horizon}: coverage<1")
        if metrics.get("n_provider_error", 0) != 0:
            operational_failures.append(f"horizon={horizon}: provider_error")
        delta = metrics.get("close_mae_vs_baseline")
        if delta is None or delta >= 0:
            operational_failures.append(f"horizon={horizon}: delta>=0")

        robust = _robustness_metrics(artifact, horizon, bootstrap_samples)
        robustness[f"horizon={horizon}"] = robust
        if robust["n_symbols"] < min_symbols:
            robustness_failures.append(f"horizon={horizon}: symbols<{min_symbols}")
        win_rate = robust["symbol_win_rate"]
        if win_rate is None or win_rate <= min_symbol_win_rate:
            robustness_failures.append(
                f"horizon={horizon}: symbol_win_rate<={min_symbol_win_rate}"
            )
        upper = robust["bootstrap_ci_upper"]
        if upper is None or upper >= 0:
            robustness_failures.append(f"horizon={horizon}: bootstrap_ci_upper>=0")

    operational_qualified = not operational_failures
    robust_qualified = not robustness_failures
    return {
        "qualified": operational_qualified and robust_qualified,
        "operational_qualified": operational_qualified,
        "robust_qualified": robust_qualified,
        "failures": [*operational_failures, *robustness_failures],
        "operational_failures": operational_failures,
        "artifact_failures": artifact_failures,
        "robustness_failures": robustness_failures,
        "robustness": robustness,
    }


def _command(args: argparse.Namespace, configuration: dict[str, Any], output: Path) -> list[str]:
    command = [
        sys.executable,
        "-m", "quantia.job.kronos_rolling_validation_job",
        "--codes", args.codes,
        "--anchor-start", args.anchor_start,
        "--anchor-end", args.anchor_end,
        "--lookbacks", str(configuration["lookback"]),
        "--horizons", args.horizons,
        "--anchor-step", str(args.anchor_step),
        "--max-anchors", str(args.max_anchors),
        "--sample-count", str(configuration["sample_count"]),
        "--temperature", str(configuration["temperature"]),
        "--top-k", str(configuration["top_k"]),
        "--top-p", str(configuration["top_p"]),
        "--clip", str(configuration["clip"]),
        "--provider-url", args.provider_url,
        "--timeout", str(args.timeout),
        "--checkpoint-every", str(args.checkpoint_every),
        "--output", str(output),
    ]
    if args.actual_end:
        command.extend(["--actual-end", args.actual_end])
    if args.resume:
        command.append("--resume")
    return command


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a resumable Kronos Phase 1 parameter grid")
    parser.add_argument("--codes", required=True)
    parser.add_argument("--anchor-start", required=True)
    parser.add_argument("--anchor-end", required=True)
    parser.add_argument("--actual-end")
    parser.add_argument("--lookbacks", default="64,128,192,256")
    parser.add_argument("--horizons", default="1,3,5")
    parser.add_argument("--sample-counts", default="5,10")
    parser.add_argument("--temperatures", default="0.7,1.0")
    parser.add_argument("--top-ks", default="0")
    parser.add_argument("--top-ps", default="0.85,0.95")
    parser.add_argument("--clips", default="5.0")
    parser.add_argument("--anchor-step", type=int, default=5)
    parser.add_argument("--max-anchors", type=int, default=3)
    parser.add_argument("--provider-url", default="http://127.0.0.1:18081/v1/open-api/kpred")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--checkpoint-every", type=int, default=1)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-configs", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--bootstrap-samples", type=int, default=5000)
    parser.add_argument("--min-symbols", type=int, default=8)
    parser.add_argument("--min-symbol-win-rate", type=float, default=0.5)
    args = parser.parse_args()
    if args.bootstrap_samples < 100:
        parser.error("bootstrap-samples must be at least 100")
    if args.min_symbols < 2:
        parser.error("min-symbols must be at least 2")
    if not 0 < args.min_symbol_win_rate < 1:
        parser.error("min-symbol-win-rate must be within (0, 1)")

    horizons = _csv_ints(args.horizons)
    configurations = build_configurations(
        _csv_ints(args.lookbacks),
        _csv_ints(args.sample_counts),
        _csv_floats(args.temperatures),
        _csv_ints(args.top_ks),
        _csv_floats(args.top_ps),
        _csv_floats(args.clips),
    )
    if args.max_configs > 0:
        configurations = configurations[:args.max_configs]
    if not configurations:
        parser.error("parameter grid is empty")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "complete": False,
        "configuration_count": len(configurations),
        "horizons": horizons,
        "robustness_gate": {
            "bootstrap_samples": args.bootstrap_samples,
            "bootstrap_quantile": 0.975,
            "min_symbols": args.min_symbols,
            "min_symbol_win_rate": args.min_symbol_win_rate,
        },
        "runs": [],
    }

    for index, configuration in enumerate(configurations, start=1):
        run_id = configuration_id(configuration)
        output = output_dir / f"{run_id}.json"
        existing = None
        if args.resume and output.is_file():
            existing = json.loads(output.read_text(encoding="utf-8"))
        has_provider_errors = bool(existing) and any(
            record.get("status") == "provider_error"
            for record in existing.get("records", [])
        )
        if existing and existing.get("complete") is True and not has_provider_errors:
            candidate = evaluate_candidate(
                existing, horizons,
                bootstrap_samples=args.bootstrap_samples,
                min_symbols=args.min_symbols,
                min_symbol_win_rate=args.min_symbol_win_rate,
            )
            manifest["runs"].append({
                "id": run_id,
                "configuration": configuration,
                "status": "completed",
                "output": str(output),
                **candidate,
            })
            _atomic_write_json(manifest_path, manifest)
            continue

        run_state = {
            "id": run_id,
            "configuration": configuration,
            "status": "running",
            "output": str(output),
        }
        manifest["runs"].append(run_state)
        _atomic_write_json(manifest_path, manifest)
        print(f"[grid {index}/{len(configurations)}] {run_id}", flush=True)
        completed = subprocess.run(_command(args, configuration, output), check=False)
        if completed.returncode != 0:
            run_state["status"] = "failed"
            run_state["returncode"] = completed.returncode
            _atomic_write_json(manifest_path, manifest)
            if not args.continue_on_error:
                raise SystemExit(completed.returncode)
            continue

        artifact = json.loads(output.read_text(encoding="utf-8"))
        run_state["status"] = "completed"
        run_state.update(evaluate_candidate(
            artifact, horizons,
            bootstrap_samples=args.bootstrap_samples,
            min_symbols=args.min_symbols,
            min_symbol_win_rate=args.min_symbol_win_rate,
        ))
        run_state["config_hash"] = artifact.get("config_hash")
        _atomic_write_json(manifest_path, manifest)

    manifest["complete"] = all(run["status"] == "completed" for run in manifest["runs"])
    manifest["qualified_count"] = sum(bool(run.get("qualified")) for run in manifest["runs"])
    manifest["operational_qualified_count"] = sum(
        bool(run.get("operational_qualified")) for run in manifest["runs"]
    )
    _atomic_write_json(manifest_path, manifest)
    print(json.dumps({
        "manifest": str(manifest_path),
        "complete": manifest["complete"],
        "configurations": len(configurations),
        "qualified": manifest["qualified_count"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
