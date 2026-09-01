# -*- coding: utf-8 -*-
"""Panel registry used by the main window and project manager."""

import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

from PySide6.QtCore import QObject, Signal


@dataclass(frozen=True)
class PanelDescriptor:
    """Describes one visible panel in the main stacked widget."""

    key: str
    title: str
    nav_order: int
    attr_name: str
    factory: Callable[[], Any]
    project_slot: str


class PanelRegistry(QObject):
    """Creates panels on demand while keeping a stable registry contract."""

    instance_created = Signal(str, object)

    def __init__(self, descriptors: Iterable[PanelDescriptor], parent=None):
        super().__init__(parent)
        ordered = sorted(descriptors, key=lambda item: item.nav_order)
        self._descriptors: List[PanelDescriptor] = ordered
        self._descriptors_by_key: Dict[str, PanelDescriptor] = {
            descriptor.key: descriptor for descriptor in ordered
        }
        self._descriptors_by_attr: Dict[str, PanelDescriptor] = {
            descriptor.attr_name: descriptor for descriptor in ordered
        }
        self._descriptors_by_project_slot: Dict[str, PanelDescriptor] = {
            descriptor.project_slot: descriptor for descriptor in ordered
        }
        self._instances: Dict[str, Any] = {}

    @property
    def descriptors(self) -> List[PanelDescriptor]:
        return list(self._descriptors)

    def create_all_eagerly(self) -> List[Any]:
        return [self.get(descriptor.key) for descriptor in self._descriptors]

    def get(self, key: str) -> Any:
        if key not in self._instances:
            descriptor = self._descriptors_by_key[key]
            trace_enabled = os.environ.get("CANAL_STARTUP_TRACE", "").strip() == "1"
            started_at = time.perf_counter()
            if trace_enabled:
                print(f"[StartupTrace] panel_start key={key}", flush=True)
            instance = descriptor.factory()
            self._instances[key] = instance
            self.instance_created.emit(key, instance)
            if trace_enabled:
                elapsed = time.perf_counter() - started_at
                print(
                    f"[StartupTrace] panel_ready key={key} elapsed={elapsed:.3f}s",
                    flush=True,
                )
        return self._instances[key]

    def get_existing(self, key: str) -> Optional[Any]:
        return self._instances.get(key)

    def get_by_attr_name(self, attr_name: str) -> Optional[Any]:
        descriptor = self._descriptors_by_attr.get(attr_name)
        if descriptor is None:
            return None
        return self.get(descriptor.key)

    def descriptor_for_project_slot(self, project_slot: str) -> Optional[PanelDescriptor]:
        return self._descriptors_by_project_slot.get(project_slot)

    def descriptor_for_attr_name(self, attr_name: str) -> Optional[PanelDescriptor]:
        return self._descriptors_by_attr.get(attr_name)

    def descriptor_for_key(self, key: str) -> Optional[PanelDescriptor]:
        """按稳定键返回面板描述。"""
        return self._descriptors_by_key.get(key)

    def iter_instances(self, *, create_missing: bool = False) -> List[Any]:
        if create_missing:
            return [self.get(descriptor.key) for descriptor in self._descriptors]
        return [
            self._instances[descriptor.key]
            for descriptor in self._descriptors
            if descriptor.key in self._instances
        ]
