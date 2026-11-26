# -*- coding: utf-8 -*-
"""用独立来源的局部地形趋势筛查明显高程错误，原资料和通过来源不变。

只对诊断参考点作空间取样；输出保留来源的全部原 XYZ。等高线必须有
沿线多数一致的外部证据才整条剔除，不能用同一条密集折线证明自身正确。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree


DEFAULT_POLICY = {
    "absolute_error_m": 20.0,
    "robust_sigma_factor": 8.0,
    "robust_fit_iterations": 6,
    "neighbor_count": 64,
    "minimum_neighbors": 8,
    "minimum_independent_sources": 4,
    "max_neighbor_distance_m": 200.0,
    "reference_spacing_m": 5.0,
    "scatter_reference_spacing_m": 5.0,
    "contour_probe_count": 16,
    "contour_error_fraction": 0.8,
    "batch_size": 1024,
}


def _check(token):
    if token is not None:
        token.raise_if_cancelled()


def _policy(value):
    policy = {**DEFAULT_POLICY, **(value or {})}
    unknown = set(policy) - set(DEFAULT_POLICY)
    if unknown:
        raise ValueError("未知地形高程筛查参数：" + ", ".join(sorted(unknown)))
    for key, number in policy.items():
        if not np.isfinite(number) or number <= 0:
            raise ValueError(f"高程筛查参数 {key} 必须有限且大于零")
    for key in ("neighbor_count", "minimum_neighbors", "minimum_independent_sources", "contour_probe_count", "batch_size", "robust_fit_iterations"):
        if int(policy[key]) != policy[key]:
            raise ValueError(f"高程筛查参数 {key} 必须为整数")
        policy[key] = int(policy[key])
    if policy["minimum_neighbors"] > policy["neighbor_count"] or not 0.5 < policy["contour_error_fraction"] <= 1:
        raise ValueError("高程筛查的邻点数或等高线多数比例无效")
    return policy


def _positions(source):
    points = np.asarray(source.get("points", []), dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or not len(points):
        raise ValueError("地形来源必须包含至少一个三维点")
    if not np.isfinite(points).all():
        raise ValueError("地形来源含非有限三维坐标")
    if source.get("kind") not in ("point", "polyline"):
        raise ValueError("高程筛查仅接收 point 或 polyline 来源")
    if source["kind"] == "point" and len(points) != 1:
        raise ValueError("point 地形来源必须只有一个点")
    return points


def _sample_indices(points, spacing, maximum=None):
    """诊断取样选择原顶点，不产生或改变输入高程。"""
    if len(points) <= 2:
        return np.arange(len(points))
    lengths = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(points[:, :2], axis=0), axis=1))]
    if lengths[-1] <= 1e-9:
        return np.array([0, len(points) - 1])
    count = min(len(points), max(2, int(np.ceil(lengths[-1] / spacing)) + 1))
    if maximum is not None:
        count = min(count, maximum)
    return np.unique(np.searchsorted(lengths, np.linspace(0, lengths[-1], count)))


def _reference_and_probes(sources, policy, token):
    # 点实体可能有百万条；预分配数值数组，避免为每点保留四个小 ndarray。
    contour_samples, vertex_counts = {}, []
    reference_count = probe_count = 0
    for index, source in enumerate(sources):
        if index % 64 == 0:
            _check(token)
        vertex_counts.append(len(source.get("points", [])))
        if source.get("kind") == "point":
            reference_count += 1
            probe_count += 1
        else:
            points = _positions(source)
            reference_indices = _sample_indices(points, policy["reference_spacing_m"])
            probe_indices = _sample_indices(points, policy["reference_spacing_m"], policy["contour_probe_count"])
            contour_samples[index] = reference_indices, probe_indices
            reference_count += len(reference_indices)
            probe_count += len(probe_indices)
    reference = np.empty((reference_count, 3))
    reference_sources = np.empty(reference_count, dtype=np.int64)
    probes = np.empty((probe_count, 3))
    probe_sources = np.empty(probe_count, dtype=np.int64)
    reference_offset = probe_offset = 0
    for index, source in enumerate(sources):
        if index % 256 == 0:
            _check(token)
        points = _positions(source)
        if source["kind"] == "point":
            reference[reference_offset] = probes[probe_offset] = points[0]
            reference_sources[reference_offset] = probe_sources[probe_offset] = index
            reference_offset += 1
            probe_offset += 1
        else:
            reference_indices, probe_indices = contour_samples[index]
            stop = reference_offset + len(reference_indices)
            reference[reference_offset:stop] = points[reference_indices]
            reference_sources[reference_offset:stop] = index
            reference_offset = stop
            stop = probe_offset + len(probe_indices)
            probes[probe_offset:stop] = points[probe_indices]
            probe_sources[probe_offset:stop] = index
            probe_offset = stop
    # 无等高线来源身份的裸点云也须避免一条极密错误线互相证明自身正确。
    # 仅诊断参考在 XY 网格每格选距格中心最近的一个原点，全部原点仍逐一检查。
    is_point_source = np.fromiter((source["kind"] == "point" for source in sources), dtype=bool, count=len(sources))
    scatter_indices = np.flatnonzero(is_point_source[reference_sources])
    effective_spacing = policy["scatter_reference_spacing_m"]
    scatter_reference_count = 0
    if len(scatter_indices):
        _check(token)
        xy = reference[scatter_indices, :2]
        target_count = min(policy["neighbor_count"], len(scatter_indices))
        unique_target_checked = False
        while True:
            _check(token)
            cells = np.floor(xy / effective_spacing)
            center_distance = np.sum((xy - (cells + 0.5) * effective_spacing) ** 2, axis=1)
            order = np.lexsort((reference_sources[scatter_indices], center_distance, cells[:, 1], cells[:, 0]))
            ordered_cells = cells[order]
            first_in_cell = np.r_[True, np.any(ordered_cells[1:] != ordered_cells[:-1], axis=1)]
            selected = scatter_indices[order[first_in_cell]]
            if len(selected) >= target_count:
                break
            if not unique_target_checked:
                # 重合位置不能凭无限缩小网格制造新参考；仅查到目标数即停止。
                unique_xy = set()
                for point in xy:
                    unique_xy.add((point[0], point[1]))
                    if len(unique_xy) >= target_count:
                        break
                target_count = min(target_count, len(unique_xy))
                unique_target_checked = True
                if len(selected) >= target_count:
                    break
            effective_spacing /= 2
        scatter_reference_count = len(selected)
        keep = ~is_point_source[reference_sources]
        keep[selected] = True
        reference, reference_sources = reference[keep], reference_sources[keep]
    diagnostics = {"scatter_reference_spacing_m_effective": effective_spacing,
                   "scatter_input_point_count": len(scatter_indices),
                   "scatter_reference_point_count": scatter_reference_count,
                   "scatter_reference_rule": "original_point_nearest_cell_center; halve_spacing_until_minimum_reference_count"}
    return reference, reference_sources, probes, probe_sources, vertex_counts, diagnostics


def _local_evidence(tree, reference, reference_sources, probes, probe_sources, policy, token):
    """分批拟合局部稳健平面，内存随 batch×neighbor 增长而非点数平方。"""
    total = len(probes)
    evaluated = np.zeros(total, dtype=bool)
    errors = np.zeros(total, dtype=bool)
    residuals = np.zeros(total)
    thresholds = np.zeros(total)
    independent_counts = np.zeros(total, dtype=np.int32)
    nearest_distances = np.zeros(total)
    k = min(policy["neighbor_count"], len(reference))
    if k < policy["minimum_neighbors"]:
        return evaluated, errors, residuals, thresholds, independent_counts, nearest_distances
    for start in range(0, total, policy["batch_size"]):
        _check(token)
        stop = min(total, start + policy["batch_size"])
        target = probes[start:stop]
        distance, indices = tree.query(target[:, :2], k=k, workers=1)
        source_ids = reference_sources[indices]
        usable = ((source_ids != probe_sources[start:stop, None]) & (distance > 1e-6)
                  & (distance <= policy["max_neighbor_distance_m"]))
        # 每个来源总权重相同，密集线顶点不能淹没若干实测 GCD 点。
        same_source = source_ids[:, :, None] == source_ids[:, None, :]
        per_source_count = np.sum(same_source & usable[:, None, :], axis=2)
        weights = usable / np.maximum(1, per_source_count)
        distinct = np.rint(weights.sum(axis=1)).astype(np.int32)
        sufficient = ((usable.sum(axis=1) >= policy["minimum_neighbors"])
                      & (distinct >= policy["minimum_independent_sources"]))
        xy = reference[indices, :2] - target[:, None, :2]
        scale = np.maximum(np.max(np.where(usable, distance, 0), axis=1), 1)
        design = np.concatenate((xy / scale[:, None, None], np.ones((*xy.shape[:2], 1))), axis=2)
        z = reference[indices, 2]
        # 减去邻域中值保持大地坐标和高程的数值稳定。
        usable_z = np.where(usable, z, np.nan)
        usable_z[~usable.any(axis=1), 0] = 0
        with np.errstate(all="ignore"):
            center_z = np.nanmedian(usable_z, axis=1)
        center_z = np.nan_to_num(center_z)
        shifted_z = z - center_z[:, None]
        working_weights = weights.copy()
        coeff = np.zeros((len(target), 3))
        for _iteration in range(policy["robust_fit_iterations"]):
            matrix = np.einsum("bki,bk,bkj->bij", design, working_weights, design)
            rhs = np.einsum("bki,bk,bk->bi", design, working_weights, shifted_z)
            # 无支持/共线行保留输入；微小正规化只用于批量求解不抛异常。
            matrix += np.eye(3)[None, :, :] * 1e-10
            coeff = np.linalg.solve(matrix, rhs[..., None])[..., 0]
            fit_residual = shifted_z - np.einsum("bki,bi->bk", design, coeff)
            masked = np.where(usable, fit_residual, np.nan)
            masked[~usable.any(axis=1), 0] = 0
            with np.errstate(all="ignore"):
                median = np.nanmedian(masked, axis=1)
                mad = np.nanmedian(np.abs(masked - median[:, None]), axis=1)
            mad = np.nan_to_num(mad)
            cutoff = np.maximum(1.0, 3 * 1.4826 * mad)
            working_weights = weights * np.minimum(1, cutoff[:, None] / np.maximum(np.abs(fit_residual), 1e-12))
        # 在两维都得到支持；避免沿单条直线外推删除真实山脊/图边点。
        normal = np.einsum("bki,bk,bkj->bij", design, working_weights, design)
        eigen = np.linalg.eigvalsh(normal)
        sufficient &= eigen[:, 0] > np.maximum(1e-8, eigen[:, -1] * 1e-4)
        minimum = np.min(np.where(usable[:, :, None], xy, np.inf), axis=1)
        maximum = np.max(np.where(usable[:, :, None], xy, -np.inf), axis=1)
        sufficient &= np.all((minimum <= 1e-6) & (maximum >= -1e-6), axis=1)
        prediction = center_z + coeff[:, 2]
        delta = target[:, 2] - prediction
        # 除绝对明显差值外还须超过实际邻域起伏，陡坡和破碎地形从严保留。
        threshold = np.maximum(policy["absolute_error_m"], policy["robust_sigma_factor"] * 1.4826 * mad)
        enough_inliers = np.sum(usable & (np.abs(fit_residual) <= np.maximum(2.0, 3 * 1.4826 * mad[:, None])), axis=1)
        sufficient &= enough_inliers >= policy["minimum_neighbors"]
        evaluated[start:stop] = sufficient
        errors[start:stop] = sufficient & (np.abs(delta) > threshold)
        residuals[start:stop] = delta
        thresholds[start:stop] = threshold
        independent_counts[start:stop] = distinct
        nearest_distances[start:stop] = np.min(np.where(usable, distance, np.inf), axis=1)
    return evaluated, errors, residuals, thresholds, independent_counts, nearest_distances


def clean_terrain_sources(sources, *, cancel_token=None, policy=None):
    """返回 ``{sources, report}``；从不修改传入来源或其点数组。

    ``sources`` 是 point/polyline 字典序列，``points`` 为原 XYZ，支持
    ``source_handle`` 等任意附带字段。报告以原 entity 索引及 handle 追溯。
    """
    policy = _policy(policy)
    sources = list(sources)
    reference, reference_sources, probes, probe_sources, vertex_counts, reference_diagnostics = _reference_and_probes(sources, policy, cancel_token)
    _check(cancel_token)
    if len(reference):
        evidence = _local_evidence(cKDTree(reference[:, :2]), reference, reference_sources, probes, probe_sources, policy, cancel_token)
    else:
        evidence = (np.empty(0, dtype=bool), np.empty(0, dtype=bool), *[np.empty(0) for _ in range(4)])
    evaluated, errors, residuals, thresholds, independent_counts, nearest_distances = evidence
    accepted, removed = [], []
    probe_counts = np.bincount(probe_sources, minlength=len(sources))
    cursor = 0
    insufficient_count = 0
    for index, source in enumerate(sources):
        if index % 128 == 0:
            _check(cancel_token)
        end = cursor + int(probe_counts[index])
        selection = slice(cursor, end)
        valid = evaluated[selection]
        bad = errors[selection]
        valid_count, bad_count = int(valid.sum()), int(bad.sum())
        probe_count = end - cursor
        minimum_checks = 1 if source["kind"] == "point" else min(3, probe_count)
        # 整条删除须覆盖大部分原线探针，且错误方向一致。
        enough_coverage = valid_count >= minimum_checks and valid_count >= policy["contour_error_fraction"] * probe_count
        consistent = bad_count >= minimum_checks and bad_count >= policy["contour_error_fraction"] * valid_count
        wrong_residual = residuals[selection][bad]
        same_direction = bool(len(wrong_residual)) and max(np.count_nonzero(wrong_residual > 0), np.count_nonzero(wrong_residual < 0)) >= policy["contour_error_fraction"] * len(wrong_residual)
        reject = enough_coverage and consistent and same_direction
        if reject:
            removed.append({"entity_index": index, "source_handle": source.get("source_handle"),
                            "layer": source.get("layer"), "kind": source["kind"], "vertex_count": vertex_counts[index],
                            "reason": "independent_local_elevation_outlier",
                            "diagnostic": {"probe_count": probe_count, "evaluated_probe_count": valid_count,
                                           "outlier_probe_count": bad_count,
                                           "median_elevation_error_m": float(np.median(wrong_residual)),
                                           "median_error_threshold_m": float(np.median(thresholds[selection][bad])),
                                           "minimum_independent_sources": int(np.min(independent_counts[selection][bad])),
                                           "maximum_nearest_reference_distance_m": float(np.max(nearest_distances[selection][bad]))}})
        else:
            accepted.append(index)
            insufficient_count += int(not enough_coverage)
        cursor = end
    removed_points = sum(value["kind"] == "point" for value in removed)
    removed_vertices = sum(value["vertex_count"] for value in removed)
    report = {"schema_version": "1.0", "rule": "INDEPENDENT_LOCAL_ROBUST_PLANE; XY_CELL_BALANCED_SCATTER_REFERENCE; WHOLE_CONTOUR; RETAIN_UNSUPPORTED; NO_OUTPUT_DECIMATION",
              "policy": policy, "input_entity_count": len(sources), "input_point_count": sum(vertex_counts),
              "removed_point_count": removed_points, "removed_contour_count": len(removed) - removed_points,
              "removed_vertex_count": removed_vertices, "output_entity_count": len(accepted),
              "output_point_count": sum(vertex_counts) - removed_vertices,
              "accepted_entity_indices": accepted, "removed_entities": removed,
              "retained_insufficient_evidence_count": insufficient_count,
              "diagnostic_reference_point_count": len(reference), "diagnostic_probe_count": len(probes),
              "source_unchanged": True}
    report.update(reference_diagnostics)
    return {"sources": [sources[index] for index in accepted], "report": report}


def _sha256(path, token=None):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            _check(token)
            digest.update(data)
    return digest.hexdigest()


def clean_native_sources_file(input_path, output_path, report_path=None, *, cancel_token=None, policy=None):
    """读取已有核对 JSONL，另存筛查副本并返回可核对报告，原文件只读。"""
    source, output = Path(input_path).resolve(), Path(output_path).resolve()
    if source == output or (report_path is not None and Path(report_path).resolve() in (source, output)):
        raise ValueError("高程筛查输出必须使用与原资料不同的文件名")
    before = _sha256(source, cancel_token)
    entities, header, ending = [], None, None
    with source.open(encoding="utf-8-sig") as stream:
        for index, line in enumerate(stream):
            if index % 128 == 0:
                _check(cancel_token)
            value = json.loads(line)
            if value.get("kind") == "header":
                if header is not None or entities or ending is not None:
                    raise ValueError("原地形来源 JSONL 头部顺序无效")
                header = value
            elif value.get("kind") == "end":
                if ending is not None:
                    raise ValueError("原地形来源 JSONL 尾部重复")
                ending = value
            else:
                if header is None or ending is not None:
                    raise ValueError("原地形来源 JSONL 实体顺序无效")
                entities.append(value)
    if header is None or ending is None or ending.get("entity_count") != len(entities):
        raise ValueError("原地形来源 JSONL 实体数量不一致")
    result = clean_terrain_sources(entities, cancel_token=cancel_token, policy=policy)
    report = result["report"]
    if ending.get("point_count") != report["input_point_count"]:
        raise ValueError("原地形来源 JSONL 顶点数量不一致")
    _check(cancel_token)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".quality-tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps(header, ensure_ascii=False, allow_nan=False) + "\n")
            for index, entity in enumerate(result["sources"]):
                if index % 128 == 0:
                    _check(cancel_token)
                stream.write(json.dumps(entity, ensure_ascii=False, allow_nan=False) + "\n")
            stream.write(json.dumps({**ending, "entity_count": report["output_entity_count"], "point_count": report["output_point_count"]}) + "\n")
        if _sha256(source, cancel_token) != before:
            raise ValueError("高程筛查期间原来源文件发生变化")
        _check(cancel_token)
        temporary.replace(output)
        report.update(input_path=str(source), input_sha256=before, output_path=str(output), output_sha256=_sha256(output, cancel_token))
        if report_path is not None:
            Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        return report
    finally:
        temporary.unlink(missing_ok=True)
