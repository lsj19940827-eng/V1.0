# -*- coding: utf-8 -*-
"""
Rigorous stress tests for the strict-math spatial merger.

This file intentionally contains many batch/subTest cases to validate:
1) formula-level correctness;
2) interval/event semantics;
3) numeric stability around boundaries;
4) randomized robustness.
"""

import math
import os
import random
import sys
import unittest


_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, "倒虹吸水力计算系统"))

from siphon_models import (  # noqa: E402
    BendEvent,
    LongitudinalNode,
    PlanFeaturePoint,
    PlanSegment,
    ProfileSegment,
    TurnType,
)
from spatial_merger import SpatialMerger  # noqa: E402


def _meas_from_alpha(alpha_math_rad: float) -> float:
    return 90.0 - math.degrees(alpha_math_rad)


def _make_plan_straight(s0: float, s1: float):
    return [
        PlanFeaturePoint(
            chainage=s0, x=s0, y=0.0, azimuth_meas_deg=90.0, turn_type=TurnType.NONE
        ),
        PlanFeaturePoint(
            chainage=s1, x=s1, y=0.0, azimuth_meas_deg=90.0, turn_type=TurnType.NONE
        ),
    ]


def _make_plan_single_arc(
    R_h: float,
    alpha_deg: float,
    qz_s: float = 500.0,
    s_start: float = 0.0,
    s_end: float = 1300.0,
    left_turn: bool = True,
):
    ip0 = (0.0, 0.0)
    ip1 = (500.0, 0.0)
    sign = 1.0 if left_turn else -1.0
    out_alpha = sign * math.radians(alpha_deg)
    d_out = (math.cos(out_alpha), math.sin(out_alpha))
    ip2 = (ip1[0] + 800.0 * d_out[0], ip1[1] + 800.0 * d_out[1])
    az2 = _meas_from_alpha(math.atan2(d_out[1], d_out[0]))
    return [
        PlanFeaturePoint(
            chainage=s_start,
            x=ip0[0],
            y=ip0[1],
            azimuth_meas_deg=90.0,
            turn_type=TurnType.NONE,
        ),
        PlanFeaturePoint(
            chainage=qz_s,
            x=ip1[0],
            y=ip1[1],
            azimuth_meas_deg=90.0,
            turn_angle=alpha_deg,
            turn_radius=R_h,
            turn_type=TurnType.ARC,
        ),
        PlanFeaturePoint(
            chainage=s_end,
            x=ip2[0],
            y=ip2[1],
            azimuth_meas_deg=az2,
            turn_type=TurnType.NONE,
        ),
    ]


def _make_long_const_slope(s0: float, s1: float, z0: float, k: float):
    beta = math.atan(k)
    return [
        LongitudinalNode(
            chainage=s0, elevation=z0, turn_type=TurnType.NONE, slope_after=beta
        ),
        LongitudinalNode(
            chainage=s1,
            elevation=z0 + (s1 - s0) * k,
            turn_type=TurnType.NONE,
            slope_before=beta,
        ),
    ]


def _make_long_single_arc(
    s0: float,
    s1: float,
    z0: float,
    arc_start: float,
    R_v: float,
    beta_before: float,
    beta_after: float,
):
    # Valley-style branch (eta = -1): s = Sc + R*sin(beta), z = Zc - R*cos(beta)
    z_start = z0 + (arc_start - s0) * math.tan(beta_before)
    Sc = arc_start - R_v * math.sin(beta_before)
    Zc = z_start + R_v * math.cos(beta_before)
    arc_end = Sc + R_v * math.sin(beta_after)
    z_end = Zc - R_v * math.cos(beta_after)
    z_final = z_end + (s1 - arc_end) * math.tan(beta_after)
    theta = abs(beta_after - beta_before)
    return [
        LongitudinalNode(
            chainage=s0, elevation=z0, turn_type=TurnType.NONE, slope_after=beta_before
        ),
        LongitudinalNode(
            chainage=arc_start,
            elevation=z_start,
            turn_type=TurnType.ARC,
            vertical_curve_radius=R_v,
            turn_angle=math.degrees(theta),
            slope_before=beta_before,
            slope_after=beta_after,
            arc_center_s=Sc,
            arc_center_z=Zc,
            arc_end_chainage=arc_end,
            arc_theta_rad=theta,
        ),
        LongitudinalNode(
            chainage=arc_end,
            elevation=z_end,
            turn_type=TurnType.NONE,
            slope_before=beta_after,
            slope_after=beta_after,
        ),
        LongitudinalNode(
            chainage=s1,
            elevation=z_final,
            turn_type=TurnType.NONE,
            slope_before=beta_after,
        ),
    ]


