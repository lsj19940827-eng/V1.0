# -*- coding: utf-8 -*-
"""
LaTeX 公式渲染器 —— 使用 matplotlib SVG 矢量渲染，在 QWebEngineView 中显示

将公式渲染为 SVG（矢量格式），直接内联嵌入 HTML，
无需网络、无锯齿、任何缩放下都完美清晰。

功能：
  1. text_to_latex()            : 将纯文本公式行转换为 LaTeX 字符串
  2. render_latex_svg()         : 将 LaTeX 渲染为内联 SVG 字符串
  3. plain_text_to_formula_html(): 将纯文本计算结果转换为含 SVG 公式的 HTML
  4. plain_text_to_formula_body(): 同上，但仅返回 <body> 内部内容
  5. wrap_with_katex()           : 将任意 body HTML 包装为完整 HTML（保持兼容）
  6. load_formula_page()         : 将 HTML 加载到 QWebEngineView
"""

import io
import re
import html as html_mod

import matplotlib
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas

# ============================================================
# matplotlib mathtext 配置（支持中文下角标 + SVG 路径输出）
# ============================================================
_MATH_RC = {
    'mathtext.fontset': 'custom',
    'mathtext.rm': 'Microsoft YaHei',
    'mathtext.it': 'Microsoft YaHei',
    'mathtext.bf': 'Microsoft YaHei',
    'mathtext.sf': 'Microsoft YaHei',
    'mathtext.cal': 'Microsoft YaHei',
    'mathtext.tt': 'Microsoft YaHei',
    'mathtext.default': 'rm',
    'svg.fonttype': 'path',       # 文字转路径，完全自包含
}

_BASE_CSS = """
* { box-sizing: border-box; }
body {
    font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
    font-size: 14px; color: #242424; line-height: 1.6;
    margin: 0; padding: 16px 20px; background: #F5F5F5;
}
svg { vertical-align: middle; }
.main-title {
    text-align: center; font-weight: 700;
    font-size: 18px; color: #242424; margin: 8px 0 16px 0;
}
.section-banner {
    background: linear-gradient(135deg, #1565C0, #1E88E5);
    color: #fff; font-weight: 600; font-size: 15px;
    padding: 10px 20px; margin: 18px 0 10px 0;
    border-radius: 8px; letter-spacing: 0.5px;
}
.step-card {
    display: flex; align-items: flex-start;
    background: #fff; border: 1px solid #F0F0F0;
    border-radius: 8px; margin: 6px 0;
    padding: 8px 14px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.04), 0 0 2px rgba(0,0,0,0.06);
}
.step-card.verify-pass { border-left: 4px solid #43A047; }
.step-card.verify-fail { border-left: 4px solid #E53935; }
.step-badge {
    background: #1976D2; color: #fff;
    font-weight: 600; font-size: 13px;
    min-width: 32px; height: 32px; border-radius: 16px;
    display: flex; align-items: center; justify-content: center;
    margin-right: 14px; flex-shrink: 0; padding: 0 2px;
}
.step-card.verify-pass .step-badge { background: #43A047; }
.step-card.verify-fail .step-badge { background: #E53935; }
.step-body { flex: 1; min-width: 0; }
.step-title {
    font-weight: 600; font-size: 14px; color: #242424;
    margin-bottom: 4px; border-bottom: 1px solid #F5F5F5; padding-bottom: 4px;
}
.formula-line {
    margin: 4px 0; padding: 6px 12px;
    background: #F8F9FE; border-radius: 6px;
}
.content-line { margin: 3px 0; font-size: 13px; color: #424242; }
.step-body .content-line {
    margin: 4px 0; padding: 6px 12px;
    background: #F8F9FE; border-radius: 6px;
}
.result-pass {
    margin: 6px 0; padding: 8px 14px; border-radius: 6px;
    background: #E8F5E9; color: #2E7D32; border-left: 3px solid #43A047;
    font-size: 13px;
}
.result-fail {
    margin: 6px 0; padding: 8px 14px; border-radius: 6px;
    background: #FFEBEE; color: #C62828; border-left: 3px solid #E53935;
    font-size: 13px;
}
.param-grid {
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 6px; margin: 6px 0;
}
.param-cell {
    background: #fff; border: 1px solid #F0F0F0;
    border-radius: 8px; padding: 8px 12px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.04), 0 0 2px rgba(0,0,0,0.06);
    display: flex; align-items: flex-start;
}
.info-panel {
    background: #fff; border: 1px solid #F0F0F0;
    border-radius: 8px; margin: 6px 0; padding: 14px 20px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.04), 0 0 2px rgba(0,0,0,0.06);
}
.info-line { margin: 3px 0; font-size: 13px; color: #424242; }
.info-subtitle {
    font-weight: 600; font-size: 14px; color: #242424; margin: 8px 0 4px 0;
}
.result-banner {
    font-weight: 700; font-size: 16px; color: #fff;
    padding: 14px 24px; margin: 14px 0;
    border-radius: 8px; text-align: center;
}
.result-banner.pass { background: linear-gradient(135deg, #43A047, #66BB6A); }
.result-banner.fail { background: linear-gradient(135deg, #E53935, #EF5350); }
.norm-table-title {
    font-size: 13px; color: #333; text-align: center;
    margin: 12px 0 8px 0; font-weight: 600;
}
.norm-table {
    width: 100%; border-collapse: collapse; margin: 0 0 6px 0;
}
.norm-table th, .norm-table td {
    border: 1px solid #333;
    padding: 8px 14px; font-size: 13px; color: #333; text-align: center;
}
.norm-table th { font-weight: 600; }
.norm-table-note {
    font-size: 12px; color: #555; margin: 4px 0 8px 0;
}
"""

