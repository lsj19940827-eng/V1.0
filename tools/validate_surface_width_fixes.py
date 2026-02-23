# -*- coding: utf-8 -*-
"""
水面宽度修复项全面验证脚本
验证对象：
  1. 马蹄形Ⅰ/Ⅱ型  — _horseshoe_std_surface_width
  2. U形渡槽        — U形水面宽（圆弧段/矩形段）
  3. 圆拱直墙型     — _arch_tunnel_surface_width
  4. 倒角矩形渡槽   — _rect_chamfer_area / _rect_chamfer_perimeter / _rect_chamfer_surface_width
"""
import sys, os, math

# 路径设置
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, '推求水面线'))
sys.path.insert(0, os.path.join(ROOT, '渠系建筑物断面计算'))

# ──────────────────────────────────────────────────────────
# 颜色输出工具
# ──────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

passed = 0
failed = 0

def check(desc, got, expected, tol=1e-6):
    global passed, failed
    err = abs(got - expected)
    ok = err <= tol
    status = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
    mark = "✓" if ok else "✗"
    print(f"  {mark} {status}  {desc}")
    if not ok:
        print(f"       got={got:.8f}  expected={expected:.8f}  diff={err:.2e}")
        failed += 1
    else:
        passed += 1

def section(title):
    print(f"\n{BOLD}{YELLOW}{'='*60}{RESET}")
    print(f"{BOLD}{YELLOW}  {title}{RESET}")
    print(f"{BOLD}{YELLOW}{'='*60}{RESET}")


# ──────────────────────────────────────────────────────────
# 导入被测模块
# ──────────────────────────────────────────────────────────
try:
    from core.hydraulic_calc import HydraulicCalculator
    from config.constants import DEFAULT_ROUGHNESS
    from models.data_models import ProjectSettings
    settings = ProjectSettings()
    calc = HydraulicCalculator(settings)
    CALC_OK = True
except Exception as e:
    print(f"{RED}[ERROR] 无法导入 HydraulicCalculator: {e}{RESET}")
    CALC_OK = False

try:
    from 隧洞设计 import calculate_horseshoe_std_elements
    HORSESHOE_OK = True
except Exception as e:
    print(f"{RED}[ERROR] 无法导入 隧洞设计: {e}{RESET}")
    HORSESHOE_OK = False

try:
    from 渡槽设计 import calculate_rect_hydro_elements_with_chamfer
    CHAMFER_OK = True
except Exception as e:
    print(f"{RED}[ERROR] 无法导入 渡槽设计: {e}{RESET}")
    CHAMFER_OK = False


# ══════════════════════════════════════════════════════════
# 1. 马蹄形水面宽度
# ══════════════════════════════════════════════════════════
section("1. 马蹄形标准断面水面宽度")

if CALC_OK and HORSESHOE_OK:
    for stype, label in [(1, "Ⅰ型"), (2, "Ⅱ型")]:
        r = 1.5
        # 参数
        t_map = {1: 3.0, 2: 2.0}
        theta_map = {1: 0.294515, 2: 0.424031}
        t = t_map[stype]
        theta = theta_map[stype]
        R_arch = t * r
        e = R_arch * (1 - math.cos(theta))

        test_hs = [
            ("底拱下界 h≈0.001r",   0.001 * r),
            ("底拱段 h=0.5e",       0.5 * e),
            ("底拱上界 h=e",        e),
            ("侧拱段 h=0.5*(e+r)",  0.5 * (e + r)),
            ("侧拱上界 h=r",        r),
            ("顶拱段 h=1.2r",       1.2 * r),
            ("顶拱中点 h=1.5r",     1.5 * r),
            ("顶拱上界 h≈2r",       2 * r * 0.9999),
        ]
        print(f"\n  马蹄形{label}  r={r}m  e={e:.4f}m")
        for desc, h in test_hs:
            _, B_ref, _, ok = calculate_horseshoe_std_elements(stype, r, h)
            if not ok:
                print(f"  - 参考函数失败: {desc}")
                continue
            B_got = calc._horseshoe_std_surface_width(stype, r, h)
            check(f"马蹄形{label} {desc}", B_got, B_ref)
else:
    print(f"  {YELLOW}跳过（模块加载失败）{RESET}")


# ══════════════════════════════════════════════════════════
# 2. U形渡槽水面宽度
# ══════════════════════════════════════════════════════════
section("2. U形渡槽水面宽度")