class TestStrictValidationBulk(unittest.TestCase):
    def test_non_strict_chainage_rejected_bulk(self):
        bad_deltas = [0.0, 1e-4, 5e-4, 9e-4]
        for ds in bad_deltas:
            with self.subTest(ds=ds):
                pps = [
                    PlanFeaturePoint(
                        chainage=100.0,
                        x=100.0,
                        y=0.0,
                        azimuth_meas_deg=90.0,
                        turn_type=TurnType.NONE,
                    ),
                    PlanFeaturePoint(
                        chainage=100.0 + ds,
                        x=101.0,
                        y=0.0,
                        azimuth_meas_deg=90.0,
                        turn_type=TurnType.NONE,
                    ),
                ]
                errs = SpatialMerger._validate_inputs(pps, [])
                self.assertTrue(any("非严格递增" in e for e in errs))

    def test_descending_long_chainage_rejected(self):
        lns = [
            LongitudinalNode(chainage=20.0, elevation=100.0, turn_type=TurnType.NONE),
            LongitudinalNode(chainage=10.0, elevation=99.0, turn_type=TurnType.NONE),
        ]
        errs = SpatialMerger._validate_inputs([], lns)
        self.assertTrue(any("纵断桩号非严格递增" in e for e in errs))

    def test_straight_length_consistency_none_fold_checked(self):
        pps = [
            PlanFeaturePoint(
                chainage=0.0, x=0.0, y=0.0, azimuth_meas_deg=90.0, turn_type=TurnType.NONE
            ),
            PlanFeaturePoint(
                chainage=40.0,
                x=10.0,
                y=0.0,
                azimuth_meas_deg=90.0,
                turn_angle=20.0,
                turn_type=TurnType.FOLD,
            ),
        ]
        errs = SpatialMerger._validate_inputs(pps, [])
        self.assertTrue(any("弦长不一致" in e for e in errs))

    def test_arc_feasibility_checks_bulk(self):
        pps = [
            PlanFeaturePoint(
                chainage=0.0, x=0.0, y=0.0, azimuth_meas_deg=90.0, turn_type=TurnType.NONE
            ),
            PlanFeaturePoint(
                chainage=100.0,
                x=100.0,
                y=0.0,
                azimuth_meas_deg=90.0,
                turn_angle=0.01,
                turn_radius=-1.0,
                turn_type=TurnType.ARC,
            ),
            PlanFeaturePoint(
                chainage=200.0, x=200.0, y=0.0, azimuth_meas_deg=90.0, turn_type=TurnType.NONE
            ),
        ]
        lns = [
            LongitudinalNode(
                chainage=50.0,
                elevation=100.0,
                turn_type=TurnType.ARC,
                vertical_curve_radius=300.0,
                arc_center_s=55.0,
                arc_center_z=200.0,
                arc_end_chainage=49.0,
            ),
            LongitudinalNode(chainage=100.0, elevation=101.0, turn_type=TurnType.NONE),
        ]
        errs = SpatialMerger._validate_inputs(pps, lns)
        self.assertTrue(any("R_h≤0" in e for e in errs))
        self.assertTrue(any("转角过小" in e for e in errs))
        self.assertTrue(any("弦长≤0" in e for e in errs))


