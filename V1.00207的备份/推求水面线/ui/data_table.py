# -*- coding: utf-8 -*-
"""
数据表格组件

提供渠道节点数据的录入和展示功能，支持Excel粘贴。
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import List, Optional, Callable, Dict, Any
import sys
import os
import subprocess

# tksheet：高性能表格组件（Excel-like）
try:
    from tksheet import Sheet
except Exception:
    Sheet = None

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType
from config.constants import INPUT_COLUMNS, STRUCTURE_TYPE_OPTIONS, ALL_COLUMNS, GEOMETRY_RESULT_COLUMNS
from utils.clipboard import ClipboardHandler
from core.geometry_calc import GeometryCalculator
from core.hydraulic_calc import HydraulicCalculator
from .latex_tooltip import SheetHeaderTooltip


class DataTablePanel(ttk.Frame):
    """
    数据表格面板
    
    使用 tksheet.Sheet 显示和编辑渠道节点数据。
    支持增删插行、Excel粘贴等功能。
    """
    
    def __init__(self, parent: tk.Widget, on_change: Optional[Callable] = None):
        """
        初始化数据表格面板
        
        Args:
            parent: 父容器
            on_change: 数据变化时的回调函数
        """
        super().__init__(parent)
        self._ensure_tksheet()
        
        self.on_change = on_change
        self.clipboard_handler = None  # 延迟初始化
        self.station_prefix = ""  # 桩号前缀，如"南支"
        
        self._all_col_defs = ALL_COLUMNS
        self._all_col_ids = [col["id"] for col in self._all_col_defs]
        self._col_id_to_index = {col_id: i for i, col_id in enumerate(self._all_col_ids)}
        self._frozen_col_ids = []
        self._frozen_col_count = 0
        
        self._selected_row = None
        self._selected_col = None
        self._row_selection_mode = False
        
        self._negative_cells = set()
        self._negative_highlighted = set()
        
        # 项目设置（用于几何计算）
        self._project_settings = None
        
        # 记录用户手动修改过转弯半径的行（这些行不会被全局转弯半径覆盖）
        self._custom_turn_radius_items = set()
        
        # 缓存计算后的节点列表（用于双击查看详情）
        self._calculated_nodes: List[ChannelNode] = []
        
        # 可编辑列的ID列表（从流量段到转弯半径）
        self._editable_col_ids = ["flow_section", "name", "structure_type", "in_out", "ip_number", "x", "y", "turn_radius"]
        
        # 几何结果列ID列表（只读）
        self._geometry_result_col_ids = [col["id"] for col in GEOMETRY_RESULT_COLUMNS]
        
        self._syncing_selection = False
        self._syncing_scroll = False
        
        # 创建界面
        self._create_widgets()
        self._bind_events()

    def _ensure_tksheet(self) -> None:
        global Sheet
        if Sheet is not None:
            return
        
        install = messagebox.askyesno(
            "缺少依赖",
            "未安装 tksheet。\n是否自动安装？\n\n将执行: python -m pip install tksheet",
        )
        if not install:
            raise ImportError("tksheet is required for DataTablePanel")
        
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "tksheet"])
            from tksheet import Sheet as _Sheet
            Sheet = _Sheet
        except Exception as e:
            messagebox.showerror("安装失败", f"自动安装 tksheet 失败：{e}\n\n请手动执行: pip install tksheet")
            raise
    
    def _create_widgets(self):
        """创建界面组件"""
        # 工具栏
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(toolbar, text="添加行", command=self.add_row).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="插入行", command=self.insert_row).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="删除行", command=self.delete_row).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=5, fill=tk.Y)
        ttk.Button(toolbar, text="清空表格", command=self.clear_all).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=5, fill=tk.Y)
        
        # 提示标签
        ttk.Label(toolbar, text="提示: Ctrl+A全选，Ctrl+C/V/X复制粘贴剪切，Delete清空内容", 
                  foreground="gray").pack(side=tk.RIGHT, padx=5)
        
        # 表格容器（带滚动条）
        table_frame = ttk.Frame(self)
        table_frame.pack(fill=tk.BOTH, expand=True)

        self.sheet = Sheet(
            table_frame,
            headers=[col["text"] for col in self._all_col_defs],
            show_header=True,
            show_row_index=True,
            show_x_scrollbar=True,
            show_y_scrollbar=True,
            to_clipboard_delimiter="\t",
            from_clipboard_delimiters=["\t"],
        )
        self.sheet.pack(fill=tk.BOTH, expand=True)
        try:
            self.sheet.change_theme("light blue")
        except Exception:
            pass
        try:
            self.sheet.set_options(
                table_selected_cells_border_fg="#21A366",
                table_selected_rows_border_fg="#21A366",
                table_selected_columns_border_fg="#21A366",
                table_editor_bg="#FFFFFF",
                table_editor_fg="#000000",
            )
        except Exception:
            pass
        
        self._apply_initial_column_widths()
        self._apply_column_editability()
        self._set_sheet_data([], redraw=True)
        self._apply_row_index_options()
        
        # 初始化表头提示框
        self.header_tooltip = SheetHeaderTooltip(self.sheet, self._all_col_defs)

    def _is_descendant(self, widget: Optional[tk.Widget], ancestor: tk.Widget) -> bool:
        if widget is None:
            return False
        try:
            current = widget
            while current is not None:
                if current == ancestor:
                    return True
                parent_name = current.winfo_parent()
                if not parent_name:
                    break
                current = self.nametowidget(parent_name)
        except Exception:
            return False
        return False
    
    def _get_active_cell(self) -> Optional[tuple]:
        for getter in (
            lambda: self.sheet.get_currently_selected(),
            lambda: self.sheet.get_selected_cells(),
        ):
            try:
                sel = getter()
            except Exception:
                continue
            if isinstance(sel, tuple) and len(sel) >= 2 and all(isinstance(x, int) for x in sel[:2]):
                return sel[0], sel[1]
            if isinstance(sel, (list, set, tuple)):
                for item in sel:
                    if isinstance(item, tuple) and len(item) >= 2 and all(isinstance(x, int) for x in item[:2]):
                        return item[0], item[1]
        return None
    
    def _get_selected_rows(self) -> List[int]:
        rows = set()
        for getter in (
            lambda: self.sheet.get_selected_rows(),
            lambda: self.sheet.get_selected_row_indices(),
        ):
            try:
                got = getter()
            except Exception:
                continue
            if isinstance(got, (list, tuple, set)):
                rows.update(int(r) for r in got if isinstance(r, int))
        return sorted(rows)
    
    def _get_selected_columns(self) -> List[int]:
        cols = set()
        for getter in (
            lambda: self.sheet.get_selected_columns(),
            lambda: self.sheet.get_selected_column_indices(),
        ):
            try:
                got = getter()
            except Exception:
                continue
            if isinstance(got, (list, tuple, set)):
                cols.update(int(c) for c in got if isinstance(c, int))
        return sorted(cols)
    
    def _get_selected_cells(self) -> List[tuple]:
        out = set()
        try:
            cells = list(self.sheet.get_selected_cells())
        except Exception:
            cells = []
        for item in cells:
            if isinstance(item, (tuple, list)) and len(item) >= 2 and all(isinstance(x, int) for x in item[:2]):
                out.add((item[0], item[1]))
        return sorted(out)

    def _global_to_local(self, col: int) -> tuple[str, int]:
        frozen_n = getattr(self, "_frozen_col_count", 0) or 0
        if col < frozen_n:
            return "left", col
        return "right", col - frozen_n
    
    def _local_to_global(self, side: str, col: int) -> int:
        frozen_n = getattr(self, "_frozen_col_count", 0) or 0
        return col if side == "left" else col + frozen_n
    
    def _schedule_sync_yviews(self) -> None:
        return
    
    def _sync_yviews(self) -> None:
        return
    
    def _forward_mousewheel_to_right(self, event):
        return None
    
    def _maybe_bridge_right_from_left(self, event):
        return None
    
    def _maybe_bridge_left_from_right(self, event):
        return None
    
    def _schedule_sync_selection(self, side: str) -> None:
        return
    
    def _sync_selection_from(self, side: str) -> None:
        return
    
    def _on_end_edit_cell(self, event, *, side: str = "right"):
        rc = None
        if isinstance(event, dict):
            r = event.get("row")
            c = event.get("column")
            if isinstance(r, int) and isinstance(c, int):
                rc = (r, c)
        elif isinstance(event, (tuple, list)):
            if len(event) >= 2 and isinstance(event[0], int) and isinstance(event[1], int):
                rc = (event[0], event[1])
            elif len(event) >= 2 and isinstance(event[1], (tuple, list)) and len(event[1]) >= 2:
                r, c = event[1][0], event[1][1]
                if isinstance(r, int) and isinstance(c, int):
                    rc = (r, c)
        
        if rc:
            frozen_n = getattr(self, "_frozen_col_count", 0) or 0
            offset = 0 if side == "left" else frozen_n
            self._selected_row, self._selected_col = rc[0], rc[1] + offset
            self._row_selection_mode = False
            self._handle_cells_changed([(rc[0], rc[1] + offset)])
    
    def _on_end_paste(self, event, *, side: str = "right"):
        cells = []
        if isinstance(event, (tuple, list)) and len(event) >= 2:
            maybe_rc = event[1]
            if isinstance(maybe_rc, (tuple, list)) and len(maybe_rc) >= 2 and all(isinstance(x, int) for x in maybe_rc[:2]):
                start_r, start_c = maybe_rc[0], maybe_rc[1]
                frozen_n = getattr(self, "_frozen_col_count", 0) or 0
                offset = 0 if side == "left" else frozen_n
                pasted = event[2] if len(event) >= 3 else None
                if isinstance(pasted, (list, tuple)):
                    for r_off, row in enumerate(pasted):
                        if not isinstance(row, (list, tuple)):
                            continue
                        for c_off, _ in enumerate(row):
                            cells.append((start_r + r_off, start_c + c_off + offset))
        if not cells:
            active = self._get_active_cell()
            if active:
                cells = [active]
        self._handle_cells_changed(cells)
    
    def _on_edit_validation(self, event, *, side: str = "right"):
        try:
            changes = []
            frozen_n = getattr(self, "_frozen_col_count", 0) or 0
            offset = 0 if side == "left" else frozen_n
            if isinstance(event, dict):
                event_name = event.get("eventname", "")
                if event_name in ("end_edit_table", "end_edit_header", "end_edit_index"):
                    cells_dict = event.get("cells", {})
                    table_cells = cells_dict.get("table", {})
                    if table_cells:
                        for (r, c), val in table_cells.items():
                            if isinstance(r, int) and isinstance(c, int):
                                changes.append((r, c + offset))
                    if changes:
                        self.after_idle(lambda: self._handle_cells_changed(changes))
                    return None
                
                loc = event.get("loc")
                if isinstance(loc, (tuple, list)) and len(loc) >= 2 and all(isinstance(x, int) for x in loc[:2]):
                    changes.append((loc[0], loc[1] + offset))
                for key in ("cells", "edited_cells"):
                    maybe = event.get(key)
                    if isinstance(maybe, (list, tuple, set)):
                        for rc in maybe:
                            if isinstance(rc, (tuple, list)) and len(rc) >= 2 and all(isinstance(x, int) for x in rc[:2]):
                                changes.append((rc[0], rc[1] + offset))
            if changes:
                self.after_idle(lambda: self._handle_cells_changed(changes))
        except Exception:
            pass
        return event
    
    def _handle_cells_changed(self, cells: List[tuple]) -> None:
        if not cells:
            return
        
        rows_changed = {r for r, _ in cells if isinstance(r, int) and r >= 0}
        cols_changed = {c for _, c in cells if isinstance(c, int) and c >= 0}
        
        turn_radius_idx = self._col_id_to_index.get("turn_radius", -1)
        if turn_radius_idx in cols_changed and rows_changed:
            self._custom_turn_radius_items.update(rows_changed)
        
        for c in cols_changed:
            if c >= len(self._all_col_ids):
                continue
            col_id = self._all_col_ids[c]
            if col_id in ("x", "y", "turn_radius"):
                min_row = min(rows_changed) if rows_changed else 0
                self.recalculate(min_row)
                break

        bend_related_col_ids = {
            "arc_length",
            "turn_radius",
            "roughness",
            "water_depth_design",
            "hydraulic_radius",
            "velocity_design",
            "bottom_width",
            "side_slope",
            "diameter",
        }
        changed_col_ids = {self._all_col_ids[c] for c in cols_changed if 0 <= c < len(self._all_col_ids)}
        # 移除自动计算弯道水头损失，改为仅在"执行计算"时统一计算
        
        # 当结构形式列发生变化时，为分水闸/分水口自动填充过闸水头损失
        structure_col_idx = self._col_id_to_index.get("structure_type", -1)
        gate_loss_col_idx = self._col_id_to_index.get("head_loss_gate", -1)
        if structure_col_idx in cols_changed and gate_loss_col_idx >= 0:
            self._auto_fill_gate_head_loss(rows_changed)
        
        if self.on_change:
            self.on_change()
    
    def _apply_initial_column_widths(self) -> None:
        widths = [int(col.get("width", 100) or 100) for col in self._all_col_defs]
        for idx, width in enumerate(widths):
            applied = False
            for call in (
                lambda: self.sheet.column_width(idx, width=width, redraw=False),
                lambda: self.sheet.column_width(column=idx, width=width, redraw=False),
                lambda: self.sheet.set_column_width(idx, width),
                lambda: self.sheet.set_column_width(column=idx, width=width),
            ):
                if applied:
                    break
                try:
                    call()
                    applied = True
                except Exception:
                    pass
        try:
            self.sheet.set_options(expand_sheet_if_paste_too_big=True)
        except Exception:
            pass

    def _apply_column_editability(self) -> None:
        editable = set(self._editable_col_ids or [])
        readonly_cols = [i for i, col_id in enumerate(self._all_col_ids) if col_id not in editable]
        if not readonly_cols:
            return
        for idx in readonly_cols:
            applied = False
            for call in (
                lambda: self.sheet.readonly_columns(columns=[idx], readonly=True),
                lambda: self.sheet.readonly_columns([idx], readonly=True),
                lambda: self.sheet.readonly_column(idx, readonly=True),
            ):
                if applied:
                    break
                try:
                    call()
                    applied = True
                except Exception:
                    pass

    def _get_sheet_data(self) -> List[List[Any]]:
        try:
            data = self.sheet.get_sheet_data(return_copy=True)
        except TypeError:
            try:
                data = self.sheet.get_sheet_data()
            except Exception:
                data = []
        except Exception:
            data = []
        data = list(data or [])
        total_cols = len(self._all_col_ids)
        normalized: List[List[Any]] = []
        for row in data:
            row_list = list(row) if isinstance(row, (list, tuple)) else [row]
            if len(row_list) < total_cols:
                row_list.extend([""] * (total_cols - len(row_list)))
            elif len(row_list) > total_cols:
                row_list = row_list[:total_cols]
            normalized.append(row_list)
        return normalized
    
    def _set_sheet_data(self, data: List[List[Any]], *, redraw: bool = True) -> None:
        normalized = []
        for row in data or []:
            row_list = list(row) if isinstance(row, (list, tuple)) else [row]
            if len(row_list) < len(self._all_col_ids):
                row_list.extend([""] * (len(self._all_col_ids) - len(row_list)))
            elif len(row_list) > len(self._all_col_ids):
                row_list = row_list[: len(self._all_col_ids)]
            normalized.append(row_list)
        try:
            self.sheet.set_sheet_data(normalized, reset_col_positions=False, reset_row_positions=False, redraw=redraw)
        except TypeError:
            self.sheet.set_sheet_data(normalized)
            if redraw:
                try:
                    self.sheet.refresh()
                except Exception:
                    pass

    def _set_sheet_data_reset(self, data: List[List[Any]], *, redraw: bool = True) -> None:
        normalized = []
        for row in data or []:
            row_list = list(row) if isinstance(row, (list, tuple)) else [row]
            if len(row_list) < len(self._all_col_ids):
                row_list.extend([""] * (len(self._all_col_ids) - len(row_list)))
            elif len(row_list) > len(self._all_col_ids):
                row_list = row_list[: len(self._all_col_ids)]
            normalized.append(row_list)
        try:
            self.sheet.set_sheet_data(
                normalized,
                reset_col_positions=False,
                reset_row_positions=True,
                redraw=redraw,
                reset_highlights=True,
                keep_formatting=False,
            )
        except TypeError:
            self.sheet.set_sheet_data(normalized)
            if redraw:
                try:
                    self.sheet.refresh()
                except Exception:
                    pass
    
    def _bind_events(self):
        """绑定事件"""
        bindings = (
            "single_select",
            "row_select",
            "column_select",
            "drag_select",
            "arrowkeys",
            "edit_cell",
            "copy",
            "cut",
            "paste",
            "delete",
            "undo",
            "right_click_popup_menu",
            "column_width_resize",
            "row_height_resize",
        )

        sh = self.sheet
        try:
            sh.enable_bindings(bindings)
        except Exception:
            try:
                sh.enable_bindings("all")
            except Exception:
                pass

        try:
            sh.extra_bindings("end_edit_cell", func=self._on_end_edit_cell)
        except Exception:
            pass
        try:
            sh.extra_bindings("end_paste", func=self._on_end_paste)
        except Exception:
            pass
        try:
            sh.edit_validation(self._on_edit_validation)
        except Exception:
            pass

        sh.bind("<Control-v>", lambda e: (self.paste_from_clipboard(), "break"))
        sh.bind("<Control-c>", lambda e: (self.copy_selected_cell_or_row(), "break"))
        sh.bind("<Control-x>", lambda e: (self.cut_selected_cell_or_row(), "break"))
        sh.bind("<Control-z>", lambda e: (self.undo(), "break"))
        sh.bind("<Control-y>", lambda e: (self.redo(), "break"))
        sh.bind("<Control-a>", lambda e: (self.select_all_cells(), "break"))
        sh.bind("<Delete>", lambda e: (self.clear_selected_contents(), "break"))
        sh.bind("<BackSpace>", lambda e: (self.clear_selected_contents(), "break"))
        sh.bind("<Control-Delete>", lambda e: (self.delete_row(), "break"))
        sh.bind("<Control-Shift-Delete>", lambda e: (self.delete_row(), "break"))
        sh.bind("<Control-d>", lambda e: (self.fill_down(), "break"))
        sh.bind("<Control-Shift-c>", lambda e: (self.copy_visible_region(include_headers=True), "break"))

        try:
            sh.popup_menu_add_command("全选", lambda: self.select_all_cells(), table_menu=True, header_menu=False, index_menu=False)
            sh.popup_menu_add_command("复制可见区域", lambda: self.copy_visible_region(include_headers=True), table_menu=True, header_menu=False, index_menu=False)
            sh.popup_menu_add_command("添加行", lambda: self.add_row(), table_menu=True, header_menu=False, index_menu=False)
            sh.popup_menu_add_command("插入行", lambda: self.insert_row(), table_menu=True, header_menu=False, index_menu=False)
            sh.popup_menu_add_command("删除行", lambda: self.delete_row(), table_menu=True, header_menu=False, index_menu=False)
            sh.popup_menu_add_command("清空内容", lambda: self.clear_selected_contents(), table_menu=True, header_menu=False, index_menu=False)
            sh.popup_menu_add_command("剪切", lambda: self.cut_selected_cell_or_row(), table_menu=True, header_menu=False, index_menu=False)
            sh.popup_menu_add_command("复制", lambda: self.copy_selected_cell_or_row(), table_menu=True, header_menu=False, index_menu=False)
            sh.popup_menu_add_command("粘贴", lambda: self.paste_from_clipboard(), table_menu=True, header_menu=False, index_menu=False)
            sh.popup_menu_add_command("撤销", lambda: self.undo(), table_menu=True, header_menu=False, index_menu=False)
            sh.popup_menu_add_command("重做", lambda: self.redo(), table_menu=True, header_menu=False, index_menu=False)
        except Exception:
            pass

        try:
            # 双击事件绑定（用于显示渐变段详细计算过程）
            sh.MT.bind("<Double-Button-1>", self._on_cell_double_click, add="+")
        except Exception:
            pass
    
    def undo(self):
        """
        撤销上一次编辑操作
        
        恢复单元格到修改前的值。
        """
        try:
            self.sheet.undo()
        except Exception:
            return
        
        self._auto_determine_in_out()
        self._update_ip_numbers()
        self.recalculate(0)
        
        if self.on_change:
            self.on_change()
    
    def _update_negative_highlights(self, nodes: List[ChannelNode] = None):
        check_cols = [
            self._col_id_to_index.get("check_pre_curve", -1),
            self._col_id_to_index.get("check_post_curve", -1),
            self._col_id_to_index.get("check_total_length", -1),
        ]
        check_cols = [c for c in check_cols if c >= 0]
        if not check_cols:
            return
        
        for r, c in list(self._negative_highlighted):
            try:
                self.sheet.dehighlight_cells(row=r, column=c, redraw=False)
            except Exception:
                try:
                    self.sheet.dehighlight_cells(r=r, c=c, redraw=False)
                except Exception:
                    pass
        self._negative_highlighted.clear()
        self._negative_cells.clear()
        
        sheet_data = self._get_sheet_data()
        for r, row in enumerate(sheet_data):
            for c in check_cols:
                val = 0.0
                if nodes and r < len(nodes):
                    node = nodes[r]
                    if c == self._col_id_to_index.get("check_pre_curve", -1):
                        val = node.check_pre_curve
                    elif c == self._col_id_to_index.get("check_post_curve", -1):
                        val = node.check_post_curve
                    elif c == self._col_id_to_index.get("check_total_length", -1):
                        val = node.check_total_length
                else:
                    try:
                        val = float(row[c]) if row[c] != "" else 0.0
                    except Exception:
                        val = 0.0
                
                if val < 0:
                    self._negative_cells.add((r, c))
        
        for r, c in self._negative_cells:
            try:
                self.sheet.highlight_cells(row=r, column=c, bg="#FFCCCC", fg="#CC0000", redraw=False)
            except Exception:
                try:
                    self.sheet.highlight_cells(r=r, c=c, bg="#FFCCCC", fg="#CC0000", redraw=False)
                except Exception:
                    pass
            self._negative_highlighted.add((r, c))
        try:
            self.sheet.redraw()
        except Exception:
            try:
                self.sheet.refresh()
            except Exception:
                pass
    
    def set_project_settings(self, settings: ProjectSettings) -> None:
        """
        设置项目参数（用于几何计算）
        
        Args:
            settings: 项目设置对象
        """
        self._project_settings = settings
    
    def update_global_turn_radius(self, turn_radius: float) -> None:
        """
        更新全局转弯半径并刷新表格显示
        
        全局转弯半径作用于所有行，除非该行被用户手动修改过（记录在 _custom_turn_radius_items 中）
        
        Args:
            turn_radius: 新的转弯半径值
        """
        if self._project_settings:
            self._project_settings.turn_radius = turn_radius
        
        sheet_data = self._get_sheet_data()
        if not sheet_data:
            return
        
        col_idx = self._col_id_to_index.get("turn_radius", -1)
        if col_idx < 0:
            return
        
        for r in range(len(sheet_data)):
            if r in self._custom_turn_radius_items:
                continue
            sheet_data[r][col_idx] = str(turn_radius) if turn_radius > 0 else ""
        
        self._set_sheet_data(sheet_data, redraw=True)
        
        # 重新计算几何数据（转弯半径影响切线长和弧长）
        self.recalculate(0)
    
    def recalculate(self, changed_row_index: int = 0) -> None:
        """
        重新计算几何数据（联动计算引擎）
        
        当 X 或 Y 坐标发生变化时，自动重新计算该行及后续行的：
        - 转角
        - 切线长
        - 弧长
        - IP直线间距
        - IP点桩号、BC桩号、MC桩号、EC桩号
        
        Args:
            changed_row_index: 发生变化的行索引（从0开始）
        """
        sheet_data = self._get_sheet_data()
        if len(sheet_data) < 2:
            return
        
        # 创建临时的项目设置（如果未设置）
        if self._project_settings is None:
            self._project_settings = ProjectSettings()
        
        # 创建几何计算器
        geo_calc = GeometryCalculator(self._project_settings)
        
        # 从表格读取所有节点数据
        nodes = self._read_nodes_for_calc()
        if len(nodes) < 2:
            return
        
        # 计算需要更新的起始行（至少从变化行的前一行开始，因为转角依赖前后节点）
        start_idx = max(0, changed_row_index - 1)
        
        # 重新计算直线距离（从变化行开始）
        for i in range(max(1, changed_row_index), len(nodes)):
            prev_node = nodes[i - 1]
            curr_node = nodes[i]
            distance = geo_calc.calculate_distance(prev_node.x, prev_node.y, curr_node.x, curr_node.y)
            curr_node.straight_distance = distance
        
        # 重新计算转角和曲线要素（从变化行开始，到末尾前一行）
        for i in range(max(1, start_idx), len(nodes) - 1):
            node = nodes[i]
            prev_node = nodes[i - 1]
            next_node = nodes[i + 1]
            
            # 检查是否为进出口节点（跳过计算）
            if node.in_out.value in ("进", "出"):
                node.turn_angle = 0.0
                node.tangent_length = 0.0
                node.arc_length = 0.0
                continue
            
            # 使用余弦定理计算转角
            turn_angle = geo_calc.calculate_turn_angle_by_cosine(
                prev_node.x, prev_node.y,
                node.x, node.y,
                next_node.x, next_node.y
            )
            node.turn_angle = turn_angle
            
            # 获取转弯半径
            turn_radius = node.turn_radius if node.turn_radius > 0 else self._project_settings.turn_radius
            if turn_radius <= 0:
                turn_radius = 100.0  # 默认值
            
            # 计算切线长和弧长
            node.tangent_length = geo_calc.calculate_tangent_length(turn_angle, turn_radius)
            node.arc_length = geo_calc.calculate_arc_length(turn_angle, turn_radius)
        
        # 重新计算桩号（从变化行开始）
        start_station = self._project_settings.start_station if self._project_settings else 0.0
        
        # 设置起点桩号
        if changed_row_index == 0:
            nodes[0].station_ip = start_station
            nodes[0].station_MC = start_station
            nodes[0].station_BC = start_station
            nodes[0].station_EC = start_station
        
        # 计算后续节点的桩号
        for i in range(max(1, changed_row_index), len(nodes)):
            prev_node = nodes[i - 1]
            curr_node = nodes[i]
            
            # IP点桩号（累计直线距离）
            curr_node.station_ip = prev_node.station_ip + curr_node.straight_distance
            
            # 里程MC递推
            prev_T = prev_node.tangent_length
            curr_T = curr_node.tangent_length
            prev_L = prev_node.arc_length
            curr_L = curr_node.arc_length
            
            station_MC = (prev_node.station_MC + 
                          curr_node.straight_distance - 
                          prev_T - curr_T + 
                          prev_L / 2 + curr_L / 2)
            curr_node.station_MC = station_MC
            
            # 弯前BC和弯末EC
            curr_node.station_BC = curr_node.station_MC - curr_L / 2
            curr_node.station_EC = curr_node.station_BC + curr_L
            
            # 弯道长度 = EC - BC
            curr_node.curve_length = curr_node.station_EC - curr_node.station_BC
        
        # 计算复核长度（用于检查设计合理性，不能出现负数）
        for i in range(len(nodes)):
            curr_node = nodes[i]
            prev_tangent = nodes[i - 1].tangent_length if i > 0 else 0.0
            next_straight = nodes[i + 1].straight_distance if i < len(nodes) - 1 else 0.0
            
            # 复核弯前长度 = L72 - J72 (当前IP直线间距 - 当前切线长)
            curr_node.check_pre_curve = curr_node.straight_distance - curr_node.tangent_length
            
            # 复核弯后长度 = L73 - J72 (下一段IP直线间距 - 当前切线长)
            curr_node.check_post_curve = next_straight - curr_node.tangent_length
            
            # 复核总长度 = L72 - J71 - J72 (当前IP直线间距 - 上一切线长 - 当前切线长)
            curr_node.check_total_length = curr_node.straight_distance - prev_tangent - curr_node.tangent_length
            
        # 更新表格显示
        self._update_geometry_results(nodes, start_idx)
        # 移除自动计算弯道水头损失，改为仅在"执行计算"时统一计算
        
        # 自动进出口判别和结构形式填充
        self._auto_determine_in_out()
        
        # 更新IP编号（根据进出口状态）
        self._update_ip_numbers()

    def _update_bend_loss_from_sheet(self, rows: Optional[List[int]] = None) -> None:
        sheet_data = self._get_sheet_data()
        if not sheet_data:
            return
        
        col_head = self._col_id_to_index.get("head_loss_bend", -1)
        if col_head < 0:
            return
        
        col_arc = self._col_id_to_index.get("arc_length", -1)
        col_turn_radius = self._col_id_to_index.get("turn_radius", -1)
        col_roughness = self._col_id_to_index.get("roughness", -1)
        col_h = self._col_id_to_index.get("water_depth_design", -1)
        col_r = self._col_id_to_index.get("hydraulic_radius", -1)
        col_v = self._col_id_to_index.get("velocity_design", -1)
        col_b = self._col_id_to_index.get("bottom_width", -1)
        col_m = self._col_id_to_index.get("side_slope", -1)
        col_d = self._col_id_to_index.get("diameter", -1)
        
        if col_arc < 0 or col_r < 0 or col_v < 0:
            return
        
        if self._project_settings is None:
            self._project_settings = ProjectSettings()
        
        hyd_calc = HydraulicCalculator(self._project_settings)
        
        def as_float(val: Any, default: float = 0.0) -> float:
            if val is None:
                return default
            try:
                s = str(val).strip()
                if not s or s in ("-", "N/A", "nan", "None"):
                    return default
                return float(s)
            except Exception:
                return default
        
        target_rows = rows if rows is not None else list(range(len(sheet_data)))
        for r_idx in target_rows:
            if not (0 <= r_idx < len(sheet_data)):
                continue
            row = sheet_data[r_idx]
            L = as_float(row[col_arc] if col_arc < len(row) else 0.0, 0.0)
            v = as_float(row[col_v] if col_v < len(row) else 0.0, 0.0)
            R = as_float(row[col_r] if col_r < len(row) else 0.0, 0.0)
            
            Rc = 0.0
            if col_turn_radius >= 0 and col_turn_radius < len(row):
                Rc = as_float(row[col_turn_radius], 0.0)
            if Rc <= 0:
                Rc = self._project_settings.turn_radius
            
            n = 0.0
            if col_roughness >= 0 and col_roughness < len(row):
                n = as_float(row[col_roughness], 0.0)
            if n <= 0:
                n = self._project_settings.roughness
            
            h = as_float(row[col_h] if col_h >= 0 and col_h < len(row) else 0.0, 0.0)
            B = as_float(row[col_b] if col_b >= 0 and col_b < len(row) else 0.0, 0.0)
            m = as_float(row[col_m] if col_m >= 0 and col_m < len(row) else 0.0, 0.0)
            D = as_float(row[col_d] if col_d >= 0 and col_d < len(row) else 0.0, 0.0)
            
            if L > 0 and v > 0 and R > 0 and Rc > 0:
                node = ChannelNode()
                node.arc_length = L
                node.velocity = v
                node.water_depth = h
                node.turn_radius = Rc
                node.roughness = n
                node.section_params = {"R": R}
                if B > 0:
                    node.section_params["B"] = B
                if m > 0:
                    node.section_params["m"] = m
                if D > 0:
                    node.section_params["D"] = D
                hw = hyd_calc.calculate_bend_loss(node)
                sheet_data[r_idx][col_head] = f"{hw:.3f}"
            else:
                sheet_data[r_idx][col_head] = ""
        
        self._set_sheet_data(sheet_data, redraw=True)
    
    def _read_nodes_for_calc(self) -> List[ChannelNode]:
        """
        从表格读取节点数据用于计算
        
        Returns:
            ChannelNode列表
        """
        nodes = []
        sheet_data = self._get_sheet_data()
        
        for values in sheet_data:
            node = ChannelNode()
            
            # 读取基础输入
            for i, col_def in enumerate(ALL_COLUMNS):
                col_id = col_def["id"]
                value = values[i] if i < len(values) else ""
                
                if col_id == "x":
                    try:
                        node.x = float(value) if value else 0.0
                    except ValueError:
                        node.x = 0.0
                elif col_id == "y":
                    try:
                        node.y = float(value) if value else 0.0
                    except ValueError:
                        node.y = 0.0
                elif col_id == "turn_radius":
                    try:
                        node.turn_radius = float(value) if value else 0.0
                    except ValueError:
                        node.turn_radius = 0.0
                elif col_id == "in_out":
                    node.in_out = InOutType.from_string(str(value)) if value else InOutType.NORMAL
                elif col_id == "turn_angle":
                    try:
                        node.turn_angle = float(value) if value else 0.0
                    except ValueError:
                        node.turn_angle = 0.0
                elif col_id == "tangent_length":
                    try:
                        node.tangent_length = float(value) if value else 0.0
                    except ValueError:
                        node.tangent_length = 0.0
                elif col_id == "arc_length":
                    try:
                        node.arc_length = float(value) if value else 0.0
                    except ValueError:
                        node.arc_length = 0.0
                elif col_id == "straight_distance":
                    try:
                        node.straight_distance = float(value) if value else 0.0
                    except ValueError:
                        node.straight_distance = 0.0
                elif col_id == "station_ip":
                    node.station_ip = self._parse_station(str(value))
                elif col_id == "station_MC":
                    node.station_MC = self._parse_station(str(value))
            
            nodes.append(node)
        
        return nodes
    
    def _update_geometry_results(self, nodes: List[ChannelNode], start_idx: int = 0) -> None:
        """
        更新几何计算结果到表格
        
        Args:
            nodes: 计算完成的节点列表
            start_idx: 开始更新的行索引
        """
        sheet_data = self._get_sheet_data()
        total_rows = min(len(nodes), len(sheet_data))
        
        def setv(row_idx: int, col_id: str, value: Any):
            c = self._col_id_to_index.get(col_id, -1)
            if c < 0 or row_idx >= len(sheet_data):
                return
            sheet_data[row_idx][c] = value
        
        for i in range(start_idx, total_rows):
            node = nodes[i]
            setv(i, "turn_angle", f"{node.turn_angle:.3f}")
            setv(i, "tangent_length", f"{node.tangent_length:.3f}")
            setv(i, "arc_length", f"{node.arc_length:.3f}")
            setv(i, "curve_length", f"{node.curve_length:.3f}")
            setv(i, "straight_distance", f"{node.straight_distance:.3f}")
            
            setv(i, "station_ip", self._format_station(node.station_ip))
            setv(i, "station_BC", self._format_station(node.station_BC))
            setv(i, "station_MC", self._format_station(node.station_MC))
            setv(i, "station_EC", self._format_station(node.station_EC))
            
            setv(i, "check_pre_curve", f"{node.check_pre_curve:.3f}")
            setv(i, "check_post_curve", f"{node.check_post_curve:.3f}")
            setv(i, "check_total_length", f"{node.check_total_length:.3f}")
            
            # 更新弯道水头损失
            setv(i, "head_loss_bend", f"{node.head_loss_bend:.3f}" if node.head_loss_bend else "")
        
        self._set_sheet_data(sheet_data, redraw=True)
        
        # 更新负值单元格高亮
        self._update_negative_highlights(nodes)
    
    def _auto_determine_in_out(self) -> None:
        """
        自动判别进出口并设置结构形式
        
        业务规则：
        1. 建筑物名称第1次出现：设置为"进"
        2. 建筑物名称最后1次出现：设置为"出"
        3. 中间出现的行：不设置进出口标识
        4. 明渠和矩形暗涵：不需要判别进出口，显示"-"
        5. 建筑物名称第1次和最后1次出现之间的行：结构形式设置为该建筑物的结构形式
        """
        sheet_data = self._get_sheet_data()
        if not sheet_data:
            return
        
        name_col_idx = self._col_id_to_index.get("name", -1)
        structure_col_idx = self._col_id_to_index.get("structure_type", -1)
        in_out_col_idx = self._col_id_to_index.get("in_out", -1)
        
        if name_col_idx < 0 or in_out_col_idx < 0:
            return
        
        building_occurrences = {}
        for row_idx, row in enumerate(sheet_data):
            name = str(row[name_col_idx]).strip() if name_col_idx < len(row) else ""
            structure_type = str(row[structure_col_idx]).strip() if 0 <= structure_col_idx < len(row) else ""
            if not name:
                continue
            # 渐变段行不计入建筑物出现位置（通过结构形式判断）
            if structure_type == "渐变段":
                continue
            building_occurrences.setdefault(name, []).append((row_idx, structure_type))
        
        for row_idx, row in enumerate(sheet_data):
            name = str(row[name_col_idx]).strip() if name_col_idx < len(row) else ""
            structure_type = str(row[structure_col_idx]).strip() if 0 <= structure_col_idx < len(row) else ""
            
            # 渐变段行不参与进出口判别，进出口列留空（通过结构形式判断）
            if structure_type == "渐变段":
                row[in_out_col_idx] = ""
                continue
            
            if not name:
                row[in_out_col_idx] = "-" if self._is_open_channel_or_rect(structure_type) else ""
                continue
            
            if self._is_open_channel_or_rect(structure_type):
                row[in_out_col_idx] = "-"
                continue
            
            occurrences = building_occurrences.get(name, [])
            if not occurrences:
                row[in_out_col_idx] = ""
                continue
            
            if occurrences[0][0] == row_idx:
                row[in_out_col_idx] = InOutType.INLET.value
            elif occurrences[-1][0] == row_idx:
                row[in_out_col_idx] = InOutType.OUTLET.value
            else:
                row[in_out_col_idx] = ""
        
        self._auto_fill_structure_type(sheet_data, building_occurrences)
        self._set_sheet_data(sheet_data, redraw=True)
    
    def _is_open_channel_or_rect(self, structure_type: str) -> bool:
        """
        判断结构形式是否为明渠、矩形暗涵或分水闸/分水口（不需要进出口判别）
        
        Args:
            structure_type: 结构形式字符串
            
        Returns:
            是否为不需要进出口判别的类型
        """
        if not structure_type:
            return False
        # 明渠类型、矩形类型和分水闸/分水口类型不需要进出口判别
        return ("明渠" in structure_type or 
                structure_type == "矩形" or 
                structure_type == "矩形暗涵" or
                "分水" in structure_type)
    
    def _auto_fill_gate_head_loss(self, rows: set) -> None:
        """
        当结构形式为分水闸/分水口时，自动填充过闸水头损失为默认值0.2m
        
        仅在该行的过闸水头损失列为空时才自动填充，不覆盖用户已有输入。
        
        Args:
            rows: 变更的行索引集合
        """
        from config.constants import DEFAULT_GATE_HEAD_LOSS
        
        structure_col_idx = self._col_id_to_index.get("structure_type", -1)
        gate_loss_col_idx = self._col_id_to_index.get("head_loss_gate", -1)
        
        if structure_col_idx < 0 or gate_loss_col_idx < 0:
            return
        
        sheet_data = self._get_sheet_data()
        changed = False
        
        for row_idx in rows:
            if row_idx < 0 or row_idx >= len(sheet_data):
                continue
            row = sheet_data[row_idx]
            structure_type = str(row[structure_col_idx]).strip() if structure_col_idx < len(row) else ""
            
            if "分水" in structure_type:
                # 仅在过闸损失列为空时自动填充
                current_gate_loss = str(row[gate_loss_col_idx]).strip() if gate_loss_col_idx < len(row) else ""
                if not current_gate_loss or current_gate_loss == "0" or current_gate_loss == "0.0":
                    row[gate_loss_col_idx] = f"{DEFAULT_GATE_HEAD_LOSS:.3f}"
                    changed = True
        
        if changed:
            self._set_sheet_data(sheet_data, redraw=True)
    
    def _auto_fill_structure_type(self, sheet_data: List[List[Any]], building_occurrences: dict) -> None:
        """
        自动填充建筑物之间的结构形式
        
        当建筑物名称第1次和最后1次出现之间有行时，
        将这些行的结构形式设置为该建筑物的结构形式。
        
        Args:
            children: 表格行列表
            all_col_ids: 列ID列表
            building_occurrences: 建筑物出现位置字典
        """
        name_col_idx = self._col_id_to_index.get("name", -1)
        structure_col_idx = self._col_id_to_index.get("structure_type", -1)
        if name_col_idx < 0 or structure_col_idx < 0:
            return
        
        for _, occurrences in building_occurrences.items():
            if len(occurrences) < 2:
                continue
            first_row_idx, first_structure = occurrences[0]
            last_row_idx, _ = occurrences[-1]
            building_structure = first_structure
            if not building_structure:
                continue
            
            for row_idx in range(first_row_idx + 1, last_row_idx):
                if row_idx < 0 or row_idx >= len(sheet_data):
                    continue
                row = sheet_data[row_idx]
                current_name = str(row[name_col_idx]).strip() if name_col_idx < len(row) else ""
                current_structure = str(row[structure_col_idx]).strip() if structure_col_idx < len(row) else ""
                if not current_name and not current_structure:
                    row[structure_col_idx] = building_structure

    def add_row(self, values: Optional[Dict] = None) -> str:
        """
        添加新行
        
        Args:
            values: 初始值字典
            
        Returns:
            新行的item id
        """
        row_data = []
        for col_def in ALL_COLUMNS:
            col_id = col_def["id"]
            row_data.append(values[col_id] if values and col_id in values else "")
        
        data = self._get_sheet_data()
        data.append(row_data)
        self._set_sheet_data(data, redraw=True)
        
        # 更新IP编号
        self._update_ip_numbers()
        
        if self.on_change:
            self.on_change()
        
        return str(len(data) - 1)
    
    def insert_row(self):
        """在选中行之前插入新行"""
        rows = self._get_selected_rows()
        if rows:
            index = min(rows)
        else:
            active = self._get_active_cell()
            index = active[0] if active else len(self._get_sheet_data())
        
        row_data = [""] * len(ALL_COLUMNS)
        data = self._get_sheet_data()
        index = max(0, min(index, len(data)))
        data.insert(index, row_data)
        self._set_sheet_data(data, redraw=True)
        
        self._update_ip_numbers()
        
        if self.on_change:
            self.on_change()
    
    def delete_row(self):
        """删除选中行"""
        rows = self._get_selected_rows()
        if not rows:
            messagebox.showwarning("提示", "请先选择要删除的行")
            return
        
        if not messagebox.askyesno("确认", f"确定要删除 {len(set(rows))} 行吗？"):
            return
        
        data = self._get_sheet_data()
        for r in sorted(set(rows), reverse=True):
            if 0 <= r < len(data):
                del data[r]
        
        self._set_sheet_data(data, redraw=True)
        self._custom_turn_radius_items.clear()
        self._update_ip_numbers()
        
        if self.on_change:
            self.on_change()
    
    def clear_all(self):
        """清空所有数据"""
        if not messagebox.askyesno("确认", "确定要清空所有数据吗？"):
            return
        
        self._set_sheet_data_reset([], redraw=True)
        self._custom_turn_radius_items.clear()
        self._negative_cells.clear()
        self._negative_highlighted.clear()
        try:
            self.sheet.dehighlight_all()
        except Exception:
            pass
        
        if self.on_change:
            self.on_change()

    def _apply_row_index_options(self) -> None:
        try:
            self.sheet.set_options(show_row_index=True, show_index=True, row_index_width=58, index_width=58, redraw=True)
        except Exception:
            try:
                self.sheet.refresh()
            except Exception:
                pass
    
    def copy_visible_region(self, *, include_headers: bool = True) -> None:
        if self.clipboard_handler is None:
            self.clipboard_handler = ClipboardHandler(self.winfo_toplevel())
        
        sheet_data = self._get_sheet_data()
        if not sheet_data:
            return
        try:
            r0, r1 = self.sheet.visible_rows
            c0, c1 = self.sheet.visible_columns
        except Exception:
            return
        
        r0 = max(0, int(r0))
        c0 = max(0, int(c0))
        r1 = min(len(sheet_data) - 1, int(r1))
        c1 = min(len(self._all_col_ids) - 1, int(c1))
        if r0 > r1 or c0 > c1:
            return
        
        out = []
        if include_headers:
            out.append([str(col.get("text", "")) for col in self._all_col_defs[c0 : c1 + 1]])
        for r in range(r0, r1 + 1):
            row = sheet_data[r]
            out.append([str(row[c]) if 0 <= c < len(row) else "" for c in range(c0, c1 + 1)])
        
        if out:
            self.clipboard_handler.copy_to_clipboard(out)
    
    def select_all_cells(self) -> None:
        try:
            self.sheet.select_all(redraw=False)
        except Exception:
            pass
        rows = len(self._get_sheet_data())
        cols = len(self._all_col_ids)
        if rows <= 0 or cols <= 0:
            return
        try:
            self.sheet.set_currently_selected(0, 0)
            self.sheet.select_cells((0, 0), (rows - 1, cols - 1), redraw=True)
        except Exception:
            try:
                self.sheet.redraw()
            except Exception:
                pass
    
    def clear_selected_contents(self) -> None:
        editable_cols = {self._col_id_to_index[cid] for cid in self._editable_col_ids if cid in self._col_id_to_index}
        if not editable_cols:
            return
        
        sheet_data = self._get_sheet_data()
        if not sheet_data:
            return
        
        rows_sel = sorted(set(self._get_selected_rows()))
        cols_sel = sorted(set(self._get_selected_columns()))
        cells_sel = self._get_selected_cells()
        active = self._get_active_cell()
        
        targets = set()
        if cells_sel:
            targets.update(cells_sel)
        if rows_sel:
            for r in rows_sel:
                for c in editable_cols:
                    targets.add((r, c))
        if cols_sel:
            for c in cols_sel:
                for r in range(len(sheet_data)):
                    targets.add((r, c))
        if not targets and active:
            targets.add(active)
        
        min_changed_row = None
        changed_cols = set()
        turn_radius_idx = self._col_id_to_index.get("turn_radius", -1)
        for r, c in targets:
            if r < 0 or r >= len(sheet_data):
                continue
            if c < 0 or c >= len(self._all_col_ids):
                continue
            if c not in editable_cols:
                continue
            sheet_data[r][c] = ""
            changed_cols.add(c)
            min_changed_row = r if min_changed_row is None else min(min_changed_row, r)
            if c == turn_radius_idx and r in self._custom_turn_radius_items:
                self._custom_turn_radius_items.discard(r)
        
        if min_changed_row is None:
            return
        
        self._set_sheet_data(sheet_data, redraw=True)
        self._update_ip_numbers()
        
        col_ids_changed = {self._all_col_ids[c] for c in changed_cols if 0 <= c < len(self._all_col_ids)}
        if {"x", "y", "turn_radius"} & col_ids_changed:
            self.recalculate(min_changed_row)
        
        if self.on_change:
            self.on_change()
    
    def cut_selected_cell_or_row(self) -> None:
        self.copy_selected_cell_or_row()
        self.clear_selected_contents()
    
    def redo(self) -> None:
        for call in (
            lambda: self.sheet.redo(),
            lambda: self.sheet.redo_last(),
        ):
            try:
                call()
                break
            except Exception:
                continue
        else:
            return
        
        self._auto_determine_in_out()
        self._update_ip_numbers()
        self.recalculate(0)
        
        if self.on_change:
            self.on_change()
    
    def fill_down(self) -> None:
        editable_cols = {self._col_id_to_index[cid] for cid in self._editable_col_ids if cid in self._col_id_to_index}
        if not editable_cols:
            return
        
        sheet_data = self._get_sheet_data()
        if not sheet_data:
            return
        
        cells = self._get_selected_cells()
        active = self._get_active_cell()
        if not cells and active:
            r, c = active
            if r <= 0 or c not in editable_cols:
                return
            if 0 <= r < len(sheet_data) and 0 <= c < len(self._all_col_ids):
                sheet_data[r][c] = sheet_data[r - 1][c]
                self._set_sheet_data(sheet_data, redraw=True)
                self._update_ip_numbers()
                if self._all_col_ids[c] in ("x", "y", "turn_radius"):
                    self.recalculate(r - 1)
                if self.on_change:
                    self.on_change()
            return
        
        if not cells:
            return
        
        min_r = min(r for r, _ in cells)
        max_r = max(r for r, _ in cells)
        min_c = min(c for _, c in cells)
        max_c = max(c for _, c in cells)
        if min_r < 0 or min_r >= len(sheet_data):
            return
        
        changed_cols = set()
        for c in range(min_c, max_c + 1):
            if c not in editable_cols:
                continue
            if c < 0 or c >= len(self._all_col_ids):
                continue
            src = sheet_data[min_r][c] if 0 <= min_r < len(sheet_data) else ""
            for r in range(min_r + 1, max_r + 1):
                if 0 <= r < len(sheet_data):
                    sheet_data[r][c] = src
            changed_cols.add(c)
        
        if not changed_cols:
            return
        
        self._set_sheet_data(sheet_data, redraw=True)
        self._update_ip_numbers()
        
        col_ids_changed = {self._all_col_ids[c] for c in changed_cols if 0 <= c < len(self._all_col_ids)}
        if {"x", "y", "turn_radius"} & col_ids_changed:
            self.recalculate(min_r)
        
        if self.on_change:
            self.on_change()
    
    def _update_ip_numbers(self):
        """
        更新所有行的IP编号
        
        IP显示逻辑：
        - 基本格式：IP + 序号
        - 只有当进出口为"进"或"出"时才添加扩展信息：
          - 添加 " " + 建筑物名称 + 结构形式缩写 + 进出口
          - 结构形式缩写：隧洞→"隧"，倒虹吸→"倒"，渡槽→"渡"，其他→""
        - 渐变段行（结构形式为"渐变段"）不分配IP编号，该列留空
        """
        ip_idx = self._col_id_to_index.get("ip_number", -1)
        name_idx = self._col_id_to_index.get("name", -1)
        structure_idx = self._col_id_to_index.get("structure_type", -1)
        in_out_idx = self._col_id_to_index.get("in_out", -1)
        
        if ip_idx < 0:
            return
        
        data = self._get_sheet_data()
        ip_counter = 0  # 独立的IP计数器，跳过渐变段行
        
        for i, row in enumerate(data):
            name = str(row[name_idx]).strip() if 0 <= name_idx < len(row) else ""
            structure_type = str(row[structure_idx]).strip() if 0 <= structure_idx < len(row) else ""
            in_out = str(row[in_out_idx]).strip() if 0 <= in_out_idx < len(row) else ""
            
            # 渐变段行不分配IP编号（通过结构形式判断）
            if structure_type == "渐变段":
                row[ip_idx] = ""
                continue
            
            base = f"IP{ip_counter}"
            ip_counter += 1
            
            if name and in_out in ("进", "出"):
                struct_abbr = ""
                if "隧洞" in structure_type:
                    struct_abbr = "隧"
                elif "倒虹吸" in structure_type:
                    struct_abbr = "倒"
                elif "渡槽" in structure_type:
                    struct_abbr = "渡"
                ip_str = f"{base} {name}{struct_abbr}{in_out}"
            else:
                ip_str = base
            
            row[ip_idx] = ip_str
        
        self._set_sheet_data(data, redraw=False)
        try:
            self.sheet.refresh()
        except Exception:
            pass
    
    def paste_from_clipboard(self):
        """
        从剪贴板粘贴数据
        
        支持类似Excel的粘贴功能：
        1. 从选中的单元格位置开始粘贴
        2. 剪贴板数据按行列解析（行用换行符分隔，列用制表符分隔）
        3. 超出现有行数时自动创建新行
        4. 超出列范围的数据不会被粘贴
        """
        if self.clipboard_handler is None:
            self.clipboard_handler = ClipboardHandler(self.winfo_toplevel())
        
        data = self.clipboard_handler.get_and_parse_excel_data()
        if not data:
            messagebox.showinfo("提示", "剪贴板中没有可用数据")
            return
        
        active = self._get_active_cell()
        start_row_idx = active[0] if active else len(self._get_sheet_data())
        start_col_idx = active[1] if active else 0
        
        total_cols = len(self._all_col_ids)
        editable_col_ids = set(self._editable_col_ids or [])
        
        # 用于跟踪是否粘贴了需要触发联动计算的列
        geometry_cols_pasted = False
        min_changed_row_idx = None
        
        sheet_data = self._get_sheet_data()
        needed_rows = start_row_idx + len(data)
        if len(sheet_data) < needed_rows:
            sheet_data.extend([[""] * total_cols for _ in range(needed_rows - len(sheet_data))])
        
        pasted_rows = 0
        for r_off, row_data in enumerate(data):
            current_row_idx = start_row_idx + r_off
            if current_row_idx >= len(sheet_data):
                break
            
            for c_off, value in enumerate(row_data):
                target_col_idx = start_col_idx + c_off
                if target_col_idx >= total_cols:
                    break
                if target_col_idx < 0 or target_col_idx >= len(self._all_col_ids):
                    continue
                col_id = self._all_col_ids[target_col_idx]
                if col_id not in editable_col_ids:
                    continue
                
                sheet_data[current_row_idx][target_col_idx] = value
                if col_id in ("x", "y", "turn_radius"):
                    geometry_cols_pasted = True
                    min_changed_row_idx = current_row_idx if min_changed_row_idx is None else min(min_changed_row_idx, current_row_idx)
            
            pasted_rows += 1
        
        self._set_sheet_data(sheet_data, redraw=True)
        
        # 更新IP编号
        self._update_ip_numbers()
        
        # 如果粘贴了几何相关列，触发联动计算
        if geometry_cols_pasted and min_changed_row_idx is not None:
            self.recalculate(min_changed_row_idx)
        
        if self.on_change:
            self.on_change()
        
        try:
            self.winfo_toplevel().focus_force()
        except Exception:
            pass
    
    def copy_selection(self):
        """复制选中行（兼容旧版本，推荐使用 copy_selected_cell_or_row）"""
        self.copy_selected_cell_or_row()
    
    def copy_selected_cell_or_row(self):
        """复制选中的单元格、多单元格区域或整行"""
        if self.clipboard_handler is None:
            self.clipboard_handler = ClipboardHandler(self.winfo_toplevel())
        
        sheet_data = self._get_sheet_data()
        
        rows = self._get_selected_rows()
        if rows:
            rows = sorted(set(rows))
            copied = [[str(v) for v in sheet_data[r]] for r in rows if 0 <= r < len(sheet_data)]
            if copied:
                self.clipboard_handler.copy_to_clipboard(copied)
            return
        
        cells = self._get_selected_cells()
        
        if cells:
            min_r = min(r for r, _ in cells)
            max_r = max(r for r, _ in cells)
            min_c = min(c for _, c in cells)
            max_c = max(c for _, c in cells)
            copied = []
            for r in range(min_r, max_r + 1):
                if r < 0 or r >= len(sheet_data):
                    continue
                row_out = []
                for c in range(min_c, max_c + 1):
                    if c < 0 or c >= len(self._all_col_ids):
                        continue
                    row_out.append(str(sheet_data[r][c]))
                copied.append(row_out)
            if copied:
                self.clipboard_handler.copy_to_clipboard(copied)
            return
        
        active = self._get_active_cell()
        if active:
            r, c = active
            if 0 <= r < len(sheet_data) and 0 <= c < len(self._all_col_ids):
                self.clipboard_handler.copy_to_clipboard([[str(sheet_data[r][c])]])
    
    def set_station_prefix(self, prefix: str) -> None:
        """
        设置桩号前缀
        
        Args:
            prefix: 桩号前缀，如"南支"
        """
        self.station_prefix = prefix

    def refresh_station_display(self, nodes: Optional[List[ChannelNode]] = None) -> None:
        if nodes is None:
            nodes = self.get_nodes()
        
        sheet_data = self._get_sheet_data()
        total_rows = min(len(sheet_data), len(nodes))
        
        cols = {
            "station_ip": "station_ip",
            "station_BC": "station_BC",
            "station_MC": "station_MC",
            "station_EC": "station_EC",
        }
        for i in range(total_rows):
            node = nodes[i]
            for col_id, attr in cols.items():
                c = self._col_id_to_index.get(col_id, -1)
                if c < 0:
                    continue
                sheet_data[i][c] = self._format_station(getattr(node, attr, 0.0))
        
        self._set_sheet_data(sheet_data, redraw=True)
    
    def _format_station(self, station_value: float) -> str:
        """
        格式化桩号显示
        
        格式：前缀+公里数+米数，例如"南支15+020.073"
        
        Args:
            station_value: 桩号数值（米）
            
        Returns:
            格式化后的桩号字符串
        """
        return ProjectSettings.format_station(station_value, self.station_prefix)
    
    def _parse_station(self, station_str: str) -> float:
        """
        从格式化的桩号字符串中提取数值
        
        解析格式如"南支15+020.073"，返回15020.073
        
        Args:
            station_str: 格式化的桩号字符串
            
        Returns:
            桩号数值（米）
        """
        if not station_str:
            return 0.0
        
        try:
            # 查找"+"号位置
            plus_idx = station_str.find('+')
            if plus_idx == -1:
                # 尝试直接解析为数字
                return float(station_str)
            
            # 提取公里数（+号前面的数字部分）
            km_part = ""
            for i in range(plus_idx - 1, -1, -1):
                if station_str[i].isdigit():
                    km_part = station_str[i] + km_part
                else:
                    break
            
            # 提取米数（+号后面的部分）
            meters_part = station_str[plus_idx + 1:]
            
            km = int(km_part) if km_part else 0
            meters = float(meters_part) if meters_part else 0.0
            
            return km * 1000 + meters
        except (ValueError, IndexError):
            return 0.0
    
    def get_nodes(self) -> List[ChannelNode]:
        """
        获取所有节点数据
        
        Returns:
            ChannelNode列表
        """
        nodes = []
        sheet_data = self._get_sheet_data()
        
        for values in sheet_data:
            
            # 创建节点
            node = ChannelNode()
            
            # 填充数据
            for i, col_def in enumerate(ALL_COLUMNS):
                col_id = col_def["id"]
                value = values[i] if i < len(values) else ""
                
                if col_id == "flow_section":
                    node.flow_section = str(value)
                elif col_id == "name":
                    node.name = str(value)
                elif col_id == "structure_type":
                    if value:
                        try:
                            node.structure_type = StructureType.from_string(str(value))
                        except ValueError:
                            pass
                elif col_id == "x":
                    try:
                        node.x = float(value) if value else 0.0
                    except ValueError:
                        node.x = 0.0
                elif col_id == "y":
                    try:
                        node.y = float(value) if value else 0.0
                    except ValueError:
                        node.y = 0.0
                elif col_id == "turn_radius":
                    try:
                        node.turn_radius = float(value) if value else 0.0
                    except ValueError:
                        node.turn_radius = 0.0
                elif col_id == "flow" or col_id == "flow_design":
                    try:
                        node.flow = float(value) if value else 0.0
                    except ValueError:
                        node.flow = 0.0
                elif col_id == "roughness":
                    try:
                        node.roughness = float(value) if value else 0.014
                    except ValueError:
                        node.roughness = 0.014
                elif col_id == "bottom_slope":
                    # 底坡存储为 1/i 格式，读取时转换为 i
                    try:
                        slope_inv = float(value) if value else 0
                        if slope_inv > 0:
                            node.slope_i = 1.0 / slope_inv
                        else:
                            node.slope_i = 0
                    except ValueError:
                        node.slope_i = 0
                elif col_id == "water_depth_design":
                    try:
                        node.water_depth = float(value) if value else 0.0
                    except ValueError:
                        node.water_depth = 0.0
                elif col_id == "cross_section_area":
                    try:
                        node.section_params["A"] = float(value) if value else 0.0
                    except ValueError:
                        pass
                elif col_id == "wetted_perimeter":
                    try:
                        node.section_params["X"] = float(value) if value else 0.0
                    except ValueError:
                        pass
                elif col_id == "hydraulic_radius":
                    try:
                        node.section_params["R"] = float(value) if value else 0.0
                    except ValueError:
                        pass
                elif col_id == "velocity_design":
                    try:
                        node.velocity = float(value) if value else 0.0
                    except ValueError:
                        node.velocity = 0.0
                elif col_id == "bottom_width":
                    try:
                        node.section_params["B"] = float(value) if value else 0.0
                    except ValueError:
                        pass
                elif col_id == "diameter":
                    try:
                        node.section_params["D"] = float(value) if value else 0.0
                    except ValueError:
                        pass
                elif col_id == "section_radius":
                    try:
                        node.section_params["R_circle"] = float(value) if value else 0.0
                    except ValueError:
                        pass
                elif col_id == "side_slope":
                    try:
                        node.section_params["m"] = float(value) if value else 0.0
                    except ValueError:
                        pass
                elif col_id == "station_ip":
                    node.station_ip = self._parse_station(str(value))
                elif col_id == "station_BC":
                    node.station_BC = self._parse_station(str(value))
                elif col_id == "station_MC":
                    node.station_MC = self._parse_station(str(value))
                elif col_id == "station_EC":
                    node.station_EC = self._parse_station(str(value))
                elif col_id == "turn_angle":
                    try:
                        node.turn_angle = float(value) if value else 0.0
                    except ValueError:
                        node.turn_angle = 0.0
                elif col_id == "tangent_length":
                    try:
                        node.tangent_length = float(value) if value else 0.0
                    except ValueError:
                        node.tangent_length = 0.0
                elif col_id == "arc_length":
                    try:
                        node.arc_length = float(value) if value else 0.0
                    except ValueError:
                        node.arc_length = 0.0
                elif col_id == "straight_distance":
                    try:
                        node.straight_distance = float(value) if value else 0.0
                    except ValueError:
                        node.straight_distance = 0.0
                elif col_id == "head_loss_reserve":
                    try:
                        node.head_loss_reserve = float(value) if value else 0.0
                    except ValueError:
                        node.head_loss_reserve = 0.0
                elif col_id == "head_loss_gate":
                    try:
                        node.head_loss_gate = float(value) if value else 0.0
                    except ValueError:
                        node.head_loss_gate = 0.0
            
            # 标记分水闸/分水口
            if node.structure_type and StructureType.is_diversion_gate(node.structure_type):
                node.is_diversion_gate = True
            
            nodes.append(node)
        
        return nodes
    
    def set_nodes(self, nodes: List[ChannelNode]) -> None:
        """
        设置节点数据
        
        Args:
            nodes: ChannelNode列表
        """
        self._custom_turn_radius_items.clear()
        
        rows = []
        for node in nodes:
            row_data = []
            for col_def in ALL_COLUMNS:
                col_id = col_def["id"]
                value = ""
                
                if col_id == "flow_section":
                    value = node.flow_section
                elif col_id == "name":
                    value = node.name
                elif col_id == "structure_type":
                    value = node.get_structure_type_str()
                elif col_id == "in_out":
                    # 渐变段行不显示进出口
                    value = "" if node.is_transition else node.get_in_out_str()
                elif col_id == "ip_number":
                    # 渐变段行不显示IP编号
                    value = "" if node.is_transition else node.get_ip_str()
                elif col_id == "x":
                    # 渐变段行不显示X坐标
                    value = "" if node.is_transition else str(node.x)
                elif col_id == "y":
                    # 渐变段行不显示Y坐标
                    value = "" if node.is_transition else str(node.y)
                elif col_id == "turn_radius":
                    # 渐变段行不显示转弯半径
                    if node.is_transition:
                        value = ""
                    elif node.turn_radius and node.turn_radius > 0:
                        value = str(node.turn_radius)
                    elif self._project_settings and self._project_settings.turn_radius > 0:
                        value = str(self._project_settings.turn_radius)
                elif col_id == "turn_angle":
                    # 渐变段行不显示转角
                    value = "" if node.is_transition else f"{node.turn_angle:.3f}"
                elif col_id == "tangent_length":
                    # 渐变段行不显示切线长
                    value = "" if node.is_transition else f"{node.tangent_length:.3f}"
                elif col_id == "arc_length":
                    # 渐变段行不显示曲线长
                    value = "" if node.is_transition else f"{node.arc_length:.3f}"
                elif col_id == "curve_length":
                    # 渐变段行不显示曲线段长
                    value = "" if node.is_transition else f"{node.curve_length:.3f}"
                elif col_id == "straight_distance":
                    # 渐变段行不显示直线距离
                    value = "" if node.is_transition else f"{node.straight_distance:.3f}"
                elif col_id == "station_ip":
                    # 渐变段行不显示IP桩号
                    value = "" if node.is_transition else self._format_station(node.station_ip)
                elif col_id == "station_BC":
                    # 渐变段行不显示BC桩号
                    value = "" if node.is_transition else self._format_station(node.station_BC)
                elif col_id == "station_MC":
                    # 渐变段行不显示MC桩号
                    value = "" if node.is_transition else self._format_station(node.station_MC)
                elif col_id == "station_EC":
                    # 渐变段行不显示EC桩号
                    value = "" if node.is_transition else self._format_station(node.station_EC)
                elif col_id == "flow" or col_id == "flow_design":
                    # 渐变段行不显示设计流量
                    value = "" if node.is_transition else (f"{node.flow:.3f}" if node.flow else "")
                elif col_id == "roughness":
                    # 渐变段行不显示糙率
                    value = "" if node.is_transition else (f"{node.roughness:.4f}" if node.roughness else "")
                elif col_id == "bottom_slope":
                    # 渐变段行不显示底坡
                    if node.is_transition:
                        value = ""
                    elif node.slope_i and node.slope_i > 0:
                        value = f"{1.0/node.slope_i:.0f}"
                elif col_id == "water_depth_design":
                    # 渐变段行不显示设计水深
                    value = "" if node.is_transition else (f"{node.water_depth:.3f}" if node.water_depth else "")
                elif col_id == "cross_section_area":
                    # 渐变段行不显示断面面积
                    if node.is_transition:
                        value = ""
                    elif hasattr(node, 'section_params') and isinstance(node.section_params, dict):
                        area = node.section_params.get("A", 0)
                        value = f"{area:.3f}" if area else ""
                    else:
                        value = ""
                elif col_id == "wetted_perimeter":
                    # 渐变段行不显示湿周
                    if node.is_transition:
                        value = ""
                    elif hasattr(node, 'section_params') and isinstance(node.section_params, dict):
                        perimeter = node.section_params.get("X", 0)
                        value = f"{perimeter:.3f}" if perimeter else ""
                    else:
                        value = ""
                elif col_id == "hydraulic_radius":
                    # 渐变段行不显示水力半径
                    if node.is_transition:
                        value = ""
                    elif hasattr(node, 'section_params') and isinstance(node.section_params, dict):
                        radius = node.section_params.get("R", 0)
                        value = f"{radius:.3f}" if radius else ""
                    else:
                        value = ""
                elif col_id == "velocity_design":
                    # 渐变段行不显示设计流速
                    value = "" if node.is_transition else (f"{node.velocity:.3f}" if node.velocity else "")
                elif col_id == "bottom_width":
                    # 渐变段行不显示底宽
                    if node.is_transition:
                        value = ""
                    elif hasattr(node, 'section_params') and isinstance(node.section_params, dict):
                        bottom_w = node.section_params.get("B", 0)
                        value = f"{bottom_w:.3f}" if bottom_w else ""
                    else:
                        value = ""
                elif col_id == "diameter":
                    # 渐变段行不显示直径
                    if node.is_transition:
                        value = ""
                    elif hasattr(node, 'section_params') and isinstance(node.section_params, dict):
                        diameter = node.section_params.get("D", 0)
                        value = f"{diameter:.3f}" if diameter else ""
                    else:
                        value = ""
                elif col_id == "section_radius":
                    # 渐变段行不显示断面半径
                    if node.is_transition:
                        value = ""
                    elif hasattr(node, 'section_params') and isinstance(node.section_params, dict):
                        r_circle = node.section_params.get("R_circle", 0)
                        value = f"{r_circle:.3f}" if r_circle else ""
                    else:
                        value = ""
                elif col_id == "side_slope":
                    # 渐变段行不显示边坡
                    if node.is_transition:
                        value = ""
                    elif hasattr(node, 'section_params') and isinstance(node.section_params, dict):
                        side_s = node.section_params.get("m", 0)
                        value = f"{side_s:.2f}" if side_s else ""
                    else:
                        value = ""
                elif hasattr(node, col_id):
                    attr_value = getattr(node, col_id)
                    value = str(attr_value) if attr_value else ""
                
                row_data.append(value)
            rows.append(row_data)
        
        
        self._set_sheet_data_reset(rows, redraw=True)
        try:
            self.sheet.set_xview(0.0)
            self.sheet.set_yview(0.0)
        except Exception:
            pass
        try:
            self.sheet.see(0, 0, keep_yscroll=False, keep_xscroll=False, redraw=False)
        except Exception:
            pass
        try:
            self.sheet.set_currently_selected(0, 0)
            self.sheet.select_cell(0, 0, redraw=False)
        except Exception:
            pass
        try:
            self.sheet.set_all_row_heights(height=22, only_set_if_too_small=True, redraw=False)
        except Exception:
            pass
        try:
            self.sheet.redraw()
        except Exception:
            try:
                self.sheet.refresh()
            except Exception:
                pass
        
        # 检查是否有有效的坐标数据，如果有则触发联动计算
        has_valid_coords = any(node.x != 0 or node.y != 0 for node in nodes)
        if has_valid_coords and len(nodes) >= 2:
            self.recalculate(0)
        else:
            # 即使没有有效坐标，也要执行进出口判别
            self._auto_determine_in_out()
            # 更新IP编号（根据进出口状态）
            self._update_ip_numbers()
        
        # 移除自动计算弯道水头损失，改为仅在"执行计算"时统一计算
    
    def update_results(self, nodes: List[ChannelNode]) -> None:
        """
        更新计算结果到表格
        
        Args:
            nodes: 计算完成的节点列表
        """
        # 缓存计算后的节点列表（包含计算详情，用于双击查看）
        self._calculated_nodes = nodes
        
        sheet_data = self._get_sheet_data()
        
        # 如果节点数量变化（有渐变段插入），先重建表格
        if len(nodes) != len(sheet_data):
            self.set_nodes(nodes)
            sheet_data = self._get_sheet_data()
        
        total_rows = len(sheet_data)
        
        def setv(row_idx: int, col_id: str, value: Any):
            c = self._col_id_to_index.get(col_id, -1)
            if c < 0 or row_idx >= len(sheet_data):
                return
            sheet_data[row_idx][c] = value
        
        for i in range(total_rows):
            node = nodes[i]
            
            # 渐变段行特殊处理：进出口、IP编号、X/Y坐标留空
            if node.is_transition:
                setv(i, "in_out", "")
                setv(i, "ip_number", "")
                setv(i, "x", "")
                setv(i, "y", "")
            else:
                setv(i, "in_out", node.get_in_out_str())
                setv(i, "ip_number", node.get_ip_str())
            
            # 渐变段行不参与几何计算，这些列留空
            if node.is_transition:
                setv(i, "turn_angle", "")
                setv(i, "tangent_length", "")
                setv(i, "arc_length", "")
                setv(i, "curve_length", "")
                setv(i, "straight_distance", "")
                setv(i, "station_ip", "")
                setv(i, "station_BC", "")
                setv(i, "station_MC", "")
                setv(i, "station_EC", "")
                setv(i, "check_pre_curve", "")
                setv(i, "check_post_curve", "")
                setv(i, "check_total_length", "")
            else:
                setv(i, "turn_angle", f"{node.turn_angle:.3f}")
                setv(i, "tangent_length", f"{node.tangent_length:.3f}")
                setv(i, "arc_length", f"{node.arc_length:.3f}")
                setv(i, "curve_length", f"{node.curve_length:.3f}")
                setv(i, "straight_distance", f"{node.straight_distance:.3f}")
                setv(i, "station_ip", self._format_station(node.station_ip))
                setv(i, "station_BC", self._format_station(node.station_BC))
                setv(i, "station_MC", self._format_station(node.station_MC))
                setv(i, "station_EC", self._format_station(node.station_EC))
                setv(i, "check_pre_curve", f"{node.check_pre_curve:.3f}")
                setv(i, "check_post_curve", f"{node.check_post_curve:.3f}")
                setv(i, "check_total_length", f"{node.check_total_length:.3f}")
            
            setv(i, "flow_design", f"{node.flow:.3f}" if node.flow else "")
            setv(i, "roughness", f"{node.roughness:.4f}" if node.roughness else "")
            
            if node.slope_i and node.slope_i > 0:
                setv(i, "bottom_slope", f"{1.0 / node.slope_i:.0f}")
            else:
                setv(i, "bottom_slope", "")
            
            bottom_w = node.section_params.get("B", 0) if node.section_params else 0
            setv(i, "bottom_width", f"{bottom_w:.3f}" if bottom_w else "")
            
            diameter = node.section_params.get("D", 0) if node.section_params else 0
            setv(i, "diameter", f"{diameter:.3f}" if diameter else "")
            
            r_circle = node.section_params.get("R_circle", 0) if node.section_params else 0
            setv(i, "section_radius", f"{r_circle:.3f}" if r_circle else "")
            
            side_s = node.section_params.get("m", 0) if node.section_params else 0
            setv(i, "side_slope", f"{side_s:.2f}" if side_s else "")
            
            setv(i, "water_depth_design", f"{node.water_depth:.3f}" if node.water_depth else "")
            
            area = node.section_params.get("A", 0) if node.section_params else 0
            setv(i, "cross_section_area", f"{area:.3f}" if area else "")
            
            perimeter = node.section_params.get("X", 0) if node.section_params else 0
            setv(i, "wetted_perimeter", f"{perimeter:.3f}" if perimeter else "")
            
            radius = node.section_params.get("R", 0) if node.section_params else 0
            setv(i, "hydraulic_radius", f"{radius:.3f}" if radius else "")
            
            setv(i, "velocity_design", f"{node.velocity:.3f}" if node.velocity else "")
            if node.arc_length > 0 and node.velocity > 0 and radius > 0:
                setv(i, "head_loss_bend", f"{node.head_loss_bend:.3f}")
            else:
                setv(i, "head_loss_bend", "")
            
            # 沿程水头损失
            setv(i, "head_loss_friction", f"{node.head_loss_friction:.3f}" if node.head_loss_friction else "")
            
            # 预留水头损失（用户可编辑，保留用户输入值）
            head_loss_reserve = getattr(node, 'head_loss_reserve', 0.0) or 0.0
            if head_loss_reserve > 0:
                setv(i, "head_loss_reserve", f"{head_loss_reserve:.3f}")
            
            # 过闸水头损失（分水闸自动填充，其他类型可手动输入）
            head_loss_gate = getattr(node, 'head_loss_gate', 0.0) or 0.0
            if head_loss_gate > 0:
                setv(i, "head_loss_gate", f"{head_loss_gate:.3f}")
            else:
                setv(i, "head_loss_gate", "")
            
            # 倒虹吸水头损失
            head_loss_siphon = getattr(node, 'head_loss_siphon', 0.0) or 0.0
            if head_loss_siphon > 0:
                setv(i, "head_loss_siphon", f"{head_loss_siphon:.3f}")
            
            # 渐变段行特殊处理（方案B）
            if node.is_transition:
                # 渐变段行显示渐变段水头损失和累计损失，但总损失、水位、底高程留空
                setv(i, "head_loss_transition", f"{node.head_loss_transition:.3f}" if node.head_loss_transition else "")
                setv(i, "head_loss_total", "")
                setv(i, "head_loss_cumulative", f"{node.head_loss_cumulative:.3f}" if node.head_loss_cumulative else "")
                setv(i, "water_level", "")
                setv(i, "bottom_elevation", "")
            else:
                # 普通节点：渐变段水头损失列留空
                setv(i, "head_loss_transition", "")
                setv(i, "head_loss_total", f"{node.head_loss_total:.3f}" if node.head_loss_total else "")
                setv(i, "head_loss_cumulative", f"{node.head_loss_cumulative:.3f}" if node.head_loss_cumulative else "")
                setv(i, "water_level", f"{node.water_level:.3f}" if node.water_level else "")
                setv(i, "bottom_elevation", f"{node.bottom_elevation:.3f}" if node.bottom_elevation else "")
        
        self._set_sheet_data(sheet_data, redraw=True)
        
        # 更新负值单元格高亮
        self._update_negative_highlights(nodes)
    
    def _on_cell_double_click(self, event):
        """
        双击单元格事件处理
        
        对于水头损失列，显示详细计算过程（LaTeX公式渲染）
        """
        try:
            # tksheet 7.x 需要传入 event 对象而不是坐标
            r = self.sheet.MT.identify_row(event)
            c = self.sheet.MT.identify_col(event)
        except Exception as e:
            return
        
        if r is None or c is None:
            return
        
        # 获取列ID
        if c < 0 or c >= len(self._all_col_ids):
            return
        col_id = self._all_col_ids[c]
        
        # 处理各类水头损失列的双击
        if col_id == "head_loss_bend":
            self._show_bend_calc_details(r)
        elif col_id == "head_loss_friction":
            self._show_friction_calc_details(r)
        elif col_id == "head_loss_transition":
            self._show_transition_calc_details(r)
        elif col_id == "head_loss_total":
            self._show_total_calc_details(r)
    
    def _get_calculated_nodes(self) -> List[ChannelNode]:
        """
        获取带有计算详情的节点列表
        
        优先返回缓存的计算节点（包含详细计算信息），
        如果没有缓存则返回从表格重新读取的节点。
        
        Returns:
            节点列表
        """
        if self._calculated_nodes and len(self._calculated_nodes) > 0:
            return self._calculated_nodes
        return self.get_nodes()
    
    def _show_bend_calc_details(self, row_idx: int):
        """
        显示弯道水头损失的详细计算过程
        
        Args:
            row_idx: 行索引
        """
        nodes = self._get_calculated_nodes()
        if row_idx < 0 or row_idx >= len(nodes):
            return
        
        node = nodes[row_idx]
        
        # 检查是否有弯道损失数据
        if not node.bend_calc_details:
            messagebox.showinfo("提示", "该行没有弯道水头损失计算数据")
            return
        
        from ui.formula_dialog import show_bend_loss_dialog
        show_bend_loss_dialog(self, node.name or f"行{row_idx+1}", node.bend_calc_details)
    
    def _show_friction_calc_details(self, row_idx: int):
        """
        显示沿程水头损失的详细计算过程
        
        Args:
            row_idx: 行索引
        """
        nodes = self._get_calculated_nodes()
        if row_idx < 0 or row_idx >= len(nodes):
            return
        
        node = nodes[row_idx]
        
        # 检查是否有沿程损失数据
        if not node.friction_calc_details:
            messagebox.showinfo("提示", "该行没有沿程水头损失计算数据")
            return
        
        from ui.formula_dialog import show_friction_loss_dialog
        show_friction_loss_dialog(self, node.name or f"行{row_idx+1}", node.friction_calc_details)
    
    def _show_total_calc_details(self, row_idx: int):
        """
        显示总水头损失的详细计算过程
        
        Args:
            row_idx: 行索引
        """
        nodes = self._get_calculated_nodes()
        if row_idx < 0 or row_idx >= len(nodes):
            return
        
        node = nodes[row_idx]
        
        # 渐变段行没有总水头损失
        if node.is_transition:
            messagebox.showinfo("提示", "渐变段行没有总水头损失，请双击渐变段水头损失列查看")
            return
        
        # 汇总各项损失
        # 查找该行之前的渐变段损失
        h_transition = 0.0
        for i in range(row_idx - 1, -1, -1):
            if nodes[i].is_transition:
                h_transition += nodes[i].head_loss_transition
            elif not nodes[i].is_transition:
                break  # 遇到非渐变段行就停止
        
        details = {
            'head_loss_bend': node.head_loss_bend,
            'head_loss_transition': h_transition,
            'head_loss_friction': node.head_loss_friction,
            'head_loss_reserve': getattr(node, 'head_loss_reserve', 0.0) or 0.0,
            'head_loss_gate': getattr(node, 'head_loss_gate', 0.0) or 0.0,
            'head_loss_siphon': getattr(node, 'head_loss_siphon', 0.0) or 0.0,
            'head_loss_total': node.head_loss_total
        }
        
        from ui.formula_dialog import show_total_loss_dialog
        show_total_loss_dialog(self, node.name or f"行{row_idx+1}", details)
    
    def _show_transition_calc_details(self, row_idx: int):
        """
        显示渐变段水头损失的详细计算过程
        
        使用弹窗显示计算过程和数值
        
        Args:
            row_idx: 行索引
        """
        nodes = self._get_calculated_nodes()
        if row_idx < 0 or row_idx >= len(nodes):
            return
        
        node = nodes[row_idx]
        
        # 检查是否为渐变段行
        if not node.is_transition:
            messagebox.showinfo("提示", "该行不是渐变段，无法显示详细计算过程")
            return
        
        details = node.transition_calc_details
        if not details:
            messagebox.showinfo("提示", "该渐变段尚未计算水头损失")
            return
        
        # 创建详细信息窗口
        detail_window = tk.Toplevel(self)
        detail_window.title(f"{node.name} - 渐变段水头损失计算详情")
        detail_window.geometry("650x550")
        detail_window.transient(self.winfo_toplevel())
        
        # 创建滚动文本框
        text_frame = ttk.Frame(detail_window)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        text = tk.Text(text_frame, wrap=tk.WORD, font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(text_frame, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 填充详细信息
        zeta = details.get('zeta', 0)
        v1 = details.get('v1', 0)
        v2 = details.get('v2', 0)
        B1 = details.get('B1', 0)
        B2 = details.get('B2', 0)
        length = details.get('length', 0)
        R_avg = details.get('R_avg', 0)
        v_avg = details.get('v_avg', 0)
        h_j1 = details.get('h_j1', 0)
        h_f = details.get('h_f', 0)
        total = details.get('total', 0)
        
        content = f"""
