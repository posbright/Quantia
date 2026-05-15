#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class NotificationSendResult:
    ok: bool
    status_code: Optional[int] = None
    response: Optional[Dict[str, Any]] = None
    error: str = ""


class NotificationChannel:
    """Base class for notification channels."""

    channel = "base"

    def send(self, payload: Dict[str, Any]) -> NotificationSendResult:
        raise NotImplementedError