class TestPlanProfileFormulaBulk(unittest.TestCase):
    def test_plan_arc_geometry_circle_equation_40_cases(self):
        case_id = 0
        for left in (True, False):
            for alpha in (8.0, 12.0, 20.0, 30.0, 45.0):
                for Rh in (200.0, 350.0, 500.0, 900.0):
                    case_id += 1
                    with self.subTest(case=case_id, left=left, alpha=alpha, Rh=Rh):
                        pps = _make_plan_single_arc(R_h=Rh, alpha_deg=alpha, left_turn=left)
                        segs = SpatialMerger._build_plan_segments(pps)
                        arc = next(sg for sg in segs if sg.seg_type == "ARC")
                        # s_BC / s_EC formula
                        expected_Lh = Rh * math.radians(alpha)
                        self.assertAlmostEqual(arc.s_start, 500.0 - expected_Lh / 2.0, places=6)
                        self.assertAlmostEqual(arc.s_end, 500.0 + expected_Lh / 2.0, places=6)
                        # circle equation at sampled points
                        for t in range(1, 10):
                            s = arc.s_start + (arc.s_end - arc.s_start) * t / 10.0
                            x, y, _ = SpatialMerger._eval_plan(segs, s)
                            r = math.hypot(x - arc.center[0], y - arc.center[1])
                            self.assertAlmostEqual(r, arc.R_h, delta=3e-1)

    def test_plan_alpha_matches_coordinate_derivative_30_cases(self):
        rng = random.Random(2026022801)
        for idx in range(30):
            left = rng.random() > 0.5
            alpha = rng.uniform(10.0, 55.0)
            Rh = rng.uniform(250.0, 1200.0)
            with self.subTest(case=idx, left=left, alpha=alpha):
                pps = _make_plan_single_arc(R_h=Rh, alpha_deg=alpha, left_turn=left)
                segs = SpatialMerger._build_plan_segments(pps)
                arc = next(sg for sg in segs if sg.seg_type == "ARC")
                for frac in (0.1, 0.3, 0.5, 0.7, 0.9):
                    s = arc.s_start + (arc.s_end - arc.s_start) * frac
                    h = 1e-3
                    x1, y1, _ = SpatialMerger._eval_plan(segs, s - h)
                    x2, y2, _ = SpatialMerger._eval_plan(segs, s + h)
                    alpha_fd = math.atan2(y2 - y1, x2 - x1)
                    _, _, alpha_eval = SpatialMerger._eval_plan(segs, s)
                    d = alpha_eval - alpha_fd
                    while d > math.pi:
                        d -= 2.0 * math.pi
                    while d <= -math.pi:
                        d += 2.0 * math.pi
                    self.assertLess(abs(d), 1e-4)

    def test_profile_arc_equation_and_derivative_40_cases(self):
        rng = random.Random(2026022802)
        for idx in range(40):
            Rv = rng.uniform(250.0, 1500.0)
            bb = math.radians(rng.uniform(-12.0, -2.0))
            ba = bb + math.radians(rng.uniform(2.0, 10.0))
            lns = _make_long_single_arc(
                s0=0.0,
                s1=1300.0,
                z0=100.0,
                arc_start=300.0,
                R_v=Rv,
                beta_before=bb,
                beta_after=ba,
            )
            with self.subTest(case=idx, Rv=Rv):
                segs = SpatialMerger._build_profile_segments(lns)
                arc = next(sg for sg in segs if sg.seg_type == "ARC")
                # endpoint matching
                z_s, _ = SpatialMerger._eval_profile(segs, arc.s_start)
                z_e, _ = SpatialMerger._eval_profile(segs, arc.s_end)
                self.assertAlmostEqual(z_s, lns[1].elevation, places=6)
                self.assertAlmostEqual(z_e, lns[2].elevation, places=6)
                # circle equation + derivative formula
                for frac in (0.1, 0.25, 0.5, 0.75, 0.9):
                    s = arc.s_start + (arc.s_end - arc.s_start) * frac
                    z, beta = SpatialMerger._eval_profile(segs, s)
                    self.assertLess(abs(beta), math.pi / 2)
                    r = math.hypot(s - arc.Sc, z - arc.Zc)
                    self.assertAlmostEqual(r, arc.R_v, places=6)
                    dz_ana = -(s - arc.Sc) / (z - arc.Zc)
                    h = 1e-4
                    z1, _ = SpatialMerger._eval_profile(segs, s - h)
                    z2, _ = SpatialMerger._eval_profile(segs, s + h)
                    dz_num = (z2 - z1) / (2.0 * h)
                    self.assertAlmostEqual(dz_num, dz_ana, delta=1e-3)


