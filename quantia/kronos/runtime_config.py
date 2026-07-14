"""Versioned runtime configuration for the Kronos shadow control plane."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping

_CONFIG_PATH = Path(os.environ.get(
    "QUANTIA_KRONOS_CONFIG_PATH",
    Path(__file__).with_name("runtime_config.json"),
))

DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 1,
    "enabled": False,
    "mode": "shadow",
    "qualification_status": "not_qualified",
    "preset_name": "approximate-short-context-v1",
    "provider_url": "http://127.0.0.1:18081/v1/open-api/kpred",
    "lookback": 48,
    "horizons": [1, 3, 5],
    "sample_count": 10,
    "sample_batch_size": 5,
    "temperature": 0.9,
    "top_k": 0,
    "top_p": 0.85,
    "clip": 5.0,
    "timeout_seconds": 600,
    "require_human_approval": True,
    "notes": "工程联调近似预设，尚未通过独立 holdout，不参与交易决策。",
}


def _number(value: Any, field: str, lower: float, upper: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not lower <= result <= upper:
        raise ValueError(f"{field} must be within {lower}..{upper}")
    return result


def validate_config(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("configuration must be an object")
    config = copy.deepcopy(DEFAULT_CONFIG)
    config.update({key: value for key, value in raw.items() if key in DEFAULT_CONFIG})
    config["enabled"] = bool(config["enabled"])
    config["require_human_approval"] = bool(config["require_human_approval"])
    if config["mode"] not in {"shadow", "canary", "production"}:
        raise ValueError("mode must be shadow/canary/production")
    if config["qualification_status"] not in {"not_qualified", "challenger", "qualified"}:
        raise ValueError("qualification_status is invalid")
    if config["mode"] != "shadow" and config["qualification_status"] != "qualified":
        raise ValueError("canary/production requires a qualified preset")
    if config["enabled"] and config["qualification_status"] != "qualified":
        raise ValueError("unqualified preset cannot enable automatic production runs")

    config["lookback"] = int(_number(config["lookback"], "lookback", 32, 512))
    config["sample_count"] = int(_number(config["sample_count"], "sample_count", 1, 64))
    config["sample_batch_size"] = int(_number(
        config["sample_batch_size"], "sample_batch_size", 1, 64,
    ))
    if config["sample_batch_size"] > config["sample_count"]:
        raise ValueError("sample_batch_size cannot exceed sample_count")
    config["temperature"] = _number(config["temperature"], "temperature", 0.05, 5.0)
    config["top_k"] = int(_number(config["top_k"], "top_k", 0, 1024))
    config["top_p"] = _number(config["top_p"], "top_p", 0.01, 1.0)
    config["clip"] = _number(config["clip"], "clip", 1.0, 20.0)
    config["timeout_seconds"] = int(_number(
        config["timeout_seconds"], "timeout_seconds", 1, 3600,
    ))
    horizons = config["horizons"]
    if not isinstance(horizons, list) or not horizons:
        raise ValueError("horizons must be a non-empty list")
    normalized_horizons = sorted({int(_number(item, "horizon", 1, 30)) for item in horizons})
    config["horizons"] = normalized_horizons
    config["provider_url"] = str(config["provider_url"]).strip()
    if not config["provider_url"].startswith(("http://", "https://")):
        raise ValueError("provider_url must be http(s)")
    config["preset_name"] = str(config["preset_name"]).strip()[:80]
    config["notes"] = str(config["notes"]).strip()[:1000]
    config["schema_version"] = 1
    return config


def _with_metadata(config: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(config)
    canonical = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    result["config_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    result["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return result


def load_config(path: Path | None = None) -> dict[str, Any]:
    target = path or _CONFIG_PATH
    if not target.is_file():
        return _with_metadata(validate_config(DEFAULT_CONFIG))
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload.pop("config_hash", None)
    payload.pop("updated_at", None)
    return _with_metadata(validate_config(payload))


def save_config(raw: Mapping[str, Any], path: Path | None = None) -> dict[str, Any]:
    target = path or _CONFIG_PATH
    result = _with_metadata(validate_config(raw))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    for attempt in range(20):
        try:
            temporary.replace(target)
            return result
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(min(0.05 * (attempt + 1), 0.5))
    raise RuntimeError("unreachable")