渐变段水头损失计算详情
{'='*55}

1. 基本信息
   - 渐变段类型: {details.get('transition_type', '')}
   - 渐变段形式: {details.get('transition_form', '')}
   - 局部损失系数 ζ₁: {zeta:.4f}

2. 流速参数
   - 起始流速 v₁: {v1:.4f} m/s
   - 末端流速 v₂: {v2:.4f} m/s
   - 平均流速 v_avg: {v_avg:.4f} m/s

3. 断面参数
   - 起始水面宽度 B₁: {B1:.3f} m
   - 末端水面宽度 B₂: {B2:.3f} m
   - 平均水力半径 R_avg: {R_avg:.4f} m

4. 渐变段长度计算
   L = 系数 × |B₁ - B₂|
   L = {length:.3f} m
   (已按规范约束取大值)

5. 局部水头损失计算 (公式见表K.1.2)
   h_j1 = ξ₁ × |v₂² - v₁²| / (2g)
        = {zeta:.4f} × |{v2:.4f}² - {v1:.4f}²| / (2×9.81)
        = {zeta:.4f} × |{v2**2:.4f} - {v1**2:.4f}| / 19.62
        = {zeta:.4f} × {abs(v2**2 - v1**2):.4f} / 19.62
        = {h_j1:.4f} m

6. 沿程水头损失计算 (平均值法)
   h_f = i × L
   其中 i = (v_avg × n / R_avg^(2/3))²
   h_f = {h_f:.4f} m

7. 总水头损失
   h_渐 = h_j1 + h_f
        = {h_j1:.4f} + {h_f:.4f}
        = {total:.4f} m

{'='*55}
"""
        
        text.insert("1.0", content)
        text.configure(state="disabled")
        
        # 按钮区域
        btn_frame = ttk.Frame(detail_window)
        btn_frame.pack(fill=tk.X, pady=10)
        
        # 关闭按钮
        close_btn = ttk.Button(btn_frame, text="关闭", command=detail_window.destroy)
        close_btn.pack(side=tk.RIGHT, padx=10)