# SVG 渲染缓存
_svg_cache = {}


def _e(s):
    """HTML 转义"""
    return html_mod.escape(str(s))


# ============================================================
# SVG 矢量渲染核心
# ============================================================

def render_latex_svg(latex_str, fontsize=14):
    """将 LaTeX 公式渲染为内联 SVG 字符串（矢量，无限清晰）。

    Returns
    -------
    str or None
        SVG 标签字符串，渲染失败返回 None
    """
    cache_key = (latex_str, fontsize)
    cached = _svg_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        with matplotlib.rc_context(_MATH_RC):
            fig = Figure()
            canvas = FigureCanvas(fig)
            fig.patch.set_alpha(0.0)

            # 文本居中放置在默认大图(6.4×4.8 inch)中，
            # 完全依赖 bbox_inches='tight' 裁剪到实际内容。
            # 旧方案手动测量 get_window_extent 再缩小 figure，
            # 但对复杂 LaTeX（\times, \sum 等）测量偏小，
            # 导致 figure 太窄、SVG 内容被裁切。
            fig.text(0.5, 0.5, '$' + latex_str + '$',
                     fontsize=fontsize, va='center', ha='center',
                     color='#1a1a1a')

            buf = io.BytesIO()
            fig.savefig(buf, format='svg', transparent=True,
                        bbox_inches='tight', pad_inches=0.05)

            import matplotlib.pyplot as plt
            plt.close(fig)

            svg_str = buf.getvalue().decode('utf-8')
            # 去掉 XML 声明和 DOCTYPE，只保留 <svg> 标签以便内联
            svg_str = re.sub(r'<\?xml[^?]*\?>\s*', '', svg_str)
            svg_str = re.sub(r'<!DOCTYPE[^>]*>\s*', '', svg_str)
            # 去掉注释
            svg_str = re.sub(r'<!--.*?-->\s*', '', svg_str, flags=re.DOTALL)

        _svg_cache[cache_key] = svg_str
        return svg_str
    except Exception:
        _svg_cache[cache_key] = None
        return None


# ============================================================
# 加载 HTML 到 QWebEngineView
# ============================================================

def load_formula_page(web_view, html_content):
    """将含 SVG 公式的 HTML 加载到 QWebEngineView。

    所有资源都内联在 HTML 中，无需网络访问。
    """
    web_view.setHtml(html_content)


# ============================================================
# 纯文本公式行 → LaTeX 字符串
# ============================================================

# 希腊字母映射
_GREEK_MAP = {
    'χ': '\\chi',
    'β': '\\beta',
    'θ': '\\theta',
    'π': '\\pi',
}

# 需要跳过（不转换）的关键词
_SKIP_KEYWORDS = [
    '✓', '✗', '通过', '未通过',
    '范围要求', '规范要求',
    '结果:', '结果：', '验证结果', '综合验证',
    '断面类型', '采用方法', '设计方法',
    '说明', '利用曼宁公式反算', '根据加大流量',
    '根据设计流量', '流量加大比例', '计算方法',
    '加大水深计算失败', '数据不可用',
    '设计方法:', '设计方法：',
    '[手动]', '设计直径',
    '计算直径', '管道总断面积',
]


