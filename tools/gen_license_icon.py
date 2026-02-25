# -*- coding: utf-8 -*-
"""
生成授权管理工具应用图标（.ico）

设计：在 512px 高分辨率绘制 → LANCZOS 缩放到各尺寸
  - 深蓝色圆角方形背景（与主应用色系统一，稍偏深以区分）
  - 白色盾牌轮廓（代表安全/授权）
  - 盾牌内金色钥匙图案（代表许可/密钥）
  - 底部白色"授"字
"""

from PIL import Image, ImageDraw, ImageFont
import os, math


BASE = 512  # 基准绘制尺寸


def create_base_icon():
    """在 512x512 高分辨率绘制基础图标"""
    s = BASE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")

    margin = int(s * 0.03)
    r = int(s * 0.17)

    # ── 1. 圆角方形背景（深蓝色，与主应用区分） ──
    draw.rounded_rectangle(
        [margin, margin, s - margin, s - margin],
        radius=r, fill=(20, 80, 180, 255)
    )

    # ── 2. 盾牌轮廓 ──
    cx = s // 2
    shield_top = int(s * 0.13)
    shield_w = int(s * 0.50)  # 盾牌宽度
    shield_h = int(s * 0.52)  # 盾牌高度
    shield_bottom = shield_top + shield_h

    # 盾牌形状：上半部矩形圆角，下半部收窄为尖角
    # 用多边形近似
    hw = shield_w // 2
    mid_y = shield_top + int(shield_h * 0.45)  # 中间分界线

    # 盾牌多边形点
    n_curve = 20  # 圆弧细分
    corner_r = int(s * 0.06)  # 盾牌顶部圆角

    shield_pts = []
    # 左上圆角
    for i in range(n_curve + 1):
        angle = math.pi + (math.pi / 2) * i / n_curve
        x = cx - hw + corner_r + corner_r * math.cos(angle)
        y = shield_top + corner_r + corner_r * math.sin(angle)
        shield_pts.append((x, y))
    # 右上圆角
    for i in range(n_curve + 1):
        angle = -math.pi / 2 + (math.pi / 2) * i / n_curve
        x = cx + hw - corner_r + corner_r * math.cos(angle)
        y = shield_top + corner_r + corner_r * math.sin(angle)
        shield_pts.append((x, y))
    # 右侧到底部尖角
    shield_pts.append((cx + hw, mid_y))
    # 底部尖角（贝塞尔近似用多段）
    n_bot = 16
    for i in range(1, n_bot + 1):
        t = i / n_bot
        # 从右侧中点到底部尖角的曲线
        x = cx + hw * (1 - t) * (1 - t * 0.3)
        y = mid_y + (shield_bottom - mid_y) * t
        shield_pts.append((x, y))
    # 从底部尖角到左侧
    for i in range(1, n_bot + 1):
        t = i / n_bot
        x = cx - hw * (1 - (1 - t)) * (1 - (1 - t) * 0.3)
        y = shield_bottom - (shield_bottom - mid_y) * t
        shield_pts.append((x, y))
    shield_pts.append((cx - hw, mid_y))

    # 填充盾牌（半透明白色底）
    draw.polygon(shield_pts, fill=(255, 255, 255, 40))
    # 盾牌描边
    lw = int(s * 0.025)
    # 用 line 画描边
    for i in range(len(shield_pts) - 1):
        draw.line([shield_pts[i], shield_pts[i + 1]], fill="white", width=lw)
    draw.line([shield_pts[-1], shield_pts[0]], fill="white", width=lw)

    # ── 3. 盾牌内钥匙图案 ──
    key_cx = cx
    key_cy = shield_top + int(shield_h * 0.38)

    # 钥匙头部（圆环）
    head_r = int(s * 0.075)
    head_inner_r = int(s * 0.04)
    # 外圆
    draw.ellipse(
        [key_cx - head_r, key_cy - head_r, key_cx + head_r, key_cy + head_r],
        fill=(255, 210, 60, 255), outline=(240, 190, 30, 255), width=int(s * 0.008)
    )
    # 内圆（镂空）
    draw.ellipse(
        [key_cx - head_inner_r, key_cy - head_inner_r,
         key_cx + head_inner_r, key_cy + head_inner_r],
        fill=(20, 80, 180, 255)
    )

    # 钥匙杆身（向下）
    shaft_w = int(s * 0.03)
    shaft_top = key_cy + head_r - int(s * 0.01)
    shaft_bottom = key_cy + int(s * 0.20)
    draw.rounded_rectangle(
        [key_cx - shaft_w // 2, shaft_top, key_cx + shaft_w // 2, shaft_bottom],
        radius=int(s * 0.005), fill=(255, 210, 60, 255)
    )

    # 钥匙齿（右侧两个小矩形）
    tooth_w = int(s * 0.04)
    tooth_h = int(s * 0.022)
    for i, ty in enumerate([shaft_bottom - int(s * 0.06), shaft_bottom - int(s * 0.025)]):
        tw = tooth_w if i == 0 else int(tooth_w * 0.7)
        draw.rectangle(
            [key_cx + shaft_w // 2, ty, key_cx + shaft_w // 2 + tw, ty + tooth_h],
            fill=(255, 210, 60, 255)
        )

    # ── 4. "授" 字 ──
    text = "授"
    text_size = int(s * 0.22)
    font = None
    for font_path in ["C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc",
                       "msyhbd.ttc", "msyh.ttc"]:
        try:
            font = ImageFont.truetype(font_path, text_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (s - tw) // 2
    ty = int(s * 0.68)
    draw.text((tx, ty), text, fill="white", font=font)

    return img


def main():
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)))
    icon_path = os.path.join(output_dir, "license_icon.ico")

    # 在 512px 绘制一次，然后 LANCZOS 高质量缩放到各尺寸
    base = create_base_icon()

    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = []
    for sz in sizes:
        resized = base.resize((sz, sz), Image.LANCZOS)
        images.append(resized)

    # 保存为 .ico（多尺寸嵌入）
    images[-1].save(icon_path, format="ICO",
                    sizes=[(sz, sz) for sz in sizes],
                    append_images=images[:-1])
    print(f"图标已生成: {icon_path}")

    # 预览 PNG
    preview_path = os.path.join(output_dir, "license_icon_preview.png")
    base.resize((256, 256), Image.LANCZOS).save(preview_path, format="PNG")
    print(f"预览已生成: {preview_path}")


if __name__ == "__main__":
    main()