if CALC_OK:
    R = 1.2
    print(f"\n  U形渡槽  R={R}m")
    test_u = [
        ("圆弧底 h=0.1R",   0.1 * R),
        ("圆弧底 h=0.5R",   0.5 * R),
        ("圆弧底 h=R（半圆顶）", R),
        ("矩形段 h=1.2R",   1.2 * R),
        ("矩形段 h=2R",     2.0 * R),
    ]
    for desc, h in test_u:
        if h <= R:
            # 弦长公式
            B_expected = 2 * math.sqrt(max(0.0, R * R - (R - h) ** 2))
        else:
            B_expected = 2 * R

        # 用 get_water_surface_width 通过虚拟节点测试
        from models.data_models import ChannelNode
        from models.enums import StructureType
        node = ChannelNode()
        node.structure_type = StructureType.AQUEDUCT_U
        node.water_depth = h
        node.section_params = {'R_circle': R}
        B_got = calc.get_water_surface_width(node)
        check(f"U形渡槽 {desc}", B_got, B_expected)
else:
    print(f"  {YELLOW}跳过（模块加载失败）{RESET}")


# ══════════════════════════════════════════════════════════
# 3. 圆拱直墙型水面宽度
# ══════════════════════════════════════════════════════════
section("3. 圆拱直墙型水面宽度")

if CALC_OK:
    B0 = 3.0
    theta_deg = 120.0
    H_total = 4.0
    theta_rad = math.radians(theta_deg)
    sin_half = math.sin(theta_rad / 2)
    R_arch = (B0 / 2) / sin_half
    H_arch = R_arch * (1 - math.cos(theta_rad / 2))
    H_straight = max(0.0, H_total - H_arch)
    cos_half = math.cos(theta_rad / 2)

    print(f"\n  圆拱直墙型  B={B0}m  θ={theta_deg}°  H_total={H_total}m")
    print(f"  R_arch={R_arch:.4f}  H_arch={H_arch:.4f}  H_straight={H_straight:.4f}")

    test_arch = [
        ("矩形段下界 h=0.1",        0.1),
        ("矩形段中 h=H_straight/2", H_straight / 2),
        ("矩形段顶 h=H_straight",   H_straight),
        ("拱部 h=H_straight+H_arch/3", H_straight + H_arch / 3),
        ("拱部 h=H_straight+H_arch*2/3", H_straight + H_arch * 2 / 3),
        ("拱顶 h≈H_total",          H_total * 0.999),
    ]
    for desc, h in test_arch:
        h = min(h, H_total)
        if h <= H_straight:
            B_expected = B0
        else:
            delta_h = h - H_straight
            val = R_arch ** 2 - (delta_h + R_arch * cos_half) ** 2
            B_expected = 2 * math.sqrt(max(0.0, val))

        from models.data_models import ChannelNode
        from models.enums import StructureType
        node = ChannelNode()
        node.structure_type = StructureType.TUNNEL_ARCH
        node.water_depth = h
        node.section_params = {'B': B0, 'H_total': H_total, 'theta_deg': theta_deg}
        B_got = calc.get_water_surface_width(node)
        check(f"圆拱直墙型 {desc}", B_got, B_expected)
else:
    print(f"  {YELLOW}跳过（模块加载失败）{RESET}")


# ══════════════════════════════════════════════════════════
# 4. 倒角矩形渡槽 — 面积 / 湿周 / 水面宽
# ══════════════════════════════════════════════════════════
section("4. 倒角矩形渡槽 面积 / 湿周 / 水面宽")

