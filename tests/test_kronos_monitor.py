import json
from pathlib import Path
from unittest import mock

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

from quantia.kronos.monitor import list_runs, overview
from quantia.kronos.runtime_config import load_config, save_config, validate_config
from quantia.web import kronosMonitorHandler as handler


def _artifact(records=3):
    return {
        "complete": True,
        "records": [
            {
                "status": "observed",
                "applied_inference_parameters": {"sample_count": 10},
                "model_version": "bundle",
                "predictor_version": "predictor",
                "tokenizer_version": "tokenizer",
            }
            for _ in range(records)
        ],
        "summary": {"lookback=48,horizon=1": {"n_expected": records}},
    }


def test_runtime_config_round_trip_and_guard(tmp_path):
    path = tmp_path / "kronos.json"
    saved = save_config({"lookback": 48, "sample_count": 10}, path)
    loaded = load_config(path)

    assert loaded["config_hash"] == saved["config_hash"]
    assert loaded["mode"] == "shadow"
    assert loaded["enabled"] is False

    with mock.patch.dict("os.environ", {}, clear=False):
        try:
            validate_config({"enabled": True, "qualification_status": "not_qualified"})
        except ValueError as exc:
            assert "cannot enable" in str(exc)
        else:
            raise AssertionError("unqualified automatic run must be rejected")


def test_monitor_aggregates_manifest_and_artifacts(tmp_path):
    run_dir = tmp_path / "h2"
    run_dir.mkdir()
    output = run_dir / "candidate.json"
    output.write_text(json.dumps(_artifact()), encoding="utf-8")
    (run_dir / "manifest.json").write_text(json.dumps({
        "complete": False,
        "configuration_count": 2,
        "runs": [{
            "id": "candidate",
            "output": str(output),
            "status": "completed",
            "qualified": False,
        }],
    }), encoding="utf-8")

    runs = list_runs(tmp_path)

    assert len(runs) == 1
    assert runs[0]["records"] == 3
    assert runs[0]["expected_records"] == 6
    assert runs[0]["progress"] == 0.5
    assert runs[0]["audited"] == 3
    assert overview(tmp_path)["latest"]["name"] == "h2"


class TestKronosMonitorApi(AsyncHTTPTestCase):
    def get_app(self):
        return Application([
            (r"/quantia/api/kronos/config", handler.KronosConfigHandler),
            (r"/quantia/api/kronos/monitor/overview", handler.KronosOverviewHandler),
            (r"/quantia/api/kronos/monitor/runs", handler.KronosRunsHandler),
            (r"/quantia/api/kronos/monitor/health", handler.KronosHealthHandler),
        ])

    def test_config_get(self):
        with mock.patch.object(handler, "load_config", return_value={"mode": "shadow"}):
            response = self.fetch("/quantia/api/kronos/config")
        assert response.code == 200
        assert json.loads(response.body)["data"]["mode"] == "shadow"

    def test_config_rejects_invalid_payload(self):
        with mock.patch.object(handler, "save_config", side_effect=ValueError("invalid")):
            response = self.fetch(
                "/quantia/api/kronos/config", method="POST",
                headers={"Content-Type": "application/json"}, body="{}",
            )
        assert response.code == 400

    def test_overview(self):
        with mock.patch.object(handler, "load_config", return_value={"mode": "shadow"}), \
                mock.patch.object(handler, "overview", return_value={"run_count": 2}):
            response = self.fetch("/quantia/api/kronos/monitor/overview")
        payload = json.loads(response.body)
        assert payload["data"]["run_count"] == 2

    def test_health_uses_provider_origin(self):
        with mock.patch.object(handler, "load_config", return_value={
            "provider_url": "http://127.0.0.1:18081/v1/open-api/kpred",
        }), mock.patch.object(handler, "_provider_health", return_value={
            "reachable": True, "url": "http://127.0.0.1:18081/health",
        }):
            response = self.fetch("/quantia/api/kronos/monitor/health")
        payload = json.loads(response.body)
        assert payload["data"]["url"].endswith("/health")