#!/usr/bin/env python3
"""Kronos control-plane configuration and read-only monitoring APIs."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC
from concurrent.futures import ThreadPoolExecutor

from tornado import gen
from tornado.ioloop import IOLoop

import quantia.web.base as webBase
from quantia.kronos.monitor import list_runs, overview
from quantia.kronos.runtime_config import load_config, save_config

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="kronos-monitor")


def _write_json(handler, body, status=200):
    handler.set_status(status)
    handler.set_header("Content-Type", "application/json;charset=UTF-8")
    handler.write(json.dumps(body, ensure_ascii=False, default=str))


def _provider_health(config):
    provider_url = config["provider_url"]
    parsed = urllib.parse.urlsplit(provider_url)
    health_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/health", "", ""))
    request = urllib.request.Request(health_url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"reachable": False, "url": health_url, "error": str(exc)}
    return {"reachable": True, "url": health_url, "data": payload}


class KronosConfigHandler(webBase.BaseHandler, ABC):
    def get(self):
        _write_json(self, {"ok": True, "data": load_config()})

    def post(self):
        try:
            body = json.loads(self.request.body or b"{}")
            config = save_config(body)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            _write_json(self, {"ok": False, "error": str(exc)}, 400)
            return
        _write_json(self, {"ok": True, "data": config})


class KronosOverviewHandler(webBase.BaseHandler, ABC):
    def get(self):
        _write_json(self, {
            "ok": True,
            "data": {"config": load_config(), **overview()},
        })


class KronosRunsHandler(webBase.BaseHandler, ABC):
    def get(self):
        _write_json(self, {"ok": True, "data": list_runs()})


class KronosHealthHandler(webBase.BaseHandler, ABC):
    @gen.coroutine
    def get(self):
        result = yield IOLoop.current().run_in_executor(
            _EXECUTOR, _provider_health, load_config(),
        )
        _write_json(self, {"ok": True, "data": result})