def text_to_latex(line):
    """将纯文本公式行转换为 LaTeX 字符串。

    仅对"像公式"的行做转换（以变量名或 ``=`` 开头、含数学运算符等），
    其他行（标题、描述文字、验证结果等）返回 ``None``。

    使用 ``\\text{}`` 处理中文（兼容 KaTeX 字体渲染）。
    """
    s = line.strip()
    if not s:
        return None

    # 必须含 = 号或比较运算符
    _CMP_OPS = ('<', '>', '≤', '≥')
    has_eq = '=' in s
    has_cmp = any(op in s for op in _CMP_OPS)
    if not has_eq and not has_cmp:
        return None

    # 跳过分隔线
    if len(s) > 3 and all(c in '=- \t' for c in s):
        return None

    # 跳过章节标题
    if s.startswith('【'):
        return None

    # 跳过含特定关键词的行
    if any(kw in s for kw in _SKIP_KEYWORDS):
        return None

    # ------ 判断是否为公式行 ------
    # Case 1: 以拉丁字母/希腊符号开头（可能跟中文下标）
    latin_start = bool(re.match(r'^[A-Za-zα-ωΑ-Ωβχθπ]', s))
    # Case 2: 续行，以 = 或比较运算符开头
    continuation = s[0] in ('=', '<', '>', '≤', '≥') if s else False
    # Case 3: 短中文变量名（1-2字，如"误差"）
    cn_var = bool(re.match(r'^[\u4e00-\u9fff]{1,2}\s*=', s))
    # Case 4: 数字开头的比较表达式（如 0.1 < V < 100）
    num_cmp = bool(re.match(r'^\d', s)) and has_cmp
    # Case 5: 短中文变量名 + 比较运算符（如 净空面积 ≥ 15%）
    cn_cmp = bool(re.match(r'^[\u4e00-\u9fff]{1,4}\s*[<>≤≥]', s)) and has_cmp

    if not (latin_start or continuation or cn_var or num_cmp or cn_cmp):
        return None

    # 运算符前中文字符太多 → 描述文本而非公式
    if '=' in s:
        eq_idx = s.index('=')
    else:
        eq_idx = len(s)
        for _op in _CMP_OPS:
            _oi = s.find(_op)
            if _oi >= 0 and _oi < eq_idx:
                eq_idx = _oi
    pre = s[:eq_idx]
    cn_before = sum(1 for c in pre if '\u4e00' <= c <= '\u9fff')
    if cn_before > 4:
        return None

    # 全行中文字符太多也跳过
    total_cn = sum(1 for c in s if '\u4e00' <= c <= '\u9fff')
    if total_cn > 8:
        return None

    # ------ 开始转换为 LaTeX ------
    latex = s

    # 1. 百分号
    latex = re.sub(r'(\d+\.?\d*)\s*%', r'\1\\%', latex)

    # 2. 中文下角标（使用 \text{} 以支持 KaTeX CJK 渲染）
    #    (a) 希腊字母 + 中文: χ加大 → \chi_{\text{加大}}
    latex = re.sub(
        r'([χβθπ])_?([\u4e00-\u9fff]+)',
        lambda m: _GREEK_MAP.get(m.group(1), m.group(1))
                  + '_{\\text{' + m.group(2) + '}}',
        latex
    )
    #    (b) 多字母变量 + 中文: Fb加大, PA加大, Fb_设计, PA_加大
    latex = re.sub(
        r'(Fb|PA|FB)_?([\u4e00-\u9fff]+)',
        lambda m: '\\text{' + m.group(1) + '}_{\\text{' + m.group(2) + '}}',
        latex
    )
    #    (c) 单字母 + 中文: Q加大, h加大, V加大, h_设计, h_加大
    latex = re.sub(
        r'([A-Za-z])_?([\u4e00-\u9fff]+)',
        lambda m: m.group(1) + '_{\\text{' + m.group(2) + '}}',
        latex
    )

    # 3. 独立短中文变量名（行首）
    latex = re.sub(
        r'^([\u4e00-\u9fff]{1,2})\s*=',
        lambda m: '\\text{' + m.group(1) + '} =',
        latex
    )

    # 3b. 独立中文变量名 + 比较运算符（行首，如 净空面积 ≥）
    latex = re.sub(
        r'^([\u4e00-\u9fff]{1,4})\s*([<>≤≥])',
        lambda m: '\\text{' + m.group(1) + '} ' + m.group(2),
        latex
    )

    # 4. 剩余的独立希腊字母替换（未与中文下标配对的）
    latex = latex.replace('×', ' \\times ')
    latex = latex.replace('÷', ' \\div ')
    latex = latex.replace('≥', ' \\geq ')
    latex = latex.replace('≤', ' \\leq ')
    for g_char, g_cmd in _GREEK_MAP.items():
        latex = latex.replace(g_char, g_cmd + ' ')

    # 5. 根号: √(内容) → \sqrt{内容}
    latex = re.sub(r'√\(([^)]+)\)', r'\\sqrt{\1}', latex)
    latex = re.sub(r'√(\d+\.?\d*)', r'\\sqrt{\1}', latex)

    # 6. 指数: ^(x) → ^{x}
    latex = re.sub(r'\^\(([^)]+)\)', r'^{\1}', latex)
    latex = re.sub(r'\^（([^）]+)）', r'^{\1}', latex)
    latex = latex.replace('²', '^{2}')
    latex = latex.replace('³', '^{3}')

    # 7. 单位处理（在行末）
    latex = re.sub(r'\s+m\^\{3\}/s\s*$', r' \\; \\text{m}^{3}\\text{/s}', latex)
    latex = re.sub(r'\s+m/s\s*$', r' \\; \\text{m/s}', latex)
    latex = re.sub(r'\s+m\^\{2\}\s*$', r' \\; \\text{m}^{2}', latex)
    latex = re.sub(r'(?<=\d)\s+m\s*$', r' \\; \\text{m}', latex)
    latex = re.sub(r'\s+rad\b', r' \\; \\text{rad}', latex)

    # 8. 角度符号
    latex = latex.replace('°', '^{\\circ}')

    # 9. arccos / sin 等函数名
    latex = re.sub(r'\barccos\b', r'\\arccos', latex)
    latex = re.sub(r'\bsin\b', r'\\sin', latex)
    latex = re.sub(r'\bcos\b', r'\\cos', latex)
    latex = re.sub(r'\btan\b', r'\\tan', latex)

    # 10. 清理多余空格
    latex = re.sub(r'\s{2,}', ' ', latex)

    return latex


