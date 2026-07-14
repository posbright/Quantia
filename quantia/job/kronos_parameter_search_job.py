#!/usr/bin/env python3
"""Kronos Phase 1 resumable parameter-grid coordinator."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import subprocess
import sys
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


def evaluate_candidate(artifact: dict[str, Any], horizons: Iterable[int]) -> dict[str, Any]:
    failures = []
    for horizon in horizons:
        lookback = artifact["settings"]["lookbacks"][0]
        metrics = artifact.get("summary", {}).get(
            f"lookback={lookback},horizon={horizon}", {}
        )
        if metrics.get("coverage") != 1.0:
            failures.append(f"horizon={horizon}: coverage<1")
        if metrics.get("n_provider_error", 0) != 0:
            failures.append(f"horizon={horizon}: provider_error")
        delta = metrics.get("close_mae_vs_baseline")
        if delta is None or delta >= 0:
            failures.append(f"horizon={horizon}: delta>=0")
    return {"qualified": not failures, "failures": failures}


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
    args = parser.parse_args()

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
            candidate = evaluate_candidate(existing, horizons)
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
        run_state.update(evaluate_candidate(artifact, horizons))
        run_state["config_hash"] = artifact.get("config_hash")
        _atomic_write_json(manifest_path, manifest)

    manifest["complete"] = all(run["status"] == "completed" for run in manifest["runs"])
    manifest["qualified_count"] = sum(bool(run.get("qualified")) for run in manifest["runs"])
    _atomic_write_json(manifest_path, manifest)
    print(json.dumps({
        "manifest": str(manifest_path),
        "complete": manifest["complete"],
        "configurations": len(configurations),
        "qualified": manifest["qualified_count"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
