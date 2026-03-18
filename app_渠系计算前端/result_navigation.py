# -*- coding: utf-8 -*-
"""Shared multi-case result navigation helpers."""

from __future__ import annotations

import html as html_mod
import re


def _e(value) -> str:
    return html_mod.escape(str(value))


def make_case_result_anchor(panel_key: str, case_idx: int) -> str:
    """Build a stable HTML anchor id for a case result block."""
    safe_key = re.sub(r"[^a-z0-9_-]+", "-", str(panel_key or "").lower()).strip("-") or "panel"
    safe_idx = max(0, int(case_idx))
    return f"case-result-{safe_key}-{safe_idx}"


def build_result_navigation_head() -> str:
    """Return shared CSS/JS used by multi-case result pages."""
    return """
<style>
.codex-case-nav {
    display:flex;
    gap:8px;
    align-items:center;
    flex-wrap:wrap;
    margin:0 0 16px 0;
    padding:10px 16px;
    background:#FFFFFF;
    border:1px solid #E0E7EF;
    border-radius:12px;
    box-shadow:0 1px 4px rgba(0,0,0,0.06);
}
.codex-case-nav__title {
    font-size:12px;
    color:#6B7A90;
    font-weight:600;
    margin-right:4px;
}
.codex-case-nav__link {
    display:inline-flex;
    align-items:center;
    gap:6px;
    padding:6px 14px;
    border:1.5px solid #1565C0;
    border-radius:20px;
    background:#FFFFFF;
    color:#1565C0;
    font-size:13px;
    font-weight:700;
    cursor:pointer;
    text-decoration:none;
    transition:background 0.15s ease, transform 0.15s ease;
}
.codex-case-nav__link:hover {
    background:#F1F7FF;
    transform:translateY(-1px);
}
.codex-case-nav__badge {
    font-size:11px;
    font-weight:600;
    padding:1px 8px;
    border-radius:9px;
}
.codex-case-block {
    position:relative;
    margin:0 0 22px 0;
    padding:12px 14px 10px 14px;
    border-radius:14px;
    background:linear-gradient(180deg,#FFFFFF,#FBFDFF);
    border:1px solid #DFE7F1;
    box-shadow:0 2px 6px rgba(0,0,0,0.04);
    scroll-margin-top:16px;
}
.codex-case-block--error {
    border-color:#F1B7B7;
    background:linear-gradient(180deg,#FFFFFF,#FFF7F7);
}
.codex-case-block__header {
    display:flex;
    align-items:center;
    gap:10px;
    flex-wrap:wrap;
    margin:0 0 12px 0;
    padding:10px 14px;
    border-radius:12px;
    background:linear-gradient(135deg,#EAF3FF,#F4F8FF);
    border-left:4px solid #1565C0;
}
.codex-case-block--error .codex-case-block__header {
    background:linear-gradient(135deg,#FFF0F0,#FFF8F8);
    border-left-color:#C62828;
}
.codex-case-block__title {
    font-size:15px;
    font-weight:800;
    color:#1565C0;
}
.codex-case-block--error .codex-case-block__title {
    color:#C62828;
}
.codex-case-block__subtitle {
    font-size:13px;
    font-weight:500;
    color:#4E5D71;
}
.codex-case-block--flash {
    animation:codex-case-flash 1.6s ease-out 1;
}
@keyframes codex-case-flash {
    0% {
        box-shadow:0 0 0 0 rgba(21,101,192,0.38);
        background:linear-gradient(180deg,#FFFDF0,#FFFFFF);
    }
    35% {
        box-shadow:0 0 0 4px rgba(21,101,192,0.16);
        background:linear-gradient(180deg,#FFF6C9,#FFFFFF);
    }
    100% {
        box-shadow:0 2px 6px rgba(0,0,0,0.04);
        background:linear-gradient(180deg,#FFFFFF,#FBFDFF);
    }
}
</style>
<script>
(function() {
    if (window.codexJumpToCase) {
        return;
    }
    window.codexFlashCase = function(anchorId) {
        var block = document.getElementById(anchorId);
        if (!block) {
            return false;
        }
        block.classList.remove('codex-case-block--flash');
        void block.offsetWidth;
        block.classList.add('codex-case-block--flash');
        window.setTimeout(function() {
            block.classList.remove('codex-case-block--flash');
        }, 1700);
        return true;
    };
    window.codexJumpToCase = function(anchorId) {
        var block = document.getElementById(anchorId);
        if (!block) {
            return false;
        }
        try {
            block.scrollIntoView({behavior: 'smooth', block: 'start'});
        } catch (error) {
            block.scrollIntoView(true);
        }
        window.codexFlashCase(anchorId);
        return false;
    };
})();
</script>
"""


def build_result_nav_bar(items, title: str = "工况快捷导航") -> str:
    """Build a shared top navigation bar for multi-case result pages."""
    if not items or len(items) <= 1:
        return ""

    parts = ['<div class="codex-case-nav">', f'<span class="codex-case-nav__title">{_e(title)}</span>']
    for item in items:
        anchor_id = item["anchor_id"]
        label = item["label"]
        summary = str(item.get("summary", "") or "").strip()
        is_error = bool(item.get("is_error", False))
        accent = "#C62828" if is_error else "#1565C0"
        badge_bg = "#FDECEC" if is_error else "#EAF3FF"
        badge_fg = "#C62828" if is_error else "#1565C0"
        parts.append(
            f'<a class="codex-case-nav__link" href="#{_e(anchor_id)}" '
            f'onclick="return window.codexJumpToCase(\'{_e(anchor_id)}\');" '
            f'style="border-color:{accent};color:{accent};">'
            f'<span>{_e(label)}</span>'
        )
        if summary:
            parts.append(
                f'<span class="codex-case-nav__badge" style="background:{badge_bg};color:{badge_fg};">'
                f'{_e(summary)}</span>'
            )
        parts.append("</a>")
    parts.append("</div>")
    return "".join(parts)


def wrap_case_result_block(
    panel_key: str,
    case_idx: int,
    title_text: str,
    body_html: str,
    *,
    subtitle: str = "",
    is_error: bool = False,
) -> str:
    """Wrap case content in a shared anchor-aware result card."""
    anchor_id = make_case_result_anchor(panel_key, case_idx)
    block_cls = "codex-case-block codex-case-block--error" if is_error else "codex-case-block"
    subtitle_html = (
        f'<span class="codex-case-block__subtitle">{_e(subtitle)}</span>' if subtitle else ""
    )
    return (
        f'<div id="{_e(anchor_id)}" class="{block_cls}" data-case-index="{int(case_idx)}">'
        f'<a name="{_e(anchor_id)}"></a>'
        f'<div class="codex-case-block__header">'
        f'<span class="codex-case-block__title">{_e(title_text)}</span>'
        f"{subtitle_html}"
        f"</div>"
        f"{body_html}"
        f"</div>"
    )
