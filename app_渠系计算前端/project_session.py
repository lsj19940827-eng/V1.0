# -*- coding: utf-8 -*-
"""不依赖控件的工程会话、修订号及保存快照。"""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class ProjectSnapshot:
    """捕获后与界面隔离的数据；后台任务只访问这份副本。"""

    generation: int
    revision: int
    data: Dict[str, Any]


class ProjectSession:
    """工程切换与修改分开计数，避免旧任务完成后确认新工程已保存。"""

    def __init__(self):
        self.generation = 0
        self.revision = 0
        self.saved_revision = 0
        self.path = ""
        self._data: Dict[str, Any] = {}

    def changed(self) -> None:
        self.revision += 1

    def commit(self, data: Dict[str, Any], path: str = "") -> None:
        """仅在完整恢复成功后切换会话。"""
        self._data = deepcopy(data)
        self.path = path
        self.generation += 1
        self.revision = 0
        self.saved_revision = 0

    def capture(self, data: Dict[str, Any]) -> ProjectSnapshot:
        self._data = deepcopy(data)
        return ProjectSnapshot(self.generation, self.revision, deepcopy(data))

    def matches(self, snapshot: ProjectSnapshot) -> bool:
        return (snapshot.generation, snapshot.revision) == (self.generation, self.revision)

    def confirm_saved(self, snapshot: ProjectSnapshot) -> bool:
        """只有当前工程的当前修订才能清除未保存标记。"""
        if not self.matches(snapshot):
            return False
        self.saved_revision = snapshot.revision
        return True

    @property
    def data(self) -> Dict[str, Any]:
        return deepcopy(self._data)
