# -*- coding: utf-8 -*-
"""
倒虹吸水力计算软件 - 三维空间合并引擎 (v5.0 严格数学版)

核心算法：以"分段解析几何"为基础，将平面IP点和纵断面变坡点构建为
三维空间曲线 r(s)=(x(s),y(s),z(s))，计算：
  - 任意桩号空间坐标 (x,y,z)
  - 任意桩号空间单位切向量 T(s)
  - 空间总长度 L（解析积分，精确）
  - 弯道空间转角 θ_event（事件级，§11）
  - 弯道等效半径 R_eff = L_event/θ_event（几何自洽，§11）

v5.0 相对 v4.0 的核心变更：
  §4  平面轴线改用"分段解析"（_build_plan_segments + _eval_plan）
      替代 _interpolate_plan + _fill_adjacent_angles 的"近似→覆盖"两步走
  §5  纵断面轴线改用"分段解析"（_build_profile_segments + _eval_profile）
      替代 _interpolate_long
  §7  节点集改为分段边界并集（_build_station_set）
      替代 plan_dict ∪ long_dict
  §8  节点属性一次解析求值（_evaluate_nodes）
  §9  空间长度改为分段解析积分：
      直线段 (b-a)·√(1+k²)；圆弧段 R_v·|β(b)-β(a)|
      替代 √(Δs²+ΔZ²) 通用式 + R_v×θ 补丁
  §10 弯道事件改为区间定义（_build_bend_candidates + _merge_composite_events）
      替代"节点+窗口"的 _detect_composite_events
  §11 R_eff = L/θ（几何自洽）替代 _compute_spatial_angles 中的 R_3D 曲率公式
  §12 R_3D = R_h·R_v/√(R_h²+R_v²·cos⁴β) 降为诊断输出（BendEvent.R_3d_mid）

向后兼容保证：
  - merge_and_compute() 签名完全不变
  - SpatialMergeResult 保留全部现有字段
  - _backfill_node_fields() 将 BendEvent 结果回填到 SpatialNode
    保证 siphon_hydraulics.py 消费路径（has_turn, spatial_turn_angle,
    effective_radius, effective_turn_type）完全不变
"""

import math
from typing import List, Optional, Tuple
from siphon_models import (
    PlanFeaturePoint, LongitudinalNode, SpatialNode,
    SpatialMergeResult, TurnType,
    PlanSegment, ProfileSegment, BendEvent,
)