# ============================================================
# 块分组 & 渲染（卡片 + 横幅 + 徽章混搭排版）
# ============================================================

def _group_lines_into_blocks(lines):
    """将文本行分组为逻辑块（章节、步骤、文本）。"""
    blocks = []
    current_step = None
    text_buffer = []
    html_buffer = None          # 收集 {{HTML}}...{{/HTML}} 之间的原始 HTML

    def _flush_text():
        nonlocal text_buffer
        if text_buffer:
            blocks.append({'type': 'text', 'lines': list(text_buffer)})
            text_buffer.clear()

    def _flush_step():
        nonlocal current_step
        if current_step is not None:
            while current_step['lines'] and not current_step['lines'][-1].strip():
                current_step['lines'].pop()
            blocks.append(current_step)
            current_step = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if html_buffer is not None:
                continue
            if current_step is not None:
                current_step['lines'].append(line)
            continue

        # 原始 HTML 块结束标记
        if html_buffer is not None:
            if stripped == '{{/HTML}}':
                blocks.append({'type': 'raw_html', 'html': '\n'.join(html_buffer)})
                html_buffer = None
            else:
                html_buffer.append(stripped)
            continue

        # 分隔线 (=== / ---)
        if len(stripped) > 5 and all(c in '=- ' for c in stripped):
            _flush_text(); _flush_step()
            blocks.append({'type': 'separator', 'heavy': '=' in stripped})
            continue

        # 居中标题
        if '计算结果' in stripped and ':' not in stripped and '：' not in stripped:
            _flush_text(); _flush_step()
            blocks.append({'type': 'title', 'text': stripped})
            continue

        # 原始 HTML 块开始标记（{{HTML}}）
        if stripped.startswith('{{HTML}}'):
            _flush_text(); _flush_step()
            first = stripped[8:].strip()
            html_buffer = [first] if first else []
            continue

        # 章节横幅 【...】
        if stripped.startswith('【') and '】' in stripped:
            _flush_text(); _flush_step()
            blocks.append({'type': 'section', 'text': stripped})
            continue

        # 步骤标题 (数字. 文字)
        step_m = re.match(r'^(\d+)\.\s+(.+)', stripped)
        if step_m:
            _flush_text(); _flush_step()
            full_title = step_m.group(2)
            actual_title = full_title
            inline_content = None
            for sep in (':', '：'):
                idx = full_title.find(sep)
                if idx >= 0:
                    remainder = full_title[idx + 1:].strip()
                    if remainder:
                        actual_title = full_title[:idx + 1]
                        inline_content = remainder
                    break
            current_step = {
                'type': 'step',
                'number': step_m.group(1),
                'title': actual_title,
                'lines': [],
                'is_verify': any(k in stripped for k in ('验证', '复核', '校核')),
            }
            if inline_content:
                current_step['lines'].append('      ' + inline_content)
            continue

        if current_step is not None:
            current_step['lines'].append(line)
        else:
            text_buffer.append(line)

    _flush_text(); _flush_step()
    return blocks


def _calc_base_indent(lines):
    """计算行列表的最小缩进量。"""
    base = None
    for ln in lines:
        if ln.strip():
            ind = len(ln) - len(ln.lstrip())
            if base is None or ind < base:
                base = ind
    return base or 0


