# -*- coding: utf-8 -*-
"""
Spatial merger strict-math accuracy report generator.

Purpose:
- Run deterministic benchmark cases with exact references.
- Generate machine-readable JSON and human-readable Markdown reports.
- Return non-zero exit code when thresholds are violated.

Usage:
    python tools/spatial_accuracy_report.py
    python tools/spatial_accuracy_report.py --output-dir dist/qa
    python tools/spatial_accuracy_report.py --case-a 800 --case-b 800 --robust 2000
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from statistics import mean
from typing import List, Optional, Tuple


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)


def _find_module_dir(root: str) -> str:
    """Find folder containing siphon_models.py to avoid path encoding issues."""
    for dp, _, fns in os.walk(root):
        if "siphon_models.py" in fns and os.path.basename(dp) != "tests":
            return dp
    raise RuntimeError("Cannot locate siphon_models.py")


MODULE_DIR = _find_module_dir(PROJECT_ROOT)
sys.path.insert(0, MODULE_DIR)

from siphon_models import LongitudinalNode, PlanFeaturePoint, TurnType  # noqa: E402
from spatial_merger import SpatialMerger  # noqa: E402


@dataclass
class Thresholds:
    theta_max_rad: float = 1e-9
    length_max_m: float = 1e-8
    reff_max_m: float = 1e-6
    unit_tangent_max: float = 1e-12
    length_deficit_max: float = 1e-10


@dataclass
class Stats:
    sample_count: int
    max_value: float
    mean_value: float


@dataclass
class Report:
    generated_at: str
    seed: int
    case_a_samples: int
    case_b_samples: int
    robust_samples: int
    case_a_theta_err_rad: Stats
    case_a_length_err_m: Stats
    case_a_reff_err_m: Stats
    case_b_theta_err_rad: Stats
    case_b_length_err_m: Stats
    case_b_reff_err_m: Stats
    robust_unit_tangent_norm_err: float
    robust_length_deficit_m: float
    thresholds: Thresholds
    passed: bool
    failed_checks: List[str]


def _meas_from_alpha(alpha_math_rad: float) -> float:
    return 90.0 - math.degrees(alpha_math_rad)


def _make_plan_arc(
    radius_h: float,
    alpha_deg: float,
    left_turn: bool,
    qz_s: float = 500.0,
    s0: float = 0.0,
    s1: float = 1300.0,
) -> List[PlanFeaturePoint]:
    ip0 = (0.0, 0.0)
    ip1 = (500.0, 0.0)
    sign = 1.0 if left_turn else -1.0
    out_alpha = sign * math.radians(alpha_deg)
    d_out = (math.cos(out_alpha), math.sin(out_alpha))
    ip2 = (ip1[0] + 800.0 * d_out[0], ip1[1] + 800.0 * d_out[1])
    az2 = _meas_from_alpha(math.atan2(d_out[1], d_out[0]))
    return [
        PlanFeaturePoint(
            chainage=s0, x=ip0[0], y=ip0[1], azimuth_meas_deg=90.0, turn_type=TurnType.NONE
        ),
        PlanFeaturePoint(
            chainage=qz_s,
            x=ip1[0],
            y=ip1[1],
            azimuth_meas_deg=90.0,
            turn_angle=alpha_deg,
            turn_radius=radius_h,
            turn_type=TurnType.ARC,
        ),
        PlanFeaturePoint(
            chainage=s1, x=ip2[0], y=ip2[1], azimuth_meas_deg=az2, turn_type=TurnType.NONE
        ),
    ]


def _make_plan_straight(s0: float = 0.0, s1: float = 1300.0) -> List[PlanFeaturePoint]:
    return [
        PlanFeaturePoint(chainage=s0, x=s0, y=0.0, azimuth_meas_deg=90.0, turn_type=TurnType.NONE),
        PlanFeaturePoint(chainage=s1, x=s1, y=0.0, azimuth_meas_deg=90.0, turn_type=TurnType.NONE),
    ]


def _make_long_const_slope(
    slope_k: float, s0: float = 0.0, s1: float = 1300.0, z0: float = 100.0
) -> List[LongitudinalNode]:
    beta = math.atan(slope_k)
    return [
        LongitudinalNode(chainage=s0, elevation=z0, turn_type=TurnType.NONE, slope_after=beta),
        LongitudinalNode(
            chainage=s1, elevation=z0 + (s1 - s0) * slope_k, turn_type=TurnType.NONE, slope_before=beta
        ),
    ]


def _make_long_arc(
    radius_v: float,
    beta_before: float,
    beta_after: float,
    s0: float = 0.0,
    s1: float = 1300.0,
    arc_start: float = 300.0,
    z0: float = 100.0,
) -> List[LongitudinalNode]:
    z_start = z0 + (arc_start - s0) * math.tan(beta_before)
    sc = arc_start - radius_v * math.sin(beta_before)
    zc = z_start + radius_v * math.cos(beta_before)
    arc_end = sc + radius_v * math.sin(beta_after)
    z_end = zc - radius_v * math.cos(beta_after)
    z_final = z_end + (s1 - arc_end) * math.tan(beta_after)
    theta = abs(beta_after - beta_before)
    return [
        LongitudinalNode(chainage=s0, elevation=z0, turn_type=TurnType.NONE, slope_after=beta_before),
        LongitudinalNode(
            chainage=arc_start,
            elevation=z_start,
            turn_type=TurnType.ARC,
            vertical_curve_radius=radius_v,
            turn_angle=math.degrees(theta),
            slope_before=beta_before,
            slope_after=beta_after,
            arc_center_s=sc,
            arc_center_z=zc,
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
        LongitudinalNode(chainage=s1, elevation=z_final, turn_type=TurnType.NONE, slope_before=beta_after),
    ]


def _stats(values: List[float]) -> Stats:
    if not values:
        return Stats(sample_count=0, max_value=float("nan"), mean_value=float("nan"))
    return Stats(sample_count=len(values), max_value=max(values), mean_value=mean(values))


def _case_a_case_b_errors(
    rng: random.Random, case_a_count: int, case_b_count: int
) -> Tuple[List[float], List[float], List[float], List[float], List[float], List[float]]:
    # Case A: plan arc + constant slope (closed-form reference).
    err_theta_a, err_len_a, err_reff_a = [], [], []
    for _ in range(case_a_count):
        # Keep arc interval valid within [0, 1300] by bounding alpha and Rh.
        radius_h = rng.uniform(120.0, 1200.0)
        alpha_deg = rng.uniform(2.0, 40.0)
        slope_k = rng.uniform(-0.12, 0.12)
        left_turn = rng.random() > 0.5

        plan_points = _make_plan_arc(radius_h, alpha_deg, left_turn)
        long_nodes = _make_long_const_slope(slope_k)
        result = SpatialMerger.merge_and_compute(plan_points, long_nodes, verbose=False)
        events = [e for e in result.bend_events if e.event_type == "PLAN" and e.turn_style == TurnType.ARC]
        if len(events) != 1:
            raise RuntimeError(f"Case A expects exactly 1 PLAN ARC event, got {len(events)}")

        event = events[0]
        alpha = math.radians(alpha_deg)
        beta = math.atan(slope_k)
        theta_ref = math.acos(
            max(-1.0, min(1.0, math.cos(beta) ** 2 * math.cos(alpha) + math.sin(beta) ** 2))
        )
        length_ref = radius_h * alpha * math.sqrt(1.0 + slope_k * slope_k)
        reff_ref = length_ref / theta_ref if theta_ref > 1e-12 else float("inf")

        err_theta_a.append(abs(event.theta_event - theta_ref))
        err_len_a.append(abs(event.L_event - length_ref))
        err_reff_a.append(abs(event.R_eff - reff_ref))

    # Case B: pure vertical arc + straight plan (closed-form reference).
    err_theta_b, err_len_b, err_reff_b = [], [], []
    for _ in range(case_b_count):
        radius_v = rng.uniform(180.0, 1200.0)
        beta_before = math.radians(rng.uniform(-12.0, -2.0))
        beta_after = beta_before + math.radians(rng.uniform(1.0, 8.0))

        plan_points = _make_plan_straight()
        long_nodes = _make_long_arc(radius_v, beta_before, beta_after)
        result = SpatialMerger.merge_and_compute(plan_points, long_nodes, verbose=False)
        events = [e for e in result.bend_events if e.event_type == "VERTICAL" and e.turn_style == TurnType.ARC]
        if len(events) != 1:
            raise RuntimeError(f"Case B expects exactly 1 VERTICAL ARC event, got {len(events)}")

        event = events[0]
        theta_ref = abs(beta_after - beta_before)
        length_ref = radius_v * theta_ref
        reff_ref = radius_v

        err_theta_b.append(abs(event.theta_event - theta_ref))
        err_len_b.append(abs(event.L_event - length_ref))
        err_reff_b.append(abs(event.R_eff - reff_ref))

    return err_theta_a, err_len_a, err_reff_a, err_theta_b, err_len_b, err_reff_b


def _robustness_checks(rng: random.Random, robust_count: int) -> Tuple[float, float]:
    max_unit_norm_err = 0.0
    max_length_deficit = 0.0

    for _ in range(robust_count):
        if rng.random() < 0.7:
            plan_points = _make_plan_arc(
                radius_h=rng.uniform(120.0, 1200.0),
                alpha_deg=rng.uniform(2.0, 40.0),
                left_turn=(rng.random() > 0.5),
            )
        else:
            plan_points = _make_plan_straight()

        if rng.random() < 0.7:
            long_nodes = None
            # Generate a valid vertical arc fully inside [0, 1300].
            for _ in range(20):
                beta_before = math.radians(rng.uniform(-12.0, -1.0))
                beta_after = beta_before + math.radians(rng.uniform(1.0, 10.0))
                candidate = _make_long_arc(
                    radius_v=rng.uniform(180.0, 1500.0),
                    beta_before=beta_before,
                    beta_after=beta_after,
                )
                arc_start = candidate[1].chainage
                arc_end = candidate[2].chainage
                if arc_start + 1e-6 < arc_end < candidate[-1].chainage - 1e-6:
                    long_nodes = candidate
                    break
            if long_nodes is None:
                long_nodes = _make_long_const_slope(rng.uniform(-0.1, 0.1))
        else:
            long_nodes = _make_long_const_slope(rng.uniform(-0.1, 0.1))

        result = SpatialMerger.merge_and_compute(plan_points, long_nodes, verbose=False)

        for nd in result.nodes:
            for vec in (nd.T_before, nd.T_after):
                mag = math.sqrt(vec[0] * vec[0] + vec[1] * vec[1] + vec[2] * vec[2])
                max_unit_norm_err = max(max_unit_norm_err, abs(mag - 1.0))

        horizontal = result.nodes[-1].chainage - result.nodes[0].chainage
        max_length_deficit = max(max_length_deficit, max(0.0, horizontal - result.total_spatial_length))

    return max_unit_norm_err, max_length_deficit


def _evaluate_thresholds(report: Report) -> Tuple[bool, List[str]]:
    th = report.thresholds
    failed: List[str] = []

    if report.case_a_theta_err_rad.max_value > th.theta_max_rad:
        failed.append(
            f"case_a_theta_err_rad.max={report.case_a_theta_err_rad.max_value:.3e} > {th.theta_max_rad:.3e}"
        )
    if report.case_a_length_err_m.max_value > th.length_max_m:
        failed.append(
            f"case_a_length_err_m.max={report.case_a_length_err_m.max_value:.3e} > {th.length_max_m:.3e}"
        )
    if report.case_a_reff_err_m.max_value > th.reff_max_m:
        failed.append(
            f"case_a_reff_err_m.max={report.case_a_reff_err_m.max_value:.3e} > {th.reff_max_m:.3e}"
        )

    if report.case_b_theta_err_rad.max_value > th.theta_max_rad:
        failed.append(
            f"case_b_theta_err_rad.max={report.case_b_theta_err_rad.max_value:.3e} > {th.theta_max_rad:.3e}"
        )
    if report.case_b_length_err_m.max_value > th.length_max_m:
        failed.append(
            f"case_b_length_err_m.max={report.case_b_length_err_m.max_value:.3e} > {th.length_max_m:.3e}"
        )
    if report.case_b_reff_err_m.max_value > th.reff_max_m:
        failed.append(
            f"case_b_reff_err_m.max={report.case_b_reff_err_m.max_value:.3e} > {th.reff_max_m:.3e}"
        )

    if report.robust_unit_tangent_norm_err > th.unit_tangent_max:
        failed.append(
            f"robust_unit_tangent_norm_err={report.robust_unit_tangent_norm_err:.3e} > {th.unit_tangent_max:.3e}"
        )
    if report.robust_length_deficit_m > th.length_deficit_max:
        failed.append(
            f"robust_length_deficit_m={report.robust_length_deficit_m:.3e} > {th.length_deficit_max:.3e}"
        )

    return (len(failed) == 0), failed


def _render_markdown(report: Report) -> str:
    status = "PASS" if report.passed else "FAIL"
    lines = [
        "# Spatial Accuracy Report",
        "",
        f"- Generated At: `{report.generated_at}`",
        f"- Seed: `{report.seed}`",
        f"- Status: **{status}**",
        "",
        "## Sample Sizes",
        "",
        f"- Case A (Plan ARC + Const Slope): `{report.case_a_samples}`",
        f"- Case B (Vertical ARC + Straight Plan): `{report.case_b_samples}`",
        f"- Robustness Random Cases: `{report.robust_samples}`",
        "",
        "## Error Metrics",
        "",
        "| Metric | Max | Mean |",
        "|---|---:|---:|",
        f"| Case A θ error (rad) | `{report.case_a_theta_err_rad.max_value:.3e}` | `{report.case_a_theta_err_rad.mean_value:.3e}` |",
        f"| Case A L error (m) | `{report.case_a_length_err_m.max_value:.3e}` | `{report.case_a_length_err_m.mean_value:.3e}` |",
        f"| Case A R_eff error (m) | `{report.case_a_reff_err_m.max_value:.3e}` | `{report.case_a_reff_err_m.mean_value:.3e}` |",
        f"| Case B θ error (rad) | `{report.case_b_theta_err_rad.max_value:.3e}` | `{report.case_b_theta_err_rad.mean_value:.3e}` |",
        f"| Case B L error (m) | `{report.case_b_length_err_m.max_value:.3e}` | `{report.case_b_length_err_m.mean_value:.3e}` |",
        f"| Case B R_eff error (m) | `{report.case_b_reff_err_m.max_value:.3e}` | `{report.case_b_reff_err_m.mean_value:.3e}` |",
        f"| Robust `max ||T|-1|` | `{report.robust_unit_tangent_norm_err:.3e}` | `-` |",
        f"| Robust `max(L_horizontal-L)` | `{report.robust_length_deficit_m:.3e}` | `-` |",
        "",
        "## Thresholds",
        "",
        f"- θ max error (rad): `{report.thresholds.theta_max_rad:.3e}`",
        f"- L max error (m): `{report.thresholds.length_max_m:.3e}`",
        f"- R_eff max error (m): `{report.thresholds.reff_max_m:.3e}`",
        f"- Unit tangent max error: `{report.thresholds.unit_tangent_max:.3e}`",
        f"- Length deficit max (m): `{report.thresholds.length_deficit_max:.3e}`",
        "",
        "## Failed Checks",
        "",
    ]
    if report.failed_checks:
        for item in report.failed_checks:
            lines.append(f"- `{item}`")
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def _save_report(output_dir: str, report: Report) -> Tuple[str, str]:
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    latest_json = os.path.join(output_dir, "spatial_accuracy_report_latest.json")
    latest_md = os.path.join(output_dir, "spatial_accuracy_report_latest.md")
    archived_json = os.path.join(output_dir, f"spatial_accuracy_report_{ts}.json")
    archived_md = os.path.join(output_dir, f"spatial_accuracy_report_{ts}.md")

    payload = asdict(report)
    with open(latest_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with open(archived_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    markdown = _render_markdown(report)
    with open(latest_md, "w", encoding="utf-8") as f:
        f.write(markdown)
    with open(archived_md, "w", encoding="utf-8") as f:
        f.write(markdown)

    return latest_md, latest_json


def run_benchmark(
    seed: int, case_a_count: int, case_b_count: int, robust_count: int, thresholds: Thresholds
) -> Report:
    rng = random.Random(seed)

    (
        err_theta_a,
        err_len_a,
        err_reff_a,
        err_theta_b,
        err_len_b,
        err_reff_b,
    ) = _case_a_case_b_errors(rng, case_a_count, case_b_count)

    robust_unit, robust_len_def = _robustness_checks(rng, robust_count)

    report = Report(
        generated_at=datetime.now().isoformat(timespec="seconds"),
        seed=seed,
        case_a_samples=case_a_count,
        case_b_samples=case_b_count,
        robust_samples=robust_count,
        case_a_theta_err_rad=_stats(err_theta_a),
        case_a_length_err_m=_stats(err_len_a),
        case_a_reff_err_m=_stats(err_reff_a),
        case_b_theta_err_rad=_stats(err_theta_b),
        case_b_length_err_m=_stats(err_len_b),
        case_b_reff_err_m=_stats(err_reff_b),
        robust_unit_tangent_norm_err=robust_unit,
        robust_length_deficit_m=robust_len_def,
        thresholds=thresholds,
        passed=False,
        failed_checks=[],
    )
    passed, failed = _evaluate_thresholds(report)
    report.passed = passed
    report.failed_checks = failed
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate strict-math spatial accuracy report.")
    parser.add_argument("--output-dir", default=os.path.join("dist", "qa"), help="Report output directory")
    parser.add_argument("--seed", type=int, default=2026022807, help="Random seed")
    parser.add_argument("--case-a", type=int, default=500, help="Case A sample count")
    parser.add_argument("--case-b", type=int, default=500, help="Case B sample count")
    parser.add_argument("--robust", type=int, default=1000, help="Robustness sample count")
    parser.add_argument("--theta-max", type=float, default=1e-9, help="Theta max error threshold (rad)")
    parser.add_argument("--length-max", type=float, default=1e-8, help="Length max error threshold (m)")
    parser.add_argument("--reff-max", type=float, default=1e-6, help="R_eff max error threshold (m)")
    parser.add_argument("--unit-max", type=float, default=1e-12, help="Unit tangent max error threshold")
    parser.add_argument(
        "--length-deficit-max", type=float, default=1e-10, help="Horizontal-length deficit threshold (m)"
    )
    args = parser.parse_args()

    thresholds = Thresholds(
        theta_max_rad=args.theta_max,
        length_max_m=args.length_max,
        reff_max_m=args.reff_max,
        unit_tangent_max=args.unit_max,
        length_deficit_max=args.length_deficit_max,
    )

    report = run_benchmark(
        seed=args.seed,
        case_a_count=args.case_a,
        case_b_count=args.case_b,
        robust_count=args.robust,
        thresholds=thresholds,
    )
    latest_md, latest_json = _save_report(args.output_dir, report)

    print("=== Spatial Accuracy Validation ===")
    print(f"status: {'PASS' if report.passed else 'FAIL'}")
    print(f"report_md: {latest_md}")
    print(f"report_json: {latest_json}")
    print(
        f"case_a theta_max={report.case_a_theta_err_rad.max_value:.3e}, "
        f"length_max={report.case_a_length_err_m.max_value:.3e}, "
        f"reff_max={report.case_a_reff_err_m.max_value:.3e}"
    )
    print(
        f"case_b theta_max={report.case_b_theta_err_rad.max_value:.3e}, "
        f"length_max={report.case_b_length_err_m.max_value:.3e}, "
        f"reff_max={report.case_b_reff_err_m.max_value:.3e}"
    )
    print(
        f"robust unit_max={report.robust_unit_tangent_norm_err:.3e}, "
        f"length_deficit_max={report.robust_length_deficit_m:.3e}"
    )
    if report.failed_checks:
        print("failed_checks:")
        for item in report.failed_checks:
            print(f"  - {item}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
