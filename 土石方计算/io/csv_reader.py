# -*- coding: utf-8 -*-
"""
CSV / TXT 地形数据读取器

支持格式：
- 地形点文件：点号,X,Y,Z 或 X,Y,Z（支持自定义分隔符和列映射）
- 桩号坐标表：桩号,X,Y（用于中心线导入）
- 纵断面底高程表：桩号,高程
"""

from __future__ import annotations
import csv
import re
from typing import Optional

from 土石方计算.models.terrain import TerrainPoint
from 土石方计算.models.alignment import Alignment


class CSVTerrainReader:
    """
    CSV / TXT 地形数据读取器

    Usage
    -----
    >>> reader = CSVTerrainReader()
    >>> pts = reader.read_terrain("survey.txt", delimiter=",",
    ...                           col_x=1, col_y=2, col_z=3)
    >>> alignment = reader.read_centerline("centerline.csv",
    ...                                    col_station=0, col_x=1, col_y=2)
    """

    DEFAULT_ENCODINGS = ["utf-8", "gbk", "gb2312", "utf-8-sig"]

    # ------------------------------------------------------------------
    # 地形点读取
    # ------------------------------------------------------------------

    def read_terrain(
        self,
        path: str,
        delimiter: str = ",",
        col_x: int = 0,
        col_y: int = 1,
        col_z: int = 2,
        col_id: Optional[int] = None,
        skip_rows: int = 0,
        comment_char: str = "#",
    ) -> list[TerrainPoint]:
        """
        读取测量坐标文件，返回地形点列表。

        Parameters
        ----------
        path : 文件路径
        delimiter : 分隔符（默认逗号，可为空格或制表符）
        col_x/y/z : 列索引（0-based）
        col_id : 点号列索引（可选，None 表示无）
        skip_rows : 跳过的标题行数
        comment_char : 注释行前缀字符

        Returns
        -------
        list[TerrainPoint]
        """
        rows = self._read_rows(path, delimiter, skip_rows, comment_char)
        result: list[TerrainPoint] = []
        for i, row in enumerate(rows):
            try:
                x = float(row[col_x])
                y = float(row[col_y])
                z = float(row[col_z])
                src = str(row[col_id]) if col_id is not None else f"csv_{i}"
                result.append(TerrainPoint(x=x, y=y, z=z, source=src))
            except (IndexError, ValueError):
                continue   # 跳过无效行
        return result

    # ------------------------------------------------------------------
    # 中心线读取
    # ------------------------------------------------------------------

    def read_centerline(
        self,
        path: str,
        delimiter: str = ",",
        col_station: int = 0,
        col_x: int = 1,
        col_y: int = 2,
        skip_rows: int = 1,
        comment_char: str = "#",
    ) -> Alignment:
        """
        读取桩号坐标表，构建中心线。

        Parameters
        ----------
        col_station : 桩号列（支持 "K0+100" 格式或纯数字）
        col_x/y : 坐标列

        Returns
        -------
        Alignment
        """
        rows = self._read_rows(path, delimiter, skip_rows, comment_char)
        records: list[tuple[float, float, float]] = []
        for row in rows:
            try:
                station = self._parse_station(row[col_station])
                x = float(row[col_x])
                y = float(row[col_y])
                records.append((station, x, y))
            except (IndexError, ValueError):
                continue
        if len(records) < 2:
            raise ValueError(f"中心线数据不足（有效行数 {len(records)}），至少需要 2 行")
        return Alignment.from_station_table(records)

    # ------------------------------------------------------------------
    # 纵断面底高程表读取
    # ------------------------------------------------------------------

    def read_design_elevations(
        self,
        path: str,
        delimiter: str = ",",
        col_station: int = 0,
        col_elevation: int = 1,
        skip_rows: int = 1,
        comment_char: str = "#",
    ) -> dict[float, float]:
        """
        读取纵断面设计底高程表。

        Returns
        -------
        {station: invert_elevation}
        """
        rows = self._read_rows(path, delimiter, skip_rows, comment_char)
        result: dict[float, float] = {}
        for row in rows:
            try:
                station = self._parse_station(row[col_station])
                elev = float(row[col_elevation])
                result[station] = elev
            except (IndexError, ValueError):
                continue
        return result

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _read_rows(
        self,
        path: str,
        delimiter: str,
        skip_rows: int,
        comment_char: str,
    ) -> list[list[str]]:
        """读取文件并返回有效行的字段列表"""
        content = self._read_file(path)
        lines = content.splitlines()
        rows: list[list[str]] = []
        for i, line in enumerate(lines):
            if i < skip_rows:
                continue
            line = line.strip()
            if not line or line.startswith(comment_char):
                continue
            # 支持空格/制表符分隔
            if delimiter in (" ", ""):
                fields = re.split(r"\s+", line)
            else:
                fields = line.split(delimiter)
            rows.append([f.strip() for f in fields])
        return rows

    def _read_file(self, path: str) -> str:
        """尝试多种编码读取文件"""
        for enc in self.DEFAULT_ENCODINGS:
            try:
                with open(path, "r", encoding=enc) as f:
                    return f.read()
            except (UnicodeDecodeError, LookupError):
                continue
        raise IOError(f"无法以支持的编码读取文件: {path}")

    @staticmethod
    def _parse_station(value: str) -> float:
        """
        解析桩号字符串为浮点数（m）。

        支持格式：
        - 纯数字：'1500.0' → 1500.0
        - K+格式：'K1+500' → 1500.0
        - K+格式：'K0+100.5' → 100.5
        - 带空格：'1 + 500' → 1500.0
        """
        v = value.strip().upper().replace(" ", "")
        # 纯数字
        try:
            return float(v)
        except ValueError:
            pass
        # K0+100 格式
        m = re.match(r"K?(\d+)\+(\d+(?:\.\d+)?)", v)
        if m:
            km = float(m.group(1))
            m_part = float(m.group(2))
            return km * 1000.0 + m_part
        raise ValueError(f"无法解析桩号: {value!r}")
