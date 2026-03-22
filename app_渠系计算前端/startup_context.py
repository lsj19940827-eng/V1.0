# -*- coding: utf-8 -*-
"""Startup context shared between bootstrap and UI assembly."""

from dataclasses import dataclass
from typing import Optional

from app_渠系计算前端.webengine_diagnostics import WebEngineProbeResult


@dataclass(frozen=True)
class StartupContext:
    """Immutable startup facts prepared before the main window is built."""

    webengine_mode: str
    webengine_probe_result: Optional[WebEngineProbeResult]
    update_checks_enabled: bool
    is_frozen_runtime: bool
