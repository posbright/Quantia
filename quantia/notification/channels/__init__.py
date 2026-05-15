#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Notification channel implementations."""

from .base import NotificationChannel, NotificationSendResult
from .dingtalk import DingTalkChannel

__all__ = ["NotificationChannel", "NotificationSendResult", "DingTalkChannel"]