class TestLengthAndStationsBulk(unittest.TestCase):
    def test_piecewise_length_formula_60_cases(self):
        rng = random.Random(2026022803)
        for idx in range(60):
            # line + arc + line profile
            Rv = rng.uniform(300.0, 1000.0)
            bb = math.radians(rng.uniform(-10.0, -3.0))
            ba = bb + math.radians(rng.uniform(2.0, 8.0))
            lns = _make_long_single_arc(
                s0=0.0,
                s1=1300.0,
                z0=100.0,
                arc_start=250.0,
                R_v=Rv,
                beta_before=bb,
                beta_after=ba,
            )
            with self.subTest(case=idx):
                segs = SpatialMerger._build_profile_segments(lns)
                L = SpatialMerger._compute_spatial_length(segs, 0.0, 1300.0)
                arc = next(sg for sg in segs if sg.seg_type == "ARC")
                # manual expected: sum(line exact) + Rv*|Δbeta|
                z0 = lns[0].elevation
                z1 = lns[1].elevation
                z2 = lns[2].elevation
                z3 = lns[3].elevation
                L1 = math.sqrt((lns[1].chainage - lns[0].chainage) ** 2 + (z1 - z0) ** 2)
                L2 = arc.R_v * abs(ba - bb)
                L3 = math.sqrt((lns[3].chainage - lns[2].chainage) ** 2 + (z3 - z2) ** 2)
                self.assertAlmostEqual(L, L1 + L2 + L3, places=5)

    def test_station_set_contains_all_required_boundaries(self):
        pps = _make_plan_single_arc(R_h=500.0, alpha_deg=30.0, qz_s=520.0, left_turn=True)
        lns = _make_long_single_arc(
            s0=0.0,
            s1=1300.0,
            z0=100.0,
            arc_start=300.0,
            R_v=600.0,
            beta_before=math.radians(-8.0),
            beta_after=math.radians(3.0),
        )
        p_segs = SpatialMerger._build_plan_segments(pps)
        v_segs = SpatialMerger._build_profile_segments(lns)
        stations = SpatialMerger._build_station_set(
            p_segs, v_segs, long_nodes=lns, plan_points=pps
        )
        # Must include QZ (S_biz), profile arc endpoints, and all segment boundaries.
        self.assertTrue(any(abs(s - 520.0) <= SpatialMerger.STATION_EPS for s in stations))
        self.assertTrue(any(abs(s - lns[1].chainage) <= SpatialMerger.STATION_EPS for s in stations))
        self.assertTrue(any(abs(s - lns[2].chainage) <= SpatialMerger.STATION_EPS for s in stations))
        for sg in p_segs + v_segs:
            self.assertTrue(any(abs(s - sg.s_start) <= SpatialMerger.STATION_EPS for s in stations))
            self.assertTrue(any(abs(s - sg.s_end) <= SpatialMerger.STATION_EPS for s in stations))

    def test_unique_sorted_eps_bulk(self):
        vals = [0.0, 0.0002, 0.0008, 0.0011, 1.0, 1.0005, 2.0]
        uniq = SpatialMerger._unique_sorted_eps(vals)
        # 0.0/0.0002/0.0008 merged, 0.0011 separated; 1.0/1.0005 merged.
        self.assertEqual(len(uniq), 4)
        self.assertAlmostEqual(uniq[0], 0.0, places=6)
        self.assertAlmostEqual(uniq[1], 0.0011, places=6)
        self.assertAlmostEqual(uniq[2], 1.0, places=6)
        self.assertAlmostEqual(uniq[3], 2.0, places=6)


