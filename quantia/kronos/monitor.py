"""Read-only aggregation of Kronos validation artifacts for the Web control plane."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_RUNS_ROOT = _REPO_ROOT.parent / "runs" / "kronos_validation"


def runs_root() -> Path:
    return Path(os.environ.get("QUANTIA_KRONOS_RUNS_DIR", _DEFAULT_RUNS_ROOT))


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def _artifact_stats(path: Path) -> dict[str, Any]:
    artifact = _read_json(path)
    records = artifact.get("records", [])
    if not isinstance(records, list):
        records = []
    fingerprints = {
        key: sorted({str(row.get(key)) for row in records if row.get(key)})
        for key in ("model_version", "predictor_version", "tokenizer_version")
    }
    return {
        "records": len(records),
        "complete": artifact.get("complete") is True,
        "observed": sum(row.get("status") == "observed" for row in records),
        "provider_errors": sum(row.get("status") == "provider_error" for row in records),
        "audited": sum(bool(row.get("applied_inference_parameters")) for row in records),
        "fingerprints": fingerprints,
        "summary": artifact.get("summary", {}),
    }


def list_runs(root: Path | None = None) -> list[dict[str, Any]]:
    base = root or runs_root()
    if not base.is_dir():
        return []
    result = []
    for manifest_path in base.glob("*/manifest.json"):
        try:
            manifest = _read_json(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            result.append({
                "name": manifest_path.parent.name,
                "path": str(manifest_path.parent),
                "status": "invalid",
                "error": str(exc),
                "updated_at": manifest_path.stat().st_mtime,
            })
            continue
        rows = []
        total_records = observed = provider_errors = audited = 0
        expected_per_config = 0
        for run in manifest.get("runs", []):
            output = Path(str(run.get("output", "")))
            stats = None
            if output.is_file():
                try:
                    stats = _artifact_stats(output)
                except (OSError, ValueError, json.JSONDecodeError):
                    stats = None
            row = {
                "id": run.get("id"),
                "configuration": run.get("configuration", {}),
                "status": run.get("status", "unknown"),
                "qualified": run.get("qualified"),
                "operational_qualified": run.get("operational_qualified"),
                "robust_qualified": run.get("robust_qualified"),
                "failures": run.get("failures", []),
                "records": stats["records"] if stats else 0,
                "complete": stats["complete"] if stats else False,
            }
            rows.append(row)
            if stats:
                total_records += stats["records"]
                observed += stats["observed"]
                provider_errors += stats["provider_errors"]
                audited += stats["audited"]
                if stats["complete"] and not expected_per_config:
                    expected_per_config = sum(
                        int(item.get("n_expected", 0))
                        for item in stats["summary"].values()
                        if isinstance(item, dict)
                    )
        configuration_count = int(manifest.get("configuration_count") or len(rows))
        expected = expected_per_config * configuration_count
        status = "completed" if manifest.get("complete") is True else "running"
        if any(row["status"] == "failed" for row in rows):
            status = "partial" if status != "completed" else status
        result.append({
            "name": manifest_path.parent.name,
            "path": str(manifest_path.parent),
            "status": status,
            "complete": manifest.get("complete") is True,
            "configuration_count": configuration_count,
            "represented_configurations": len(rows),
            "completed_configurations": sum(row["status"] == "completed" for row in rows),
            "qualified_count": sum(row.get("qualified") is True for row in rows),
            "records": total_records,
            "expected_records": expected,
            "progress": round(total_records / expected, 4) if expected else None,
            "observed": observed,
            "provider_errors": provider_errors,
            "audited": audited,
            "updated_at": manifest_path.stat().st_mtime,
            "configurations": rows,
        })
    return sorted(result, key=lambda item: item["updated_at"], reverse=True)


def overview(root: Path | None = None) -> dict[str, Any]:
    runs = list_runs(root)
    latest = runs[0] if runs else None
    return {
        "runs_root": str(root or runs_root()),
        "run_count": len(runs),
        "latest": latest,
        "has_qualified_candidate": any(run.get("qualified_count", 0) > 0 for run in runs),
    }