def _try_extract_formula(stripped, margin_style):
    """从复杂行中提取公式（处理 bullet 前缀、中文标签前缀等情况）。

    支持的模式:
      - 「- 设计流量超高: Fb_设计 = H - h_设计 = ...」→ bullet + 标签 + 公式
      - 「净空高度 Fb加大 = H - h加大 = ...」         → 中文前缀 + 拉丁变量公式
      - 「不淤流速 = 0.1 m/s」                          → 中文变量 = 数值
      - 「水力坡降 1/3000」                              → 中文标签 + 数值（无等号）
    """
    _CMP_OPS_SET = ('<', '>', '≤', '≥')
    has_eq = '=' in stripped
    has_cmp = any(op in stripped for op in _CMP_OPS_SET)
    if not has_eq and not has_cmp and not re.search(r'[\u4e00-\u9fff]{2,}\s+\d', stripped):
        return None

    clean = stripped
    bullet = ''

    # 去掉 bullet 标记
    bm = re.match(r'^[-•·]\s+', clean)
    if bm:
        bullet = '• '
        clean = clean[bm.end():]

    if has_eq or has_cmp:
        # 模式1: 「标签: 公式」（冒号分隔）
        for sep in (': ', '：'):
            idx = clean.find(sep)
            if idx >= 0:
                label = clean[:idx]
                formula = clean[idx + len(sep):].strip()
                if formula and ('=' in formula or any(op in formula for op in _CMP_OPS_SET)):
                    latex = text_to_latex(formula)
                    if latex:
                        # 将标签也纳入 SVG 渲染，避免 HTML 文字与 SVG 字号不一致
                        full_latex = '\\text{' + label + sep[0] + '} \\; ' + latex
                        svg = render_latex_svg(full_latex, fontsize=14)
                        if svg:
                            return (f'<div class="formula-line" style="{margin_style}">'
                                    f'{_e(bullet)}{svg}</div>')

        # 模式2: 「中文前缀 拉丁/希腊变量 = ...」（空格分隔）
        m = re.match(r'^([\u4e00-\u9fff]+\s+)([A-Za-z\u0391-\u03c9].+)', clean)
        if m:
            prefix = m.group(1).strip()
            formula = m.group(2)
            latex = text_to_latex(formula)
            if latex:
                # 将中文前缀纳入 SVG 渲染，保持字号一致
                full_latex = '\\text{' + prefix + '} \\; ' + latex
                svg = render_latex_svg(full_latex, fontsize=14)
                if svg:
                    return (f'<div class="formula-line" style="{margin_style}">'
                            f'{_e(bullet)}{svg}</div>')

        # 模式3: 「中文变量名 = 数值 [单位]」（无拉丁变量名，值以数字开头）
        m3 = re.match(r'^([\u4e00-\u9fff]{2,6})\s*(=\s*[\d\-.].+)', clean)
        if m3:
            cn_name = m3.group(1)
            value_part = m3.group(2)
            latex = text_to_latex(value_part)
            if latex:
                full_latex = '\\text{' + cn_name + '} ' + latex
                svg = render_latex_svg(full_latex, fontsize=14)
                if svg:
                    return (f'<div class="formula-line" style="{margin_style}">'
                            f'{_e(bullet)}{svg}</div>')

        # 模式3b: 「中文变量名 ≥/≤/>/< 数值」（比较表达式）
        if has_cmp:
            m3b = re.match(r'^([\u4e00-\u9fff]{2,6})\s*([<>≤≥].+)', clean)
            if m3b:
                cn_name = m3b.group(1)
                value_part = m3b.group(2)
                latex = text_to_latex(value_part)
                if latex:
                    full_latex = '\\text{' + cn_name + '} ' + latex
                    svg = render_latex_svg(full_latex, fontsize=14)
                    if svg:
                        return (f'<div class="formula-line" style="{margin_style}">'
                                f'{_e(bullet)}{svg}</div>')

    # 模式4: 「中文标签 数值/分数」（无等号，如 水力坡降 1/3000）
    m4 = re.match(r'^([\u4e00-\u9fff]{2,6})\s+(\d.+)', clean)
    if m4:
        cn_label = m4.group(1)
        value = m4.group(2)
        full_latex = '\\text{' + cn_label + '} \\; ' + value
        svg = render_latex_svg(full_latex, fontsize=14)
        if svg:
            return (f'<div class="formula-line" style="{margin_style}">'
                    f'{_e(bullet)}{svg}</div>')

    return None


def _render_content_line(stripped, margin_style, enable_formula=True):
    """渲染单行内容（公式 / 验证结果 / 小标题 / 普通文本）。"""
    # 验证结果行
    if any(k in stripped for k in ('结果', '验证', '复核')) and \
       any(k in stripped for k in ('通过', '✓', '✗')):
        cls = 'result-fail' if ('未通过' in stripped or '✗' in stripped) else 'result-pass'
        return f'<div class="{cls}" style="{margin_style}">{_e(stripped)}</div>'

    if enable_formula:
        # 公式行（SVG 矢量渲染）
        latex = text_to_latex(stripped)
        if latex:
            svg = render_latex_svg(latex, fontsize=14)
            if svg:
                return f'<div class="formula-line" style="{margin_style}">{svg}</div>'

        # 从复杂行中提取公式（bullet 前缀、中文标签前缀等）
        extracted = _try_extract_formula(stripped, margin_style)
        if extracted:
            return extracted

    # 小标题（以冒号结尾且不含等号）
    if (stripped.endswith(':') or stripped.endswith('：')) and '=' not in stripped:
        return f'<div class="info-subtitle" style="{margin_style}">{_e(stripped)}</div>'

    # 普通文本
    return f'<div class="content-line" style="{margin_style}">{_e(stripped)}</div>'