class TestEventsRigorousBulk(unittest.TestCase):
    def test_interval_split_merge_pattern(self):
        # plan arc: [100, 300], vertical arc: [200, 400]
        plan_evts = [
            BendEvent(s_a=100.0, s_b=300.0, event_type="PLAN", turn_style=TurnType.ARC, R_h=500.0)
        ]
        vert_evts = [
            BendEvent(
                s_a=200.0, s_b=400.0, event_type="VERTICAL", turn_style=TurnType.ARC, R_v=700.0
            )
        ]
        merged = SpatialMerger._merge_composite_events(plan_evts, vert_evts, [], [])
        arc = [e for e in merged if e.turn_style == TurnType.ARC]
        self.assertEqual(len(arc), 3)
        self.assertEqual((arc[0].event_type, arc[0].s_a, arc[0].s_b), ("PLAN", 100.0, 200.0))
        self.assertEqual((arc[1].event_type, arc[1].s_a, arc[1].s_b), ("COMPOSITE", 200.0, 300.0))
        self.assertEqual((arc[2].event_type, arc[2].s_a, arc[2].s_b), ("VERTICAL", 300.0, 400.0))

    def test_fold_same_station_aggregates_to_one_composite(self):
        pps = [
            PlanFeaturePoint(chainage=0.0, x=0.0, y=0.0, azimuth_meas_deg=90.0, turn_type=TurnType.NONE),
            PlanFeaturePoint(
                chainage=250.0,
                x=250.0,
                y=0.0,
                azimuth_meas_deg=90.0,
                turn_angle=20.0,
                turn_type=TurnType.FOLD,
            ),
            PlanFeaturePoint(chainage=400.0, x=390.0, y=40.0, azimuth_meas_deg=75.0, turn_type=TurnType.NONE),
        ]
        lns = [
            LongitudinalNode(chainage=0.0, elevation=100.0, turn_type=TurnType.NONE, slope_after=0.0),
            LongitudinalNode(
                chainage=250.0,
                elevation=100.0,
                turn_type=TurnType.FOLD,
                turn_angle=6.0,
                slope_before=math.radians(-3.0),
                slope_after=math.radians(3.0),
            ),
            LongitudinalNode(chainage=400.0, elevation=103.0, turn_type=TurnType.NONE, slope_before=0.0),
        ]
        res = SpatialMerger.merge_and_compute(pps, lns, verbose=False)
        folds = [
            e
            for e in res.bend_events
            if e.turn_style == TurnType.FOLD and abs(e.s_a - 250.0) <= SpatialMerger.STATION_EPS
        ]
        self.assertEqual(len(folds), 1)
        self.assertEqual(folds[0].event_type, "COMPOSITE")

    def test_reff_definition_bulk_40_cases(self):
        rng = random.Random(2026022804)
        for idx in range(40):
            Rh = rng.uniform(250.0, 900.0)
            alpha = rng.uniform(8.0, 45.0)
            k = rng.uniform(-0.06, 0.06)
            pps = _make_plan_single_arc(R_h=Rh, alpha_deg=alpha, left_turn=(rng.random() > 0.5))
            lns = _make_long_const_slope(0.0, 1300.0, 100.0, k)
            with self.subTest(case=idx):
                res = SpatialMerger.merge_and_compute(pps, lns, verbose=False)
                for ev in res.bend_events:
                    if ev.turn_style == TurnType.ARC and ev.theta_event > 1e-9:
                        self.assertAlmostEqual(ev.R_eff, ev.L_event / ev.theta_event, places=9)

    def test_arc_event_zero_theta_gives_infinite_radius(self):
        plan = [PlanSegment(seg_type="LINE", s_start=0.0, s_end=100.0, p_start=(0.0, 0.0), direction=(1.0, 0.0))]
        prof = [ProfileSegment(seg_type="LINE", s_start=0.0, s_end=100.0, z_start=100.0, k=0.0)]
        events = [BendEvent(s_a=10.0, s_b=20.0, event_type="PLAN", turn_style=TurnType.ARC)]
        SpatialMerger._compute_event_properties(events, plan, prof)
        self.assertAlmostEqual(events[0].theta_event, 0.0, places=12)
        self.assertTrue(math.isinf(events[0].R_eff))


