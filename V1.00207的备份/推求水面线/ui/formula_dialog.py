# -*- coding: utf-8 -*-
"""
公式渲染对话框组件

用于展示水头损失等计算的详细过程，使用 matplotlib 渲染 LaTeX 公式。
"""

import tkinter as tk
from tkinter import ttk
from typing import List, Dict, Any, Optional
import io

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class FormulaDialog:
    """
    公式渲染对话框
    
    使用 matplotlib 渲染 LaTeX 公式，展示详细计算过程。
    """
    
    def __init__(self, parent: tk.Widget, title: str, sections: List[Dict[str, Any]], 
                 width: int = 700, height: int = 600):
        """
        初始化公式对话框
        
        Args:
            parent: 父窗口
            title: 对话框标题
            sections: 内容段落列表，每个段落包含:
                - title: 段落标题
                - formula: LaTeX 公式字符串 (可选)
                - content: 文本内容 (可选)
                - values: 代入数值的计算过程 (可选)
            width: 对话框宽度
            height: 对话框高度
        """
        self.parent = parent
        self.title = title
        self.sections = sections
        self.width = width
        self.height = height
        
        # 缓存渲染好的公式图片
        self._formula_cache: Dict[str, Any] = {}
        
        self._create_dialog()
    
    def _create_dialog(self):
        """创建对话框"""
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title(self.title)
        self.dialog.geometry(f"{self.width}x{self.height}")
        self.dialog.transient(self.parent.winfo_toplevel())
        
        # 创建主框架
        main_frame = ttk.Frame(self.dialog)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 创建带滚动条的画布
        canvas = tk.Canvas(main_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 绑定鼠标滚轮
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 添加内容
        self._add_content()
        
        # 关闭按钮
        btn_frame = ttk.Frame(self.dialog)
        btn_frame.pack(fill=tk.X, pady=10)
        
        close_btn = ttk.Button(btn_frame, text="关闭", command=self.dialog.destroy)
        close_btn.pack(side=tk.RIGHT, padx=10)
    
    def _add_content(self):
        """添加内容到对话框"""
        for i, section in enumerate(self.sections):
            # 添加分隔线（除了第一个段落）
            if i > 0:
                sep = ttk.Separator(self.scrollable_frame, orient="horizontal")
                sep.pack(fill=tk.X, pady=10)
            
            # 段落标题
            if "title" in section:
                title_label = ttk.Label(
                    self.scrollable_frame, 
                    text=section["title"],
                    font=("Microsoft YaHei", 11, "bold")
                )
                title_label.pack(anchor="w", pady=(5, 5))
            
            # 文本内容
            if "content" in section:
                content_label = ttk.Label(
                    self.scrollable_frame,
                    text=section["content"],
                    font=("Microsoft YaHei", 10),
                    wraplength=self.width - 60
                )
                content_label.pack(anchor="w", pady=(0, 5))
            
            # LaTeX 公式
            if "formula" in section:
                self._add_formula(section["formula"])
            
            # 代入数值的计算过程
            if "values" in section:
                values_frame = ttk.Frame(self.scrollable_frame)
                values_frame.pack(anchor="w", pady=(5, 5), fill=tk.X)
                
                # 使用等宽字体显示计算过程
                values_text = tk.Text(
                    values_frame, 
                    font=("Consolas", 10),
                    height=min(len(section["values"].split("\n")) + 1, 10),
                    wrap=tk.WORD,
                    bg="#f5f5f5",
                    relief=tk.FLAT,
                    padx=10,
                    pady=5
                )
                values_text.insert("1.0", section["values"])
                values_text.configure(state="disabled")
                values_text.pack(fill=tk.X, expand=True)
    
    def _add_formula(self, latex: str):
        """
        添加 LaTeX 公式
        
        Args:
            latex: LaTeX 公式字符串
        """
        if HAS_MATPLOTLIB and HAS_PIL:
            # 检查缓存
            if latex in self._formula_cache:
                img = self._formula_cache[latex]
            else:
                try:
                    # 创建 matplotlib 图形
                    fig = plt.figure(figsize=(6, 0.8), dpi=100)
                    fig.patch.set_facecolor('white')
                    
                    # 渲染 LaTeX
                    fig.text(0.5, 0.5, latex, fontsize=14, ha='center', va='center',
                            transform=fig.transFigure)
                    
                    # 保存为图片
                    buf = io.BytesIO()
                    fig.savefig(buf, format='png', bbox_inches='tight',
                               pad_inches=0.1, facecolor='white', edgecolor='none')
                    buf.seek(0)
                    plt.close(fig)
                    
                    # 转换为 PhotoImage
                    pil_img = Image.open(buf)
                    img = ImageTk.PhotoImage(pil_img)
                    
                    # 缓存
                    self._formula_cache[latex] = img
                except Exception as e:
                    # 渲染失败，使用纯文本
                    self._add_formula_text(latex)
                    return
            
            # 显示图片
            formula_frame = ttk.Frame(self.scrollable_frame)
            formula_frame.pack(anchor="w", pady=5)
            
            label = tk.Label(formula_frame, image=img, bg="white")
            label.image = img  # 保持引用
            label.pack(anchor="w")
        else:
            self._add_formula_text(latex)
    
    def _add_formula_text(self, latex: str):
        """使用纯文本显示公式"""
        latex_text = latex.replace("$", "")
        formula_label = ttk.Label(
            self.scrollable_frame,
            text=latex_text,
            font=("Consolas", 11)
        )
        formula_label.pack(anchor="w", pady=5)


def show_bend_loss_dialog(parent: tk.Widget, node_name: str, details: Dict[str, Any]):
    """
    显示弯道水头损失计算详情对话框
    
    Args:
        parent: 父窗口
        node_name: 节点名称
        details: 计算详情字典
    """
    n = details.get('n', 0)
    L = details.get('L', 0)
    v = details.get('v', 0)
    R = details.get('R', 0)
    Rc = details.get('Rc', 0)
    B = details.get('B', 0)
    hw = details.get('hw', 0)
    
    sections = [
        {
            "title": "1. 弯道水头损失公式",
            "formula": r"$h_w = \frac{n^2 \cdot L \cdot v^2}{R^{4/3}} \times \frac{3}{4} \times \sqrt{\frac{B}{R_c}}$",
            "content": "其中: n=糙率, L=弯道长度(弧长), v=流速, R=水力半径, B=水面宽度, Rc=转弯半径"
        },
        {
            "title": "2. 计算参数",
            "values": f"""糙率 n = {n:.6f}
弯道长度 L = {L:.3f} m
流速 v = {v:.4f} m/s
水力半径 R = {R:.4f} m
水面宽度 B = {B:.3f} m
转弯半径 Rc = {Rc:.3f} m"""
        },
        {
            "title": "3. 代入公式计算",
            "values": f"""h_w = ({n:.6f})² × {L:.3f} × ({v:.4f})² / ({R:.4f})^(4/3) × 0.75 × √({B:.3f}/{Rc:.3f})
    = {n**2:.10f} × {L:.3f} × {v**2:.6f} / {R**(4/3):.6f} × 0.75 × √{B/Rc if Rc > 0 else 0:.6f}
    = {hw:.6f} m"""
        },
        {
            "title": "4. 计算结果",
            "formula": f"$h_w = {hw:.4f} \\ m$"
        }
    ]
    
    FormulaDialog(parent, f"{node_name} - 弯道水头损失计算详情", sections)


def show_friction_loss_dialog(parent: tk.Widget, node_name: str, details: Dict[str, Any]):
    """
    显示沿程水头损失计算详情对话框
    
    Args:
        parent: 父窗口
        node_name: 节点名称
        details: 计算详情字典
    """
    method = details.get('method', 'slope')  # 'slope' 或 'manning'
    
    sections = []
    
    if method == 'slope':
        # 底坡法
        slope_i = details.get('slope_i', 0)
        L_effective = details.get('L_effective', 0)
        hf = details.get('hf', 0)
        
        sections = [
            {
                "title": "1. 沿程水头损失公式（底坡法）",
                "formula": r"$h_f = i \times L_{eff}$",
                "content": "其中: i=底坡, Leff=有效计算长度"
            },
            {
                "title": "2. 有效长度计算",
                "formula": r"$L_{eff} = \Delta S_{MC} - L_{trans} - \frac{L_{arc,1}}{2} - \frac{L_{arc,2}}{2}$",
                "values": f"""有效长度 Leff = {L_effective:.3f} m
(扣除了渐变段长度和上下游弧长的一半)"""
            },
            {
                "title": "3. 计算参数",
                "values": f"""底坡 i = {slope_i:.6f} (即 1/{1/slope_i:.0f} 如果底坡非零)
有效长度 Leff = {L_effective:.3f} m"""
            },
            {
                "title": "4. 代入公式计算",
                "values": f"""h_f = {slope_i:.6f} × {L_effective:.3f}
    = {hf:.6f} m"""
            },
            {
                "title": "5. 计算结果",
                "formula": f"$h_f = {hf:.4f} \\ m$"
            }
        ]
    else:
        # 曼宁法
        J1 = details.get('J1', 0)
        J2 = details.get('J2', 0)
        J_avg = details.get('J_avg', 0)
        L = details.get('L', 0)
        hf = details.get('hf', 0)
        n = details.get('n', 0)
        v1 = details.get('v1', 0)
        v2 = details.get('v2', 0)
        R1 = details.get('R1', 0)
        R2 = details.get('R2', 0)
        
        sections = [
            {
                "title": "1. 沿程水头损失公式（曼宁法）",
                "formula": r"$h_f = J_{avg} \times L$",
                "content": "其中: J_avg=平均水力坡降, L=计算长度"
            },
            {
                "title": "2. 水力坡降计算公式",
                "formula": r"$J = \left(\frac{v \cdot n}{R^{2/3}}\right)^2$",
                "content": "其中: v=流速, n=糙率, R=水力半径"
            },
            {
                "title": "3. 计算参数",
                "values": f"""糙率 n = {n:.6f}
上游流速 v₁ = {v1:.4f} m/s
下游流速 v₂ = {v2:.4f} m/s
上游水力半径 R₁ = {R1:.4f} m
下游水力半径 R₂ = {R2:.4f} m
计算长度 L = {L:.3f} m"""
            },
            {
                "title": "4. 水力坡降计算",
                "values": f"""J₁ = (v₁ × n / R₁^(2/3))² = ({v1:.4f} × {n:.6f} / {R1:.4f}^0.667)² = {J1:.8f}
J₂ = (v₂ × n / R₂^(2/3))² = ({v2:.4f} × {n:.6f} / {R2:.4f}^0.667)² = {J2:.8f}
J_avg = (J₁ + J₂) / 2 = {J_avg:.8f}"""
            },
            {
                "title": "5. 代入公式计算",
                "values": f"""h_f = J_avg × L = {J_avg:.8f} × {L:.3f}
    = {hf:.6f} m"""
            },
            {
                "title": "6. 计算结果",
                "formula": f"$h_f = {hf:.4f} \\ m$"
            }
        ]
    
    FormulaDialog(parent, f"{node_name} - 沿程水头损失计算详情", sections)


def show_total_loss_dialog(parent: tk.Widget, node_name: str, details: Dict[str, Any]):
    """
    显示总水头损失计算详情对话框
    
    Args:
        parent: 父窗口
        node_name: 节点名称
        details: 计算详情字典
    """
    hw = details.get('head_loss_bend', 0)
    h_transition = details.get('head_loss_transition', 0)
    hf = details.get('head_loss_friction', 0)
    h_reserve = details.get('head_loss_reserve', 0)
    h_gate = details.get('head_loss_gate', 0)
    h_siphon = details.get('head_loss_siphon', 0)
    h_total = details.get('head_loss_total', 0)
    
    sections = [
        {
            "title": "1. 总水头损失公式",
            "formula": r"$h_{\Sigma} = h_w + h_{tr} + h_f + h_{res} + h_{gate} + h_{sip}$",
            "content": "其中: h_w=弯道水头损失, h_tr=渐变段水头损失, h_f=沿程水头损失, h_res=预留水头损失, h_gate=过闸水头损失, h_sip=倒虹吸水头损失"
        },
        {
            "title": "2. 各项损失值",
            "values": f"""弯道水头损失 h_w = {hw:.4f} m
渐变段水头损失 h_渐 = {h_transition:.4f} m
沿程水头损失 h_f = {hf:.4f} m
预留水头损失 h_预留 = {h_reserve:.4f} m
过闸水头损失 h_过闸 = {h_gate:.4f} m
倒虹吸水头损失 h_倒虹吸 = {h_siphon:.4f} m"""
        },
        {
            "title": "3. 代入公式计算",
            "values": f"""h_总 = {hw:.4f} + {h_transition:.4f} + {hf:.4f} + {h_reserve:.4f} + {h_gate:.4f} + {h_siphon:.4f}
    = {h_total:.4f} m"""
        },
        {
            "title": "4. 计算结果",
            "formula": f"$h_{{\\Sigma}} = {h_total:.4f} \\ m$"
        }
    ]
    
    FormulaDialog(parent, f"{node_name} - 总水头损失计算详情", sections)