if CALC_OK and CHAMFER_OK:
    b_slot = 3.0
    ca = 45.0   # 倒角角度 (°)
    cl = 0.15   # 倒角底边长 (m)
    ch = cl * math.tan(math.radians(ca))  # 倒角高度

    print(f"\n  渡槽-矩形  B={b_slot}m  倒角{ca}°  底边{cl}m  倒角高={ch:.4f}m")

    # 测试点覆盖：倒角区内、临界处、倒角区上
    test_ch = [
        ("倒角区内 h=0.3*ch",      0.3 * ch),
        ("倒角区内 h=0.7*ch",      0.7 * ch),
        ("倒角临界 h=ch",           ch),
        ("矩形区 h=ch+0.2",         ch + 0.2),
        ("矩形区 h=1.0",            1.0),
        ("矩形区 h=2.0",            2.0),
    ]

    from models.data_models import ChannelNode
    from models.enums import StructureType

    for desc, h in test_ch:
        # 参考值来自原始渡槽设计函数
        A_ref, P_ref = calculate_rect_hydro_elements_with_chamfer(h, b_slot, ca, cl)

        # 水面宽参考值（推导）
        if h >= ch:
            BW_ref = b_slot
        else:
            BW_ref = b_slot - 2 * cl * (1 - h / ch)

        # 构造虚拟节点
        node = ChannelNode()
        node.structure_type = StructureType.AQUEDUCT_RECT
        node.water_depth = h
        node.section_params = {'B': b_slot, 'chamfer_angle': ca, 'chamfer_length': cl}

        A_got  = calc.get_cross_section_area(node)
        P_got  = calc.get_wetted_perimeter(node)
        BW_got = calc.get_water_surface_width(node)

        check(f"倒角渡槽 面积 {desc}",   A_got,  A_ref,  tol=1e-8)
        check(f"倒角渡槽 湿周 {desc}",   P_got,  P_ref,  tol=1e-8)
        check(f"倒角渡槽 水面宽 {desc}", BW_got, BW_ref, tol=1e-8)

    # 无倒角退化验证（chamfer=0 应与纯矩形一致）
    print(f"\n  无倒角退化验证（chamfer=0）")
    h_test = 1.5
    node_plain = ChannelNode()
    node_plain.structure_type = StructureType.AQUEDUCT_RECT
    node_plain.water_depth = h_test
    node_plain.section_params = {'B': b_slot, 'chamfer_angle': 0, 'chamfer_length': 0}
    check("无倒角 面积=B*h",   calc.get_cross_section_area(node_plain),  b_slot * h_test)
    check("无倒角 湿周=B+2h",  calc.get_wetted_perimeter(node_plain),    b_slot + 2 * h_test)
    check("无倒角 水面宽=B",   calc.get_water_surface_width(node_plain), b_slot)
else:
    print(f"  {YELLOW}跳过（模块加载失败）{RESET}")


# ══════════════════════════════════════════════════════════
# 5. 连续性验证 — 各断面水面宽在分界处连续
# ══════════════════════════════════════════════════════════
section("5. 分界处连续性验证")

if CALC_OK and HORSESHOE_OK:
    # 马蹄形 — 底拱/侧拱分界、侧拱/顶拱分界
    for stype, label in [(1, "Ⅰ型"), (2, "Ⅱ型")]:
        r = 1.0
        t_map = {1: 3.0, 2: 2.0}
        theta_map = {1: 0.294515, 2: 0.424031}
        t = t_map[stype]
        theta = theta_map[stype]
        R_arch = t * r
        e = R_arch * (1 - math.cos(theta))
        eps = 1e-6

        B_below_e = calc._horseshoe_std_surface_width(stype, r, e - eps)
        B_above_e = calc._horseshoe_std_surface_width(stype, r, e + eps)
        check(f"马蹄形{label} 底拱/侧拱分界连续", B_below_e, B_above_e, tol=1e-3)

        B_below_r = calc._horseshoe_std_surface_width(stype, r, r - eps)
        B_above_r = calc._horseshoe_std_surface_width(stype, r, r + eps)
        check(f"马蹄形{label} 侧拱/顶拱分界连续", B_below_r, B_above_r, tol=1e-3)

    # 倒角矩形 — 倒角高处连续
    if CHAMFER_OK:
        b_s, ca2, cl2 = 2.5, 30.0, 0.2
        ch2 = cl2 * math.tan(math.radians(ca2))
        B_below_ch = calc._rect_chamfer_surface_width(b_s, ch2 - 1e-8, ca2, cl2)
        B_above_ch = calc._rect_chamfer_surface_width(b_s, ch2 + 1e-8, ca2, cl2)
        check("倒角矩形 倒角高处连续", B_below_ch, B_above_ch, tol=1e-4)


# ══════════════════════════════════════════════════════════
# 汇总
# ══════════════════════════════════════════════════════════
total = passed + failed
print(f"\n{BOLD}{'='*60}{RESET}")
if failed == 0:
    print(f"{BOLD}{GREEN}全部通过  {passed}/{total} PASSED{RESET}")
else:
    print(f"{BOLD}{RED}存在失败  {passed}/{total} PASSED  {failed} FAILED{RESET}")
print(f"{BOLD}{'='*60}{RESET}\n")

sys.exit(0 if failed == 0 else 1)