class TestRandomizedRigorousStress(unittest.TestCase):
    def test_randomized_200_cases(self):
        rng = random.Random(2026022805)
        total_cases = 200
        for idx in range(total_cases):
            s0, s1 = 0.0, 1300.0

            # Plan
            if rng.random() < 0.75:
                pps = _make_plan_single_arc(
                    R_h=rng.uniform(220.0, 800.0),
                    alpha_deg=rng.uniform(6.0, 40.0),
                    left_turn=(rng.random() > 0.5),
                )
            else:
                pps = _make_plan_straight(s0, s1)

            # Profile
            if rng.random() < 0.75:
                bb = math.radians(rng.uniform(-12.0, -1.0))
                ba = bb + math.radians(rng.uniform(2.0, 10.0))
                lns = _make_long_single_arc(
                    s0=s0,
                    s1=s1,
                    z0=100.0 + rng.uniform(-20.0, 20.0),
                    arc_start=300.0,
                    R_v=rng.uniform(280.0, 1200.0),
                    beta_before=bb,
                    beta_after=ba,
                )
                # Keep only valid increasing arc interval; otherwise fallback.
                if lns[2].chainage <= lns[1].chainage + 1e-3 or lns[2].chainage >= s1 - 1.0:
                    lns = _make_long_const_slope(s0, s1, 100.0, rng.uniform(-0.08, 0.08))
            else:
                lns = _make_long_const_slope(s0, s1, 100.0, rng.uniform(-0.08, 0.08))

            with self.subTest(case=idx):
                res = SpatialMerger.merge_and_compute(pps, lns, verbose=False)

                self.assertGreaterEqual(len(res.nodes), 2)
                # chainage monotonic
                for i in range(len(res.nodes) - 1):
                    self.assertGreater(res.nodes[i + 1].chainage, res.nodes[i].chainage)
                # unit tangent
                for nd in res.nodes:
                    for T in (nd.T_before, nd.T_after):
                        mag = math.sqrt(T[0] ** 2 + T[1] ** 2 + T[2] ** 2)
                        self.assertAlmostEqual(mag, 1.0, places=9)
                # L_spatial >= horizontal range
                horiz = res.nodes[-1].chainage - res.nodes[0].chainage
                self.assertGreaterEqual(res.total_spatial_length + 1e-6, horiz)
                # event semantics
                for ev in res.bend_events:
                    self.assertFalse(math.isnan(ev.theta_event))
                    self.assertFalse(math.isnan(ev.L_event))
                    if ev.turn_style == TurnType.FOLD:
                        self.assertAlmostEqual(ev.L_event, 0.0, places=12)
                        self.assertAlmostEqual(ev.R_eff, 0.0, places=12)
                    elif ev.theta_event > 1e-9:
                        self.assertAlmostEqual(ev.R_eff, ev.L_event / ev.theta_event, places=9)


if __name__ == "__main__":
    unittest.main()