def _render_param_grid(step_blocks):
    """将输入参数步骤块渲染为两列紧凑网格。"""
    cells = []
    for block in step_blocks:
        num = block['number']
        title = block['title']
        lines = block['lines']
        value_parts = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            latex = text_to_latex(stripped)
            if latex:
                svg = render_latex_svg(latex, fontsize=13)
                if svg:
                    value_parts.append(f'<div style="margin:2px 0;">{svg}</div>')
                    continue
            value_parts.append(
                f'<div style="margin:2px 0;font-size:13px;color:#424242;">{_e(stripped)}</div>'
            )
        value_html = '\n'.join(value_parts)
        cells.append(
            f'<div class="param-cell">'
            f'<div class="step-badge" style="min-width:24px;height:24px;'
            f'border-radius:12px;font-size:11px;margin-right:10px;margin-top:2px;">'
            f'{_e(num)}</div>'
            f'<div class="step-body">'
            f'<div class="step-title">{_e(title)}</div>'
            f'{value_html}'
            f'</div></div>'
        )
    return '<div class="param-grid">\n' + '\n'.join(cells) + '\n</div>'


def _render_step_card(block):
    """渲染带编号徽章的步骤卡片。"""
    num = block['number']
    title = block['title']
    lines = block['lines']
    all_text = ' '.join(l.strip() for l in lines)
    has_fail = '未通过' in all_text or '✗' in all_text
    has_pass = '通过' in all_text or '✓' in all_text
    card_cls = 'step-card'
    if block['is_verify']:
        if has_fail:
            card_cls += ' verify-fail'
        elif has_pass:
            card_cls += ' verify-pass'

    base_indent = _calc_base_indent(lines)
    parts = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        rel = max(0, len(line) - len(line.lstrip()) - base_indent)
        ms = f'margin-left:{rel * 7}px;' if rel > 0 else ''
        parts.append(_render_content_line(stripped, ms, enable_formula=True))

    return (
        f'<div class="{card_cls}">'
        f'<div class="step-badge">{_e(num)}</div>'
        f'<div class="step-body">'
        f'<div class="step-title">{_e(title)}</div>'
        + '\n'.join(parts)
        + '</div></div>'
    )


def _render_text_block(lines):
    """渲染无编号的文本块（信息面板或结果横幅）。"""
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return ''
    all_text = ' '.join(l.strip() for l in non_empty)
    # 综合验证结果 → 结果横幅
    if '综合验证结果' in all_text:
        cls = 'fail' if ('未通过' in all_text or '✗' in all_text) else 'pass'
        return f'<div class="result-banner {cls}">{_e(all_text)}</div>'

    base_indent = _calc_base_indent(non_empty)
    parts = []
    for line in non_empty:
        stripped = line.strip()
        rel = max(0, len(line) - len(line.lstrip()) - base_indent)
        ms = f'margin-left:{rel * 7}px;' if rel > 0 else ''
        parts.append(_render_content_line(stripped, ms, enable_formula=True))
    return '<div class="info-panel">\n' + '\n'.join(parts) + '\n</div>'


def _render_block(block):
    """将逻辑块渲染为 HTML。"""
    t = block['type']
    if t == 'separator':
        bw = '2px' if block['heavy'] else '1px'
        return f'<hr style="border:none;border-top:{bw} solid #ccc;margin:8px 0;"/>'
    if t == 'title':
        return f'<div class="main-title">{_e(block["text"])}</div>'
    if t == 'section':
        return f'<div class="section-banner">{_e(block["text"])}</div>'
    if t == 'step':
        return _render_step_card(block)
    if t == 'raw_html':
        return block['html']
    if t == 'text':
        return _render_text_block(block['lines'])
    return ''


def plain_text_to_formula_body(plain_text):
    """将纯文本计算结果转换为 HTML body 内容（不含 <html>/<head> 标签）。"""
    lines = plain_text.split('\n')
    blocks = _group_lines_into_blocks(lines)
    html_parts = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b['type'] == 'section' and '输入参数' in b['text']:
            html_parts.append(_render_block(b))
            i += 1
            param_steps = []
            while i < len(blocks) and blocks[i]['type'] == 'step':
                param_steps.append(blocks[i])
                i += 1
            if param_steps:
                html_parts.append(_render_param_grid(param_steps))
            continue
        html_parts.append(_render_block(b))
        i += 1
    return '\n'.join(html_parts)