class SpatialMerger:
    """三维空间合并引擎（v5.0 严格数学版）"""

    STATION_EPS = 1e-3   # 桩号去重容差 (m)，§13
    TURN_ANGLE_THRESH = 0.1  # 转弯角度阈值 (°)
    INF_RADIUS = 1e7         # 视为无穷大的半径阈值 (m)

    # ==================================================================
    # 主入口
    # ==================================================================

    @staticmethod
    def merge_and_compute(plan_points: List[PlanFeaturePoint],
                          long_nodes: List[LongitudinalNode],
                          pipe_diameter: float = 0.0,
                          verbose: bool = True) -> SpatialMergeResult:
        """
        合并平面和纵断面数据，计算三维空间属性。签名与 v4.0 完全相同。

        支持三种退化场景：
          A. 两者都有  → 完整三维空间计算（主路径）
          B. 仅平面    → β=0，无竖向坡度
          C. 仅纵断面  → α=常数，无水平偏转
        """
        result = SpatialMergeResult()
        steps = []

        has_plan = bool(plan_points) and len(plan_points) >= 2
        has_long = bool(long_nodes) and len(long_nodes) >= 2
        result.has_plan_data = has_plan
        result.has_longitudinal_data = has_long

        if not has_plan and not has_long:
            steps.append("警告：无平面数据和纵断面数据，无法进行空间合并计算")
            result.computation_steps = steps
            return result

        steps.append("=" * 50)
        steps.append("三维空间合并计算 (v5.0 严格数学版)")
        steps.append("=" * 50)

        # §3 预处理校验
        errs = SpatialMerger._validate_inputs(plan_points if has_plan else [],
                                               long_nodes if has_long else [])
        for e in errs:
            steps.append(f"  [输入校验] {e}")
        if errs:
            steps.append(f"  [输入不一致] 共发现 {len(errs)} 项，请优先修正输入数据")

        if has_plan and has_long:
            steps.append("模式：完整三维空间计算（平面+纵断面）")
            spatial_nodes, plan_segs, prof_segs = SpatialMerger._merge_full_3d(
                plan_points, long_nodes, steps, verbose)
        elif has_plan:
            steps.append("模式：仅平面数据（假设 β=0）")
            spatial_nodes, plan_segs, prof_segs = SpatialMerger._merge_plan_only(
                plan_points, steps)
        else:
            steps.append("模式：仅纵断面数据（假设 α=0）")
            spatial_nodes, plan_segs, prof_segs = SpatialMerger._merge_long_only(
                long_nodes, steps)

        result.nodes = spatial_nodes
        result.plan_segments = plan_segs
        result.profile_segments = prof_segs

        # §9 空间总长度（解析积分）
        steps.append("")
        steps.append("【空间长度计算（解析积分）】")
        if spatial_nodes and len(spatial_nodes) >= 2:
            s0 = spatial_nodes[0].chainage
            s1 = spatial_nodes[-1].chainage
            total_L = SpatialMerger._compute_spatial_length(prof_segs, s0, s1) if prof_segs \
                else sum(abs(spatial_nodes[i+1].chainage - spatial_nodes[i].chainage)
                         for i in range(len(spatial_nodes)-1))
        else:
            total_L = 0.0
        result.total_spatial_length = total_L
        steps.append(f"  空间总长度 L = {total_L:.4f} m")

        # §10-§11 弯道事件
        steps.append("")
        steps.append("【弯道事件计算】")
        plan_cands, vert_cands = SpatialMerger._build_bend_candidates(
            plan_segs, prof_segs,
            plan_points=plan_points if has_plan else None,
            long_nodes=long_nodes if has_long else None)
        events = SpatialMerger._merge_composite_events(plan_cands, vert_cands,
                                                        plan_segs, prof_segs)
        SpatialMerger._compute_event_properties(events, plan_segs, prof_segs)
        result.bend_events = events
        for ev in events:
            if ev.theta_event > math.radians(SpatialMerger.TURN_ANGLE_THRESH):
                steps.append(f"  [{ev.event_type}] s=[{ev.s_a:.1f},{ev.s_b:.1f}] "
                             f"θ={math.degrees(ev.theta_event):.2f}° "
                             f"R_eff={ev.R_eff:.2f}m L={ev.L_event:.2f}m")

        # 向后兼容：将事件结果回填到 SpatialNode
        SpatialMerger._backfill_node_fields(spatial_nodes, events)
        bend_count = sum(1 for ev in events
                         if ev.theta_event > math.radians(SpatialMerger.TURN_ANGLE_THRESH))
        result.xi_spatial_bends = 0.0  # 由 siphon_hydraulics 按管径查表计算
        steps.append(f"共 {bend_count} 个弯道事件")

        # §13 几何一致性断言（verbose模式）
        if verbose:
            SpatialMerger._run_geometry_assertions(
                spatial_nodes, total_L, steps,
                plan_points if has_plan else None,
                long_nodes if has_long else None)

        result.computation_steps = steps
        return result

    # ==================================================================
    # §3 预处理与一致性检查
    # ==================================================================

    @staticmethod
    def _validate_inputs(plan_points: List[PlanFeaturePoint],
                         long_nodes: List[LongitudinalNode]) -> List[str]:
        """§3: 三项预处理校验，任一失败输出错误信息（不静默吞错）"""
        errors = []
        EPS_S = SpatialMerger.STATION_EPS
        EPS_L = 0.5  # 直线段长度一致性容差 (m)

        # ①桩号严格递增
        for i in range(len(plan_points) - 1):
            ds = plan_points[i+1].chainage - plan_points[i].chainage
            if ds <= EPS_S:
                errors.append(f"平面桩号非严格递增: PP[{i}]={plan_points[i].chainage:.3f} "
                               f"> PP[{i+1}]={plan_points[i+1].chainage:.3f}")
        for i in range(len(long_nodes) - 1):
            ds = long_nodes[i+1].chainage - long_nodes[i].chainage
            if ds <= EPS_S:
                errors.append(f"纵断桩号非严格递增: LN[{i}]={long_nodes[i].chainage:.3f} "
                               f"> LN[{i+1}]={long_nodes[i+1].chainage:.3f}")

        # ②直线段长度一致性（相邻非 ARC 控制段）
        for i in range(len(plan_points) - 1):
            p1, p2 = plan_points[i], plan_points[i+1]
            if p1.turn_type != TurnType.ARC and p2.turn_type != TurnType.ARC:
                ds = p2.chainage - p1.chainage
                dxy = math.hypot(p2.x - p1.x, p2.y - p1.y)
                if abs(ds - dxy) > EPS_L and ds > 1.0:
                    errors.append(f"直线段桩号差与坐标弦长不一致: PP[{i}→{i+1}] "
                                   f"Δs={ds:.3f} vs √(ΔX²+ΔY²)={dxy:.3f}, 差={abs(ds-dxy):.3f}m")

        # ③圆弧可行性
        for i, pp in enumerate(plan_points):
            if pp.turn_type == TurnType.ARC:
                if pp.turn_radius <= 0:
                    errors.append(f"平面ARC点PP[{i}]半径 R_h≤0: R_h={pp.turn_radius}")
                if pp.turn_angle < 0.1:
                    errors.append(f"平面ARC点PP[{i}]转角过小: α={pp.turn_angle}°")
        for i, ln in enumerate(long_nodes):
            if ln.arc_end_chainage is not None:
                ds = ln.arc_end_chainage - ln.chainage
                if ds <= 1e-6:
                    errors.append(f"纵断ARC节点LN[{i}]弦长≤0")

        return errors

    # ==================================================================
    # §4 平面轴线分段解析构建
    # ==================================================================

    @staticmethod
    def _build_plan_segments(plan_points: List[PlanFeaturePoint]) -> List[PlanSegment]:
        """§4: 从 PlanFeaturePoint[] 构建平面解析分段序列（LINE/ARC 不重叠全覆盖）"""
        n = len(plan_points)
        if n < 2:
            return []

        def norm2(dx, dy):
            d = math.hypot(dx, dy)
            return (dx/d, dy/d) if d > 1e-12 else (1., 0.)

        # Step 1: 对每个内部 ARC 型 IP 反算圆弧几何（§4.1）
        arc_geom = {}   # ip_index -> dict
        for i in range(1, n - 1):
            pp = plan_points[i]
            if pp.turn_type != TurnType.ARC or pp.turn_radius <= 0 or pp.turn_angle < 0.1:
                continue
            pp_p, pp_n = plan_points[i - 1], plan_points[i + 1]
            d_in  = norm2(pp.x - pp_p.x, pp.y - pp_p.y)
            d_out = norm2(pp_n.x - pp.x, pp_n.y - pp.y)

            cross_z = d_in[0]*d_out[1] - d_in[1]*d_out[0]
            left = cross_z > 0
            eps  = 1 if left else -1

            R_h   = pp.turn_radius
            a_rad = math.radians(pp.turn_angle)
            T_len = R_h * math.tan(a_rad / 2)
            L_h   = R_h * a_rad

            bc  = (pp.x - T_len*d_in[0],  pp.y - T_len*d_in[1])
            ec  = (pp.x + T_len*d_out[0], pp.y + T_len*d_out[1])
            nin = (-d_in[1], d_in[0]) if left else (d_in[1], -d_in[0])
            cen = (bc[0] + R_h*nin[0], bc[1] + R_h*nin[1])

            bc_s  = pp.chainage - L_h / 2.0
            ec_s  = pp.chainage + L_h / 2.0
            th0   = math.atan2(bc[1] - cen[1], bc[0] - cen[0])

            arc_geom[i] = dict(bc=bc, ec=ec, bc_s=bc_s, ec_s=ec_s,
                               cen=cen, R_h=R_h, eps=eps, th0=th0)

        # Step 2: 按桩号排序事件，生成 LINE/ARC 段序列（§4.2）
        # 包含所有 IP 点（FOLD/NONE 型中间 IP 的坐标就在轴线上，必须作为段边界）
        events = []
        for i, pp in enumerate(plan_points):
            if i not in arc_geom:   # 非 ARC 型（含首尾、FOLD、中间 NONE）
                events.append((pp.chainage, (pp.x, pp.y), 'P', -1))
        for i, g in arc_geom.items():
            events.append((g['bc_s'], g['bc'], 'B', i))
            events.append((g['ec_s'], g['ec'], 'E', i))
        events.sort(key=lambda e: e[0])

        segs = []
        prev_s, prev_xy, in_arc = events[0][0], events[0][1], None
        for s, xy, k, idx in events[1:]:
            if k == 'B':
                if s > prev_s + 1e-6:
                    dx, dy = xy[0]-prev_xy[0], xy[1]-prev_xy[1]
                    segs.append(PlanSegment(seg_type='LINE', s_start=prev_s, s_end=s,
                                            p_start=prev_xy, direction=norm2(dx, dy)))
                prev_s, prev_xy, in_arc = s, xy, idx
            elif k == 'E' and in_arc == idx:
                g = arc_geom[idx]
                segs.append(PlanSegment(seg_type='ARC', s_start=g['bc_s'], s_end=g['ec_s'],
                                        center=g['cen'], R_h=g['R_h'],
                                        epsilon=g['eps'], theta_0=g['th0']))
                prev_s, prev_xy, in_arc = s, xy, None
            elif k == 'P' and in_arc is None and s > prev_s + 1e-6:
                dx, dy = xy[0]-prev_xy[0], xy[1]-prev_xy[1]
                segs.append(PlanSegment(seg_type='LINE', s_start=prev_s, s_end=s,
                                        p_start=prev_xy, direction=norm2(dx, dy)))
                prev_s, prev_xy = s, xy
        return segs

    # §4.3 平面段解析求值
    @staticmethod
    def _find_seg_idx(segs, s: float, side: str) -> int:
        """在分段列表中按桩号定位段索引，支持左('L')/右('R')/中('M')极限"""
        idx = 0
        for k, sg in enumerate(segs):
            if sg.s_start <= s + 1e-9 and s <= sg.s_end + 1e-9:
                idx = k
                break
        else:
            idx = 0 if s < segs[0].s_start else len(segs) - 1
        if side == 'L' and idx > 0 and abs(s - segs[idx].s_start) < 1e-9:
            idx -= 1
        elif side == 'R' and idx < len(segs)-1 and abs(s - segs[idx].s_end) < 1e-9:
            idx += 1
        return idx

    @staticmethod
    def _eval_plan(plan_segs: List[PlanSegment], s: float,
                   side: str = 'M') -> Tuple[float, float, float]:
        """§4.3: 解析求值平面坐标和数学方位角。返回 (x, y, α_rad)"""
        if not plan_segs:
            return (s, 0., 0.)
        sg = plan_segs[SpatialMerger._find_seg_idx(plan_segs, s, side)]
        if sg.seg_type == 'LINE':
            ds = s - sg.s_start
            x = sg.p_start[0] + ds * sg.direction[0]
            y = sg.p_start[1] + ds * sg.direction[1]
            return x, y, math.atan2(sg.direction[1], sg.direction[0])
        else:  # ARC §4.3
            theta = sg.theta_0 + sg.epsilon * (s - sg.s_start) / sg.R_h
            x = sg.center[0] + sg.R_h * math.cos(theta)
            y = sg.center[1] + sg.R_h * math.sin(theta)
            alpha = theta + sg.epsilon * math.pi / 2
            while alpha > math.pi:  alpha -= 2*math.pi
            while alpha <= -math.pi: alpha += 2*math.pi
            return x, y, alpha

    # ==================================================================
    # §5 纵断面轴线分段解析构建
    # ==================================================================

    @staticmethod
    def _build_profile_segments(long_nodes: List[LongitudinalNode]) -> List[ProfileSegment]:
        """§5: 从 LongitudinalNode[] 构建纵断面解析分段序列

        FOLD 节点作为段边界（产生两段不同坡度的 LINE 段）。
        ARC 节点产生一个 ARC 分段。
        其他 NONE 节点不创建新段，仅限定线段范围。
        """
        n = len(long_nodes)
        if n < 2:
            return []

        segs = []
        prev_s = long_nodes[0].chainage
        prev_z = long_nodes[0].elevation
        i = 0

        while i < n:
            ln = long_nodes[i]
            is_arc = (ln.turn_type == TurnType.ARC
                      and ln.arc_end_chainage is not None
                      and ln.arc_center_s is not None
                      and ln.arc_center_z is not None
                      and ln.vertical_curve_radius > 0)

            if is_arc:
                # LINE gap before ARC
                if ln.chainage > prev_s + 1e-6:
                    ds = ln.chainage - prev_s
                    k = (ln.elevation - prev_z) / ds
                    segs.append(ProfileSegment(seg_type='LINE', s_start=prev_s, s_end=ln.chainage,
                                               z_start=prev_z, k=k))

                # §5.1: 确定 η（确保 z(S_start)=Z_start）
                Sc, Zc, R_v = ln.arc_center_s, ln.arc_center_z, ln.vertical_curve_radius
                inside0 = max(0., R_v**2 - (ln.chainage - Sc)**2)
                sq0 = math.sqrt(inside0)
                eta = 1 if abs(Zc + sq0 - ln.elevation) <= abs(Zc - sq0 - ln.elevation) else -1

                arc_end = ln.arc_end_chainage
                theta_arc = ln.arc_theta_rad if ln.arc_theta_rad else 0.
                segs.append(ProfileSegment(seg_type='ARC', s_start=ln.chainage, s_end=arc_end,
                                           R_v=R_v, Sc=Sc, Zc=Zc, eta=eta,
                                           theta_arc=theta_arc))

                inside_e = max(0., R_v**2 - (arc_end - Sc)**2)
                prev_z = Zc + eta * math.sqrt(inside_e)
                prev_s = arc_end

                # 跳过弧内节点，定位弧终点节点
                j = i + 1
                while j < n and long_nodes[j].chainage < arc_end - 1e-3:
                    j += 1
                if j < n and abs(long_nodes[j].chainage - arc_end) < 0.1:
                    prev_z = long_nodes[j].elevation
                    i = j
                else:
                    i = j
                continue

            elif ln.turn_type == TurnType.FOLD and ln.chainage > prev_s + 1e-6:
                # §10.1: FOLD 节点为段边界，将前一段 LINE 封闭于此
                ds = ln.chainage - prev_s
                k = (ln.elevation - prev_z) / ds
                segs.append(ProfileSegment(seg_type='LINE', s_start=prev_s, s_end=ln.chainage,
                                           z_start=prev_z, k=k))
                prev_s = ln.chainage
                prev_z = ln.elevation

            i += 1

        last = long_nodes[-1]
        if last.chainage > prev_s + 1e-6:
            ds = last.chainage - prev_s
            k = (last.elevation - prev_z) / ds
            segs.append(ProfileSegment(seg_type='LINE', s_start=prev_s, s_end=last.chainage,
                                       z_start=prev_z, k=k))
        return segs

    # §5.2 纵断面段解析求值
    @staticmethod
    def _eval_profile(prof_segs: List[ProfileSegment], s: float,
                      side: str = 'M') -> Tuple[float, float]:
        """§5.2: 解析求值高程和坡角。返回 (z, β_rad)"""
        if not prof_segs:
            return (0., 0.)
        sg = prof_segs[SpatialMerger._find_seg_idx(prof_segs, s, side)]
        if sg.seg_type == 'LINE':
            z    = sg.z_start + sg.k * (s - sg.s_start)
            beta = math.atan(sg.k)   # §5.2: atan（不是 atan2）
            return z, beta
        else:  # ARC §5.2
            inside = max(0., sg.R_v**2 - (s - sg.Sc)**2)
            z      = sg.Zc + sg.eta * math.sqrt(inside)
            denom  = z - sg.Zc
            dz_ds  = -(s - sg.Sc) / denom if abs(denom) > 1e-12 else 0.
            beta   = math.atan(dz_ds)   # §5.2: atan（不是 atan2）
            return z, beta

    # ==================================================================
    # §6 三维单位切向量（辅助函数）
    # ==================================================================

    @staticmethod
    def _make_T(alpha_rad: float, beta_rad: float) -> Tuple[float, float, float]:
        """§6.2: T(s) = (cosβ·cosα, cosβ·sinα, sinβ)，|T|=1"""
        cb = math.cos(beta_rad)
        return (cb * math.cos(alpha_rad), cb * math.sin(alpha_rad), math.sin(beta_rad))

    @staticmethod
    def _dot3(a: Tuple, b: Tuple) -> float:
        return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

    @staticmethod
    def _unique_sorted_eps(values: List[float], eps: Optional[float] = None) -> List[float]:
        """按容差 ε 去重并升序，避免量化改写边界桩号。"""
        if not values:
            return []
        if eps is None:
            eps = SpatialMerger.STATION_EPS
        arr = sorted(float(v) for v in values)
        uniq = [arr[0]]
        for v in arr[1:]:
            if abs(v - uniq[-1]) > eps:
                uniq.append(v)
        return uniq

    # ==================================================================
    # §7 节点集生成
    # ==================================================================

    @staticmethod
    def _build_station_set(plan_segs: List[PlanSegment],
                           prof_segs: List[ProfileSegment],
                           long_nodes: Optional[List[LongitudinalNode]] = None,
                           plan_points: Optional[List[PlanFeaturePoint]] = None) -> List[float]:
        """§7: S = Unique(S_P ∪ S_V ∪ S_biz)，ε_s=1e-3，升序排列

        S_P = 所有平面段边界 (s_BC, s_EC, 首尾)
        S_V = 所有纵断面顶点 S_k（必须包含所有 LongitudinalNode.chainage）
        """
        raw = []
        # S_P: 平面分段边界
        for sg in plan_segs:
            raw.append(sg.s_start)
            raw.append(sg.s_end)
        # 纵断面分段边界（覆盖 ARC 起终点）
        for sg in prof_segs:
            raw.append(sg.s_start)
            raw.append(sg.s_end)
        # S_V: 所有纵断面顶点（§7：标准 S_V = {S_k}）
        if long_nodes:
            for ln in long_nodes:
                raw.append(ln.chainage)
        # S_biz: 业务附加桩号（这里将平面特征点桩号并入）
        if plan_points:
            for pp in plan_points:
                raw.append(pp.chainage)
        return SpatialMerger._unique_sorted_eps(raw)

    # ==================================================================
    # §8 节点属性计算（解析精确）
    # ==================================================================

    @staticmethod
    def _evaluate_nodes(stations: List[float],
                        plan_segs: List[PlanSegment],
                        prof_segs: List[ProfileSegment]) -> List[SpatialNode]:
        """§8: 对每个桩号一次解析求值，计算 x,y,z,α,β,T,θ_node"""
        nodes = []
        for s in stations:
            x, y, alpha_m = SpatialMerger._eval_plan(plan_segs, s, 'M')
            z, beta_m     = SpatialMerger._eval_profile(prof_segs, s, 'M')

            # 左右极限切向（段边界处取不同段）
            _, _, al = SpatialMerger._eval_plan(plan_segs, s, 'L')
            _, _, ar = SpatialMerger._eval_plan(plan_segs, s, 'R')
            _, bl    = SpatialMerger._eval_profile(prof_segs, s, 'L')
            _, br    = SpatialMerger._eval_profile(prof_segs, s, 'R')

            T_bef = SpatialMerger._make_T(al, bl)
            T_aft = SpatialMerger._make_T(ar, br)

            dot = max(-1., min(1., SpatialMerger._dot3(T_bef, T_aft)))
            theta_node = math.acos(dot)

            nd = SpatialNode(
                chainage=s, x=x, y=y, z=z,
                azimuth_before=math.degrees(al),
                azimuth_after=math.degrees(ar),
                slope_before=bl,
                slope_after=br,
                # v5.0 新增解析精确字段
                alpha_before_rad=al, alpha_after_rad=ar,
                beta_before_rad=bl,  beta_after_rad=br,
                T_before=T_bef, T_after=T_aft,
                theta_3d_node=theta_node,
            )
            nodes.append(nd)
        return nodes

    # ==================================================================
    # §9 空间长度解析积分
    # ==================================================================

    @staticmethod
    def _seg_length(sg: ProfileSegment, s_a: float, s_b: float) -> float:
        """§9: 单段解析积分"""
        a = max(sg.s_start, s_a)
        b = min(sg.s_end,   s_b)
        if b <= a + 1e-12:
            return 0.
        if sg.seg_type == 'LINE':
            return (b - a) * math.sqrt(1. + sg.k**2)   # §9.1
        else:
            _, ba = SpatialMerger._eval_profile([sg], a)
            _, bb = SpatialMerger._eval_profile([sg], b)
            return sg.R_v * abs(bb - ba)                # §9.2: R_v·|Δβ|

    @staticmethod
    def _compute_spatial_length(prof_segs: List[ProfileSegment],
                                s_a: float, s_b: float) -> float:
        """§9: [s_a,s_b] 区间解析空间长度（跨段时分段累加）"""
        return sum(SpatialMerger._seg_length(sg, s_a, s_b) for sg in prof_segs)

    # ==================================================================
    # §10 弯道事件候选集与复合合并
    # ==================================================================

    @staticmethod
    def _build_bend_candidates(plan_segs: List[PlanSegment],
                               prof_segs: List[ProfileSegment],
                               plan_points: Optional[List[PlanFeaturePoint]] = None,
                               long_nodes: Optional[List[LongitudinalNode]] = None):
        """§10.1: 弯道事件候选集

        ARC 平面段 ⇒ 水平圆弧事件 [s_BC, s_EC]
        FOLD 平面 IP ⇒ 水平折点事件（零长度）
        ARC 纵断段 ⇒ 竖向圆弧事件 [S1, S2]
        FOLD 纵断节点 ⇒ 竖向折坡事件（零长度）
        """
        plan_evts = []
        # 平面 ARC 圆弧事件
        for sg in plan_segs:
            if sg.seg_type == 'ARC' and sg.R_h > 0:
                plan_evts.append(BendEvent(s_a=sg.s_start, s_b=sg.s_end,
                                           event_type='PLAN', turn_style=TurnType.ARC,
                                           R_h=sg.R_h))
        # 平面 FOLD 折点事件（零长度，§10.1）
        if plan_points:
            for pp in plan_points:
                if pp.turn_type == TurnType.FOLD and pp.turn_angle > SpatialMerger.TURN_ANGLE_THRESH:
                    plan_evts.append(BendEvent(s_a=pp.chainage, s_b=pp.chainage,
                                               event_type='PLAN', turn_style=TurnType.FOLD))

        vert_evts = []
        # 纵断 ARC 圆弧事件
        for sg in prof_segs:
            if sg.seg_type == 'ARC' and sg.R_v > 0:
                vert_evts.append(BendEvent(s_a=sg.s_start, s_b=sg.s_end,
                                           event_type='VERTICAL', turn_style=TurnType.ARC,
                                           R_v=sg.R_v))
        # 纵断 FOLD 折坡事件（零长度，§10.1）
        if long_nodes:
            for ln in long_nodes:
                if ln.turn_type == TurnType.FOLD and ln.turn_angle > SpatialMerger.TURN_ANGLE_THRESH:
                    vert_evts.append(BendEvent(s_a=ln.chainage, s_b=ln.chainage,
                                               event_type='VERTICAL', turn_style=TurnType.FOLD))
        return plan_evts, vert_evts

    @staticmethod
    def _merge_composite_events(plan_evts: List[BendEvent],
                                vert_evts: List[BendEvent],
                                plan_segs: List[PlanSegment],
                                prof_segs: List[ProfileSegment]) -> List[BendEvent]:
        """§10.2: 区间分割合并法，生成最终弯道事件列表

        ARC 平面事件和 ARC 纵断事件通过区间分割合并。
        FOLD 零长度事件单独处理：检查是否落在另一类型的 ARC 事件内成为复合。
        """
        if not plan_evts and not vert_evts:
            return []

        # 分离 ARC 事件和 FOLD 零长度事件
        plan_arc = [e for e in plan_evts if e.turn_style == TurnType.ARC]
        plan_fold = [e for e in plan_evts if e.turn_style == TurnType.FOLD]
        vert_arc  = [e for e in vert_evts if e.turn_style == TurnType.ARC]
        vert_fold = [e for e in vert_evts if e.turn_style == TurnType.FOLD]

        # 对 ARC-ARC 事件做区间分割合并
        result_evts = []
        if plan_arc or vert_arc:
            pts = []
            for e in plan_arc + vert_arc:
                pts.append(e.s_a)
                pts.append(e.s_b)
            pts = SpatialMerger._unique_sorted_eps(pts)

            if len(pts) >= 2:
                prev_type = None
                prev_sa   = None

                def in_arc_evts(s_mid, evts):
                    return any(e.s_a - 1e-9 <= s_mid <= e.s_b + 1e-9 for e in evts)

                for k in range(len(pts) - 1):
                    qa, qb = pts[k], pts[k+1]
                    if qb - qa < 1e-9:
                        continue
                    s_mid = (qa + qb) / 2.
                    in_p = in_arc_evts(s_mid, plan_arc)
                    in_v = in_arc_evts(s_mid, vert_arc)

                    if not in_p and not in_v:
                        prev_type = None; prev_sa = None
                        continue

                    etype = 'COMPOSITE' if (in_p and in_v) else ('PLAN' if in_p else 'VERTICAL')
                    R_h = next((e.R_h for e in plan_arc if e.s_a-1e-9<=s_mid<=e.s_b+1e-9), 0.)
                    R_v = next((e.R_v for e in vert_arc if e.s_a-1e-9<=s_mid<=e.s_b+1e-9), 0.)

                    if etype == prev_type and prev_sa is not None:
                        result_evts[-1].s_b = qb
                        result_evts[-1].R_h = result_evts[-1].R_h or R_h
                        result_evts[-1].R_v = result_evts[-1].R_v or R_v
                    else:
                        result_evts.append(BendEvent(s_a=qa, s_b=qb,
                                                     event_type=etype, turn_style=TurnType.ARC,
                                                     R_h=R_h, R_v=R_v))
                        prev_type = etype
                        prev_sa   = qa

        # FOLD 零长度事件：按桩号聚合，处理 PLAN/VERTICAL 同桩号折点的复合事件
        fold_stations = SpatialMerger._unique_sorted_eps(
            [e.s_a for e in plan_fold] + [e.s_a for e in vert_fold]
        )
        for s in fold_stations:
            has_p = any(abs(e.s_a - s) <= SpatialMerger.STATION_EPS for e in plan_fold)
            has_v = any(abs(e.s_a - s) <= SpatialMerger.STATION_EPS for e in vert_fold)
            in_p_arc = any(e.s_a - 1e-9 <= s <= e.s_b + 1e-9 for e in plan_arc)
            in_v_arc = any(e.s_a - 1e-9 <= s <= e.s_b + 1e-9 for e in vert_arc)

            if has_p and has_v:
                etype = 'COMPOSITE'
            elif has_p:
                etype = 'COMPOSITE' if in_v_arc else 'PLAN'
            else:
                etype = 'COMPOSITE' if in_p_arc else 'VERTICAL'

            result_evts.append(BendEvent(s_a=s, s_b=s,
                                         event_type=etype, turn_style=TurnType.FOLD))

        # 按开始桩号排序（方便下游查表）
        result_evts.sort(key=lambda e: e.s_a)
        return result_evts

    # ==================================================================
    # §11 事件转角与等效半径
    # ==================================================================

    @staticmethod
    def _compute_event_properties(events: List[BendEvent],
                                  plan_segs: List[PlanSegment],
                                  prof_segs: List[ProfileSegment]) -> None:
        """§11: 计算每个事件的 L_event, θ_event, R_eff = L/θ

        ARC 事件: T_a = T(s_a^+)， T_b = T(s_b^-)， L = 解析积分， R_eff = L/θ
        FOLD 事件 (s_a=s_b): T_a = T(s^+)， T_b = T(s^-)， L = 0， R_eff = 0（表示锐折）
        """
        for ev in events:
            if ev.turn_style == TurnType.FOLD:
                # FOLD 零长度事件：用左右极限切向计算转角
                _, _, al = SpatialMerger._eval_plan(plan_segs, ev.s_a, 'L')
                _, bl    = SpatialMerger._eval_profile(prof_segs, ev.s_a, 'L')
                _, _, ar = SpatialMerger._eval_plan(plan_segs, ev.s_a, 'R')
                _, br    = SpatialMerger._eval_profile(prof_segs, ev.s_a, 'R')
                T_bef = SpatialMerger._make_T(al, bl)
                T_aft = SpatialMerger._make_T(ar, br)
                dot = max(-1., min(1., SpatialMerger._dot3(T_bef, T_aft)))
                ev.theta_event = math.acos(dot)
                ev.L_event = 0.
                ev.R_eff   = 0.   # FOLD 无平滑过渡，R_eff=0 表示锐折
                continue

            # ARC 事件：§11 的标准公式
            _, _, al = SpatialMerger._eval_plan(plan_segs, ev.s_a, 'R')
            _, bl    = SpatialMerger._eval_profile(prof_segs, ev.s_a, 'R')
            _, _, ar = SpatialMerger._eval_plan(plan_segs, ev.s_b, 'L')
            _, br    = SpatialMerger._eval_profile(prof_segs, ev.s_b, 'L')

            T_a = SpatialMerger._make_T(al, bl)
            T_b = SpatialMerger._make_T(ar, br)
            dot = max(-1., min(1., SpatialMerger._dot3(T_a, T_b)))
            ev.theta_event = math.acos(dot)

            ev.L_event = (SpatialMerger._compute_spatial_length(prof_segs, ev.s_a, ev.s_b)
                          if prof_segs else (ev.s_b - ev.s_a))

            ev.R_eff = (ev.L_event / ev.theta_event
                        if ev.theta_event > 1e-9 else float('inf'))

            # §12 可选诊断：事件中点 R_3D(s_m)
            if ev.R_h > 0 and ev.R_v > 0:
                s_m = (ev.s_a + ev.s_b) / 2.
                _, beta_m = SpatialMerger._eval_profile(prof_segs, s_m)
                cos4b = math.cos(beta_m) ** 4
                kap2  = 1./ev.R_v**2 + cos4b/ev.R_h**2
                ev.R_3d_mid = 1. / math.sqrt(kap2) if kap2 > 1e-30 else float('inf')
            elif ev.R_h > 0:
                # R_v→∞ 极限：R_3D = R_h / cos²β
                s_m = (ev.s_a + ev.s_b) / 2.
                _, beta_m = SpatialMerger._eval_profile(prof_segs, s_m)
                cosb = math.cos(beta_m)
                ev.R_3d_mid = ev.R_h / (cosb * cosb) if abs(cosb) > 1e-12 else float('inf')
            elif ev.R_v > 0:
                ev.R_3d_mid = ev.R_v

    # ==================================================================
    # 向后兼容：回填 SpatialNode 旧字段
    # ==================================================================

    @staticmethod
    def _backfill_node_fields(nodes: List[SpatialNode],
                              events: List[BendEvent]) -> None:
        """将 BendEvent 结果回填到 SpatialNode，保证下游 siphon_hydraulics 不变"""
        EPS = 2.0  # m，节点-事件匹配容差
        for nd in nodes:
            best_ev = None
            best_dist = float('inf')
            for ev in events:
                if ev.theta_event < math.radians(SpatialMerger.TURN_ANGLE_THRESH):
                    continue
                dist = min(abs(nd.chainage - ev.s_a), abs(nd.chainage - ev.s_b),
                           abs(nd.chainage - (ev.s_a+ev.s_b)/2.))
                if nd.chainage >= ev.s_a - EPS and nd.chainage <= ev.s_b + EPS and dist < best_dist:
                    best_dist = dist
                    best_ev = ev

            if best_ev is None:
                continue

            nd.spatial_turn_angle = math.degrees(best_ev.theta_event)
            nd.effective_radius   = best_ev.R_eff if best_ev.R_eff < SpatialMerger.INF_RADIUS else 0.

            if best_ev.event_type in ('PLAN', 'COMPOSITE'):
                nd.has_plan_turn    = True
                nd.plan_turn_radius = best_ev.R_h if best_ev.R_h > 0 else nd.plan_turn_radius
                # 用事件的 turn_style 设置类型（FOLD→FOLD, ARC→ARC），不覆盖已有非NONE标记
                if nd.plan_turn_type == TurnType.NONE:
                    nd.plan_turn_type = best_ev.turn_style
            if best_ev.event_type in ('VERTICAL', 'COMPOSITE'):
                nd.has_long_turn    = True
                nd.long_turn_radius = best_ev.R_v if best_ev.R_v > 0 else nd.long_turn_radius
                if nd.long_turn_type == TurnType.NONE:
                    nd.long_turn_type = best_ev.turn_style

            # 保守规则：任一FOLD则FOLD，双ARC才ARC（§PRD v4.0风险点C）
            if nd.plan_turn_type == TurnType.FOLD or nd.long_turn_type == TurnType.FOLD:
                nd.effective_turn_type = TurnType.FOLD
            else:
                nd.effective_turn_type = best_ev.turn_style

    # ==================================================================
    # 三种退化合并模式
    # ==================================================================

    @staticmethod
    def _merge_full_3d(plan_points, long_nodes, steps, verbose):
        """模式A：完整三维合并"""
        plan_segs = SpatialMerger._build_plan_segments(plan_points)
        prof_segs = SpatialMerger._build_profile_segments(long_nodes)

        stations = SpatialMerger._build_station_set(plan_segs, prof_segs,
                                                     long_nodes=long_nodes,
                                                     plan_points=plan_points)
        if verbose:
            steps.append(f"  平面分段: {len(plan_segs)} 段，纵断面分段: {len(prof_segs)} 段")
            steps.append(f"  节点集: {len(stations)} 个桩号")

        nodes = SpatialMerger._evaluate_nodes(stations, plan_segs, prof_segs)

        # 从节点中标记转弯信息（保留旧字段供下游）
        SpatialMerger._tag_turn_nodes(nodes, plan_segs, prof_segs, plan_points, long_nodes)

        return nodes, plan_segs, prof_segs

    @staticmethod
    def _merge_plan_only(plan_points, steps):
        """模式B：仅平面数据，β=0"""
        plan_segs = SpatialMerger._build_plan_segments(plan_points)
        # 生成平坦纵断面（z=0 的 LINE 段）
        if plan_segs:
            s0, s1 = plan_segs[0].s_start, plan_segs[-1].s_end
        else:
            s0, s1 = plan_points[0].chainage, plan_points[-1].chainage
        prof_segs = [ProfileSegment(seg_type='LINE', s_start=s0, s_end=s1, z_start=0., k=0.)]

        stations = SpatialMerger._build_station_set(plan_segs, prof_segs,
                                                    plan_points=plan_points)
        nodes = SpatialMerger._evaluate_nodes(stations, plan_segs, prof_segs)
        SpatialMerger._tag_turn_nodes(nodes, plan_segs, prof_segs, plan_points, [])
        steps.append(f"  生成 {len(nodes)} 个空间节点（β=0 退化模式）")
        return nodes, plan_segs, prof_segs

    # NOTE: _merge_long_only 不传 plan_points，不需要平面 FOLD 事件

    @staticmethod
    def _merge_long_only(long_nodes, steps):
        """模式C：仅纵断面数据，α=0（朝正东），X=桩号，Y=0"""
        # 生成直线平面段（朝正东方向）
        s0, s1 = long_nodes[0].chainage, long_nodes[-1].chainage
        plan_segs = [PlanSegment(seg_type='LINE', s_start=s0, s_end=s1,
                                  p_start=(s0, 0.), direction=(1., 0.))]
        prof_segs = SpatialMerger._build_profile_segments(long_nodes)

        stations = SpatialMerger._build_station_set(plan_segs, prof_segs,
                                                      long_nodes=long_nodes)
        nodes = SpatialMerger._evaluate_nodes(stations, plan_segs, prof_segs)
        SpatialMerger._tag_turn_nodes(nodes, plan_segs, prof_segs, [], long_nodes)
        steps.append(f"  生成 {len(nodes)} 个空间节点（α=0 退化模式）")
        return nodes, plan_segs, prof_segs

    @staticmethod
    def _tag_turn_nodes(nodes, plan_segs, prof_segs, plan_points, long_nodes):
        """为节点打上平面/纵断面转弯标记（保留旧字段，供 _backfill_node_fields 使用）"""
        # 从原始 plan_points 对应节点（QZ桩号）精确匹配
        plan_dict = {round(pp.chainage, 3): pp for pp in plan_points}
        long_dict  = {round(ln.chainage, 3): ln for ln in long_nodes}

        for nd in nodes:
            s_r = round(nd.chainage, 3)
            pp  = plan_dict.get(s_r)
            ln  = long_dict.get(s_r)

            if pp and pp.turn_angle > 0.1 and pp.turn_type != TurnType.NONE:
                nd.has_plan_turn  = True
                nd.plan_turn_radius = pp.turn_radius
                nd.plan_turn_angle  = pp.turn_angle
                nd.plan_turn_type   = pp.turn_type

            if ln and ln.turn_angle > 0.1 and ln.turn_type != TurnType.NONE:
                nd.has_long_turn  = True
                nd.long_turn_radius = ln.vertical_curve_radius
                nd.long_turn_angle  = ln.turn_angle
                nd.long_turn_type   = ln.turn_type
                if ln.turn_type == TurnType.ARC and ln.arc_end_chainage is not None:
                    nd.long_arc_end_chainage = ln.arc_end_chainage
                    nd.long_arc_theta_rad    = ln.arc_theta_rad

    # ==================================================================
    # 向后兼容：保留旧的 _build_plan_geometry 和 _arc_point
    # （供运行时断言和外部调用）
    # ==================================================================

    @staticmethod
    def _build_plan_geometry(plan_points: List[PlanFeaturePoint]) -> List[dict]:
        """保留：为每个圆弧型IP点预计算精确几何参数（供运行时断言）"""
        n = len(plan_points)
        geom = [dict(bc=None, ec=None, center=None, qz=None,
                     bc_chainage=None, ec_chainage=None,
                     d_in=None, d_out=None, left_turn=True)
                for _ in range(n)]
        for i in range(1, n - 1):
            pp = plan_points[i]
            if pp.turn_type != TurnType.ARC or pp.turn_angle < 0.1 or pp.turn_radius <= 0:
                continue
            pp_prev = plan_points[i - 1]; pp_next = plan_points[i + 1]
            dx_in  = pp.x - pp_prev.x; dy_in  = pp.y - pp_prev.y
            dx_out = pp_next.x - pp.x; dy_out = pp_next.y - pp.y
            len_in  = math.sqrt(dx_in**2 + dy_in**2)
            len_out = math.sqrt(dx_out**2 + dy_out**2)
            if len_in < 1e-9 or len_out < 1e-9:
                continue
            d_in  = (dx_in/len_in,  dy_in/len_in)
            d_out = (dx_out/len_out, dy_out/len_out)
            R = pp.turn_radius; a_rad = math.radians(pp.turn_angle)
            T = R * math.tan(a_rad / 2); L_arc = R * a_rad
            bc = (pp.x - T*d_in[0],  pp.y - T*d_in[1])
            ec = (pp.x + T*d_out[0], pp.y + T*d_out[1])
            left_turn = (d_in[0]*d_out[1] - d_in[1]*d_out[0]) > 0
            if left_turn:
                center = (bc[0] - R*d_in[1], bc[1] + R*d_in[0])
            else:
                center = (bc[0] + R*d_in[1], bc[1] - R*d_in[0])
            bc_ch = pp.chainage - L_arc/2.; ec_ch = pp.chainage + L_arc/2.
            qz = SpatialMerger._arc_point(center, R, bc, a_rad/2., left_turn)
            geom[i] = dict(bc=bc, ec=ec, center=center, qz=qz,
                           bc_chainage=bc_ch, ec_chainage=ec_ch,
                           d_in=d_in, d_out=d_out, left_turn=left_turn)
        return geom

    @staticmethod
    def _arc_point(center, R, bc, delta, left_turn):
        """保留：从BC沿圆弧行进 delta 弧度，返回弧上坐标"""
        theta_bc = math.atan2(bc[1] - center[1], bc[0] - center[0])
        theta    = theta_bc + delta if left_turn else theta_bc - delta
        return (center[0] + R * math.cos(theta), center[1] + R * math.sin(theta))

    # ==================================================================
    # §13 运行时几何一致性断言
    # ==================================================================

    @staticmethod
    def _run_geometry_assertions(spatial_nodes, total_spatial_length, steps,
                                  plan_points=None, long_nodes=None):
        """§13: 5项几何一致性断言（不抛异常，仅输出警告）"""
        warnings = []
        n = len(spatial_nodes)
        if n < 2:
            return

        # 断言1：桩号单调性
        for i in range(n - 1):
            ds = spatial_nodes[i+1].chainage - spatial_nodes[i].chainage
            if ds < -1e-6:
                warnings.append(f"[断言1] 桩号非单调: 段{i} Δs={ds:.6f}")

        # 断言2：平面弦长 ≤ 桩号差（弧长≥弦长）
        EPS = 1e-2
        for i in range(n - 1):
            n1, n2 = spatial_nodes[i], spatial_nodes[i+1]
            ds = n2.chainage - n1.chainage
            if ds < 1e-6: continue
            dh = math.hypot(n2.x - n1.x, n2.y - n1.y)
            if dh > ds + EPS:
                warnings.append(f"[断言2] 弦长>桩号差: 段{i} dh={dh:.4f}>ds={ds:.4f}")

        # 断言3：平面弧段圆方程
        if plan_points:
            geom = SpatialMerger._build_plan_geometry(plan_points)
            for idx, g in enumerate(geom):
                if g['center'] is None: continue
                R = plan_points[idx].turn_radius
                cx, cy = g['center']
                for nd in spatial_nodes:
                    if g['bc_chainage'] <= nd.chainage <= g['ec_chainage']:
                        err = abs(math.hypot(nd.x-cx, nd.y-cy) - R)
                        if err > 0.5:
                            warnings.append(f"[断言3] 弧段节点偏离圆: s={nd.chainage:.3f} err={err:.4f}m")

        # 断言4：竖曲线弧段圆方程
        if long_nodes:
            for ln in long_nodes:
                if (ln.turn_type == TurnType.ARC and ln.arc_center_s is not None
                        and ln.arc_center_z is not None and ln.vertical_curve_radius > 0):
                    Sc, Zc, Rv = ln.arc_center_s, ln.arc_center_z, ln.vertical_curve_radius
                    err0 = abs(math.hypot(ln.chainage-Sc, ln.elevation-Zc) - Rv)
                    if err0 > 0.1:
                        warnings.append(f"[断言4] 竖曲线起点偏离圆: s={ln.chainage:.3f} err={err0:.4f}m")

        # 断言5：L_spatial ≥ 水平总长
        total_h = sum(abs(spatial_nodes[i+1].chainage - spatial_nodes[i].chainage)
                      for i in range(n-1))
        if total_spatial_length < total_h - 1e-6:
            warnings.append(f"[断言5] L_spatial<L_horizontal: {total_spatial_length:.4f}<{total_h:.4f}")

        steps.append("")
        steps.append("【几何一致性检查】")
        if warnings:
            for w in warnings: steps.append(f"  ⚠ {w}")
        else:
            steps.append("  全部通过")