def wrap_with_katex(body_html, extra_css="", extra_head=""):
    """将任意 body HTML 包装为完整 HTML 页面。"""
    css = _BASE_CSS + extra_css
    return (
        f'<html><head><meta charset="utf-8">'
        f'<style>{css}</style>{extra_head}</head>'
        f'<body>{body_html}</body></html>'
    )


def plain_text_to_formula_html(plain_text, extra_css=""):
    """将纯文本计算结果转换为含 SVG 公式的完整 HTML。"""
    body = plain_text_to_formula_body(plain_text)
    return wrap_with_katex(body, extra_css=extra_css)


def make_plain_html(text):
    """将纯文本包装为 Fluent 风格 HTML（用于错误信息等）。"""
    lines = text.split('\n')
    parts = []
    for line in lines:
        s = line.strip()
        if not s:
            parts.append('<div style="height:6px;"></div>')
            continue
        if len(s) > 5 and all(c in '=- ' for c in s):
            parts.append('<hr style="border:none;border-top:1px solid #E0E0E0;margin:8px 0;">')
            continue
        indent = len(line) - len(line.lstrip())
        ml = f'padding-left:{indent * 8}px;' if indent > 0 else ''
        parts.append(f'<div style="{ml}margin:2px 0;">{_e(s)}</div>')
    body = '\n'.join(parts)
    css = """
    * { box-sizing: border-box; }
    body {
        font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
        font-size: 14px; color: #242424; line-height: 1.7;
        background: #F5F5F5; padding: 20px; margin: 0;
    }
    .plain-card {
        background: #FFFFFF; border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.04), 0 0 2px rgba(0,0,0,0.06);
        padding: 24px 28px;
    }
    """
    return (f'<html><head><meta charset="utf-8"><style>{css}</style></head>'
            f'<body><div class="plain-card">{body}</div></body></html>')


# ============================================================
# Fluent Design 帮助页面
# ============================================================

_FLUENT_HELP_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
    font-size: 14px; color: #242424; line-height: 1.7;
    background: #F5F5F5; padding: 20px; margin: 0;
}
.help-card {
    background: #FFFFFF; border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.04), 0 0 2px rgba(0,0,0,0.06);
    padding: 28px 32px;
}
.help-header { margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid #F0F0F0; }
.help-title { font-size: 22px; font-weight: 700; color: #1976D2; margin-bottom: 6px; }
.help-subtitle { font-size: 13px; color: #555555; }
.section-head {
    font-size: 15px; font-weight: 600; color: #1976D2;
    margin: 24px 0 10px 0; padding-left: 14px; position: relative;
}
.section-head::before {
    content: ''; position: absolute; left: 0; top: 2px;
    width: 3px; height: 100%; background: #1976D2; border-radius: 2px;
}
.text-line { margin: 6px 0; color: #424242; }
.formula-block {
    background: linear-gradient(135deg, #F8F9FE 0%, #F0F4FF 100%);
    border: 1px solid #E3ECF9; padding: 14px 20px; margin: 10px 0;
    border-radius: 8px; overflow-x: auto;
}
.formula-label {
    font-size: 12px; color: #1976D2; font-weight: 600;
    margin-bottom: 6px; letter-spacing: 0.3px;
}
.formula-block svg { vertical-align: middle; }
.formula-text {
    font-family: 'Cambria Math', 'Times New Roman', serif;
    font-size: 15px; color: #1a1a1a;
}
.num-list { margin: 8px 0; }
.num-item { display: flex; align-items: flex-start; padding: 6px 0; }
.num-badge {
    background: #1976D2; color: #fff;
    min-width: 26px; height: 26px; border-radius: 13px;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 12px; font-weight: 600;
    margin-right: 12px; flex-shrink: 0; margin-top: 1px;
}
.num-content { flex: 1; }
.num-main { color: #242424; }
.num-sub { font-size: 13px; color: #424242; margin-top: 3px; }
.bullet-list { margin: 6px 0 6px 4px; padding-left: 20px; }
.bullet-list li {
    padding: 3px 0; color: #424242;
    list-style: none; position: relative;
}
.bullet-list li::before {
    content: ''; position: absolute; left: -16px; top: 11px;
    width: 6px; height: 6px; background: #1976D2; border-radius: 50%;
}
.hint-block {
    background: #FFF8E1; border: 1px solid #FFE082;
    padding: 12px 16px; margin: 12px 0; border-radius: 8px;
    font-size: 13px; color: #795548;
}
.fluent-table {
    width: 100%; border-collapse: separate; border-spacing: 0;
    margin: 10px 0; border-radius: 8px; overflow: hidden;
    border: 1px solid #E3ECF9;
}
.fluent-table th {
    background: linear-gradient(135deg, #1976D2, #1E88E5);
    color: #fff; font-weight: 600; font-size: 13px;
    padding: 10px 16px; text-align: center;
}
.fluent-table td {
    padding: 9px 16px; font-size: 13px; color: #424242;
    text-align: center; border-top: 1px solid #F0F0F0;
}
.fluent-table tr:nth-child(even) td { background: #F8F9FE; }
.fluent-table tr:nth-child(odd) td { background: #FFFFFF; }
.fluent-table tr:hover td { background: #E3F2FD; }
"""


class HelpPageBuilder:
    """Fluent Design 风格帮助页面构建器。

    用法::

        h = HelpPageBuilder("明渠水力计算", "请输入参数后点击计算")
        h.section("曼宁公式")
        h.formula("Q = (1/n) × A × R^(2/3) × i^(1/2)", "流量公式")
        h.numbered_list(["矩形断面", "梯形断面", "圆形明渠"])
        html = h.build()
    """

    def __init__(self, title, subtitle=""):
        self._title = title
        self._subtitle = subtitle
        self._parts = []

    def section(self, title):
        self._parts.append(('section', title))
        return self

    def text(self, content):
        self._parts.append(('text', content))
        return self

    def formula(self, text, label=None):
        self._parts.append(('formula', text, label))
        return self

    def numbered_list(self, items):
        """items: list of str 或 (主文本, 副文本) 元组"""
        self._parts.append(('numlist', items))
        return self

    def bullet_list(self, items):
        self._parts.append(('bullets', items))
        return self

    def hint(self, text):
        self._parts.append(('hint', text))
        return self

    def table(self, headers, rows):
        """headers: list of str; rows: list of list/tuple of str"""
        self._parts.append(('table', headers, rows))
        return self

    def divider(self):
        self._parts.append(('divider',))
        return self

    # ---- 渲染 ----

    def _render_formula(self, text, label):
        latex = text_to_latex(text)
        svg = None
        if latex:
            svg = render_latex_svg(latex, fontsize=15)
        html = '<div class="formula-block">'
        if label:
            html += f'<div class="formula-label">{_e(label)}</div>'
        if svg:
            html += svg
        else:
            html += f'<span class="formula-text">{_e(text)}</span>'
        html += '</div>'
        return html

    def _render_numlist(self, items):
        html = '<div class="num-list">'
        for i, item in enumerate(items, 1):
            if isinstance(item, tuple):
                main, sub = item[0], item[1]
                html += (f'<div class="num-item">'
                         f'<span class="num-badge">{i}</span>'
                         f'<div class="num-content">'
                         f'<div class="num-main">{_e(main)}</div>'
                         f'<div class="num-sub">{_e(sub)}</div>'
                         f'</div></div>')
            else:
                html += (f'<div class="num-item">'
                         f'<span class="num-badge">{i}</span>'
                         f'<div class="num-content">'
                         f'<div class="num-main">{_e(item)}</div>'
                         f'</div></div>')
        html += '</div>'
        return html

    def _render_table(self, headers, rows):
        html = '<table class="fluent-table"><thead><tr>'
        for h in headers:
            html += f'<th>{_e(h)}</th>'
        html += '</tr></thead><tbody>'
        for row in rows:
            html += '<tr>'
            for cell in row:
                html += f'<td>{_e(cell)}</td>'
            html += '</tr>'
        html += '</tbody></table>'
        return html

    def _render_bullets(self, items):
        html = '<ul class="bullet-list">'
        for item in items:
            html += f'<li>{_e(item)}</li>'
        html += '</ul>'
        return html

    def build(self):
        body = ['<div class="help-card">']
        body.append('<div class="help-header">')
        body.append(f'<div class="help-title">{_e(self._title)}</div>')
        if self._subtitle:
            body.append(f'<div class="help-subtitle">{_e(self._subtitle)}</div>')
        body.append('</div>')

        for part in self._parts:
            ptype = part[0]
            if ptype == 'section':
                body.append(f'<div class="section-head">{_e(part[1])}</div>')
            elif ptype == 'text':
                body.append(f'<div class="text-line">{_e(part[1])}</div>')
            elif ptype == 'formula':
                label = part[2] if len(part) > 2 else None
                body.append(self._render_formula(part[1], label))
            elif ptype == 'numlist':
                body.append(self._render_numlist(part[1]))
            elif ptype == 'bullets':
                body.append(self._render_bullets(part[1]))
            elif ptype == 'table':
                body.append(self._render_table(part[1], part[2]))
            elif ptype == 'hint':
                body.append(f'<div class="hint-block">{_e(part[1])}</div>')
            elif ptype == 'divider':
                body.append('<hr style="border:none;border-top:1px solid #F0F0F0;margin:20px 0;">')

        body.append('</div>')
        content = '\n'.join(body)
        return (f'<html><head><meta charset="utf-8">'
                f'<style>{_FLUENT_HELP_CSS}</style></head>'
                f'<body>{content}</body></html>')


def clear_cache():
    """清空 SVG 渲染缓存。"""
    _svg_cache.clear()
