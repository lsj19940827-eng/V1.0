"""Whole-route quantities and closed calculation meshes, saved separately."""
from __future__ import annotations

import csv
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path

import numpy as np


FIELDS = ("excavation_volume", "backfill_volume", "embankment_volume", "total_fill_volume")
LABELS = ("天然开挖 m³", "结构周边回填 m³", "新增填筑 m³", "总填方 m³")
SECTION_NAMES = {"u_channel": "U形明渠", "rectangular_channel": "矩形明渠", "trapezoidal_channel": "梯形明渠",
                 "compound_trapezoidal_channel": "复式梯形明渠", "circular_channel": "圆形明渠",
                 "circular_culvert": "圆管涵", "rectangular_culvert": "矩形暗涵", "arch_culvert": "拱形暗涵",
                 "arch_tunnel": "圆拱直墙隧洞", "circular_tunnel": "圆形隧洞",
                 "flat_bottom_tunnel": "平底圆形隧洞", "horseshoe_tunnel": "马蹄形隧洞",
                 "aqueduct_u": "U形渡槽", "aqueduct_rectangular": "矩形渡槽",
                 "circular_siphon": "圆形埋管", "box_foundation": "闸基基坑"}
ROLES = {"excavation": ("天然开挖", (210, 65, 45, 255)),
         "backfill": ("结构周边回填", (230, 180, 40, 255)),
         "embankment": ("新增填筑", (65, 145, 210, 255)),
         "occupancy": ("结构及另列材料占位", (135, 135, 145, 255))}


def structure_label(payload, row):
    asset = next((a for a in payload.get("inputs", {}).get("network", {}).get("assets", [])
                  if a.get("asset_id") == row.get("asset_id")), row)
    if asset.get("kind") == "pressure_pipe": return "有压管道"
    if asset.get("kind") == "siphon": return "倒虹吸"
    if asset.get("section_type", row.get("section_type")) == "circular_channel":
        test = payload.get("test_only") or asset.get("test_only") or asset.get("is_test")
        return "圆形管渠（明流，测试埋设）" if test else "完整圆断面明流管渠"
    if asset.get("section_type") == "circular_culvert" and asset.get("source_type") == "明渠-圆形": return "圆管涵（明渠-圆形）"
    return SECTION_NAMES.get(row.get("section_type"), row.get("section_type", ""))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _verify_sources(payload):
    for source in (payload.get("terrain", {}), payload.get("network_file", {})):
        expected = source.get("source_sha256", source.get("sha256"))
        if source.get("path") and expected and _sha(source["path"]) != expected:
            raise ValueError("源文件已变化，请重新计算后导出")


def _cad_array_sha(values):
    return hashlib.sha256(memoryview(np.ascontiguousarray(values))).hexdigest()


def _cad_edges(faces):
    a = faces.reshape(-1)
    b = faces[:, [1, 2, 0]].reshape(-1)
    low, high = np.minimum(a, b).astype(np.uint64), np.maximum(a, b).astype(np.uint64)
    packed = (low << np.uint64(32)) | high
    unique, counts = np.unique(packed, return_counts=True)
    positive, positive_counts = np.unique(packed[a < b], return_counts=True)
    balance = -counts.copy()
    balance[np.searchsorted(unique, positive)] += 2 * positive_counts
    report = {'boundary_edges': int(np.count_nonzero(counts == 1)),
              'multiple_edges': int(np.count_nonzero(counts > 2)),
              'direction_imbalances': int(np.count_nonzero(balance)),
              'loop_halfedges': int(np.count_nonzero(a == b))}
    report['closed_oriented_two_halfedges_every_edge'] = bool(
        np.all(counts == 2) and not np.any(balance) and not np.any(a == b))
    return report, unique[counts > 2]


def _cad_triangle_volume(triangle, reference):
    a, b, c = [[Fraction(float(point[j])) - Fraction(float(reference[j])) for j in range(3)]
               for point in triangle]
    return (a[0]*(b[1]*c[2]-b[2]*c[1]) + a[1]*(b[2]*c[0]-b[0]*c[2])
            + a[2]*(b[0]*c[1]-b[1]*c[0])) / 6


def _normalize_zero_edges(points, faces):
    """Convert zero-length CAD edges without changing any calculation solid.

    Only bit-identical endpoints of an existing triangle edge may contract.
    Original coincident contacts elsewhere remain separate. Conflicting edge
    paths receive independently indexed, correctly rounded edge midpoints.
    """
    p, f = np.asarray(points), np.asarray(faces)
    if (p.ndim != 2 or p.shape[1] != 3 or p.dtype != np.dtype('float64')
            or not np.isfinite(p).all() or f.ndim != 2 or f.shape[1] != 3
            or not np.issubdtype(f.dtype, np.integer) or len(p) >= 2**32
            or (f.size and (int(f.min()) < 0 or int(f.max()) >= len(p)))):
        raise ValueError('CAD实体转换需要有限double坐标及有效三角索引')
    original_topology, _ = _cad_edges(f)
    if not original_topology['closed_oriented_two_halfedges_every_edge']:
        raise ValueError('CAD转换前原索引必须每边恰有两个反向半边')
    source_hashes = {'vertices': _cad_array_sha(p), 'faces': _cad_array_sha(f)}
    report = {'method': 'exact_triangle_edge_contraction_with_independent_midpoint_paths',
              'changed': False, 'source_vertex_count': len(p), 'source_face_count': len(f),
              'source_array_sha256': source_hashes, 'source_topology': original_topology,
              'original_vertex_double_bits_unchanged': True}
    bits = np.ascontiguousarray(p).view(np.uint64)
    zero_edges = []
    for start in range(0, len(f), 100000):
        chunk = f[start:start+100000]
        for a, b in ((0, 1), (1, 2), (2, 0)):
            same = np.all(bits[chunk[:, a]] == bits[chunk[:, b]], axis=1)
            zero_edges.extend((start+int(i), int(chunk[i, a]), int(chunk[i, b])) for i in np.flatnonzero(same))
    if not zero_edges:
        report.update(post_vertex_count=len(p), post_face_count=len(f), post_array_sha256=source_hashes,
                      post_topology=original_topology, vertex_aliases=[], added_midpoints=[],
                      removed_zero_faces=[], modified_original_face_count=0, exact_volume_delta_m3='0',
                      volume_delta_m3=0.0)
        return points, faces, report
    parent = np.arange(len(p), dtype=np.int64)
    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = int(parent[index])
        return index
    for _, a, b in zero_edges:
        x, y = find(a), find(b)
        if x != y:
            parent[max(x, y)] = min(x, y)
    for index in np.flatnonzero(parent != np.arange(len(p))):
        parent[index] = find(int(index))
    aliases = [[int(index), int(parent[index])] for index in np.flatnonzero(parent != np.arange(len(p)))]
    mapped = parent[f]
    repeated = (mapped[:, 0] == mapped[:, 1]) | (mapped[:, 1] == mapped[:, 2]) | (mapped[:, 2] == mapped[:, 0])
    trial_topology, conflicts = _cad_edges(mapped[~repeated])
    if trial_topology['boundary_edges'] or trial_topology['direction_imbalances']:
        raise ValueError('零边收缩产生未闭合或方向不明确的半边，停止CAD转换')
    groups = {int(key): {} for key in conflicts}
    for start in range(0, len(f), 100000):
        chunk = f[start:start+100000]
        for a, b in ((0, 1), (1, 2), (2, 0)):
            va, vb = chunk[:, a], chunk[:, b]
            ma, mb = parent[va], parent[vb]
            keys = (np.minimum(ma, mb).astype(np.uint64) << np.uint64(32)) | np.maximum(ma, mb).astype(np.uint64)
            for local in np.flatnonzero(np.isin(keys, conflicts)):
                edge = tuple(sorted((int(va[local]), int(vb[local]))))
                groups[int(keys[local])].setdefault(edge, []).append(
                    (start+int(local), int(va[local]), int(vb[local])))
    children, midpoints, midpoint_proofs = {}, [], []
    for packed, originals in sorted(groups.items()):
        if len(originals) < 2 or any(len(incidents) != 2 for incidents in originals.values()):
            raise ValueError('CAD冲突边不能唯一追溯至成对原索引边')
        for edge, incidents in sorted(originals.items()):
            if incidents[0][1:] != incidents[1][1:][::-1]:
                raise ValueError('CAD原索引边的两个半边方向不相反')
            midpoint, axes = [], []
            for axis in range(3):
                exact = (Fraction(float(p[edge[0], axis])) + Fraction(float(p[edge[1], axis]))) / 2
                stored = float(exact)
                error, half_ulp = Fraction(stored)-exact, Fraction(math.ulp(stored))/2
                if abs(error) > half_ulp:
                    raise ValueError('CAD边中点舍入超过半ULP')
                midpoint.append(stored)
                axes.append({'axis': axis, 'exact_midpoint': str(exact), 'error_m': str(error),
                             'half_ulp_m': str(half_ulp), 'within_half_ulp': True})
            midpoint_id = len(p)+len(midpoints)
            midpoints.append(midpoint)
            for face_id, _, _ in incidents:
                current = children.setdefault(face_id, [f[face_id].tolist()])
                matches = [i for i, triangle in enumerate(current) if all(v in triangle for v in edge)]
                if len(matches) != 1:
                    raise ValueError('CAD原边在分割子三角中不能唯一定位')
                child_id = matches[0]
                triangle = current[child_id]
                positions = [i for i in range(3) if set((triangle[i], triangle[(i+1) % 3])) == set(edge)]
                if len(positions) != 1:
                    raise ValueError('CAD分割边方向不明确')
                i = positions[0]
                a, b, c = triangle[i], triangle[(i+1) % 3], triangle[(i+2) % 3]
                current[child_id:child_id+1] = [[a, midpoint_id, c], [midpoint_id, b, c]]
            midpoint_proofs.append({'mapped_conflict_edge': [packed >> 32, packed & 0xffffffff],
                'original_edge': list(edge), 'incident_faces': [row[0] for row in incidents],
                'index': midpoint_id, 'xyz': midpoint, 'axis_rounding': axes})
    post_points = np.concatenate((p, np.asarray(midpoints, dtype=np.float64).reshape(-1, 3))) if midpoints else p
    parent = np.concatenate((parent, np.arange(len(p), len(post_points), dtype=np.int64)))
    pieces, source_ids, start = [], [], 0
    for face_id, replacements in sorted(children.items()):
        pieces.extend((f[start:face_id], np.asarray(replacements, dtype=f.dtype)))
        source_ids.extend((np.arange(start, face_id, dtype=np.int64), np.full(len(replacements), face_id, dtype=np.int64)))
        start = face_id+1
    pieces.append(f[start:]); source_ids.append(np.arange(start, len(f), dtype=np.int64))
    split = np.concatenate(pieces)
    source_ids = np.concatenate(source_ids)
    mapped = parent[split].astype(f.dtype, copy=False)
    removed = (mapped[:, 0] == mapped[:, 1]) | (mapped[:, 1] == mapped[:, 2]) | (mapped[:, 2] == mapped[:, 0])
    removed_proofs = []
    for index in np.flatnonzero(removed):
        triangle = post_points[split[index]]
        if not any(np.array_equal(triangle[a].view(np.uint64), triangle[b].view(np.uint64))
                   for a, b in ((0, 1), (1, 2), (2, 0))):
            raise ValueError('CAD转换禁止删除非零面积三角')
        removed_proofs.append({'original_face_index': int(source_ids[index]), 'split_indices': split[index].tolist(),
                               'strict_area_zero_by_identical_xyz': True})
    post_faces, post_sources = mapped[~removed], source_ids[~removed]
    post_topology, _ = _cad_edges(post_faces)
    if not post_topology['closed_oriented_two_halfedges_every_edge']:
        raise ValueError('CAD转换后索引仍未严格闭合或存在多重边')
    changed_faces = set(children) | {row['original_face_index'] for row in removed_proofs}
    changed_ids = np.asarray(sorted(changed_faces), dtype=np.int64)
    for start in range(0, len(post_faces), 100000):
        chunk = post_faces[start:start+100000]
        ids = post_sources[start:start+100000]
        unchanged = ~np.isin(ids, changed_ids)
        if not np.array_equal(post_points[chunk[unchanged]].view(np.uint64), p[f[ids[unchanged]]].view(np.uint64)):
            raise ValueError('CAD转换改变了未分割三角的原坐标')
        triangle_bits = np.ascontiguousarray(post_points[chunk]).view(np.uint64)
        if any(np.any(np.all(triangle_bits[:, a] == triangle_bits[:, b], axis=1)) for a, b in ((0, 1), (1, 2), (2, 0))):
            raise ValueError('CAD转换后仍有重复坐标角点')
    reference = p[0]
    before = sum((_cad_triangle_volume(p[f[index]], reference) for index in changed_ids), Fraction(0))
    after = sum((_cad_triangle_volume(post_points[post_faces[index]], reference)
                 for index in np.flatnonzero(np.isin(post_sources, changed_ids))), Fraction(0))
    delta = after-before
    if abs(delta) >= Fraction(1, 1000000):
        raise ValueError('CAD拓扑转换精确体积差达到1e-6立方米，停止导出')
    report.update(changed=True, post_vertex_count=len(post_points), post_face_count=len(post_faces),
                  post_array_sha256={'vertices': _cad_array_sha(post_points), 'faces': _cad_array_sha(post_faces)},
                  post_topology=post_topology, vertex_aliases=aliases, added_midpoints=midpoint_proofs,
                  removed_zero_faces=removed_proofs, modified_original_face_count=len(changed_ids),
                  modified_original_faces=changed_ids.tolist(), unmodified_triangle_xyz_bits_exact=True,
                  exact_volume_delta_m3=str(delta), volume_delta_m3=float(delta),
                  exact_volume_difference_less_than_1e_6=True)
    return post_points, post_faces, report


def export_network_result(payload, path, calculation=None):
    if payload.get("method") == "exact_tin_actual_midpoint_section_integration":
        from .section_exporter import export_section_result
        return export_section_result(payload, path, calculation)
    from app_渠系计算前端.runtime_platform import ensure_safe_windows_platform_queries
    ensure_safe_windows_platform_queries()
    if payload.get("status") != "READY" or not payload.get("converged"):
        raise ValueError("只能导出已完成并收敛的全线成果")
    _verify_sources(payload)
    path = Path(path).resolve()
    for original in (payload.get("terrain", {}).get("path"), payload.get("network_file", {}).get("path")):
        if original:
            same = path == Path(original).resolve()
            if not same and path.exists(): same = path.samefile(original)
            if same: raise ValueError("成果必须另存，不能覆盖源地形或全线输入及其链接")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    elif path.suffix.lower() == ".csv":
        from .workbench_drawings import layered_scope_note,layered_volume_columns
        layer_columns=layered_volume_columns(payload)
        fields=(*FIELDS,*(key for key,_ in layer_columns))
        labels=(*LABELS,*(name+" m³" for _,name in layer_columns))
        with path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(["全线TEST算量" if payload.get("test_only") else "全线工程量", *labels])
            writer.writerow(["去重合计", *(payload.get(k) for k in fields)])
            writer.writerow([])
            writer.writerow(["对象编号", "名称", "类型", "起桩 m", "止桩 m", "真长 m", *labels])
            for row in payload.get("rows", payload.get("assets", [])):
                writer.writerow([row.get("asset_id"), row.get("name"), structure_label(payload, row),
                                 row.get("station_start"), row.get("station_end"),
                                 row.get("length", row.get("station_end", 0)-row.get("station_start", 0)),
                                 *(row.get(k) for k in fields)])
            writer.writerow([])
            writer.writerow(["共用范围归属", payload.get("allocation_policy", "")])
            writer.writerow(["输入摘要", payload.get("input_hash", "")])
            writer.writerow(["地形摘要", payload.get("terrain", {}).get("source_sha256", "")])
            note=layered_scope_note(payload)
            if note:writer.writerow(["简化分层及计量范围",note])
    elif path.suffix.lower() == ".3dm":
        if calculation is None:
            raise ValueError("保存实体模型须重新计算，历史数量不代替计算实体")
        return _model(payload, path, calculation)
    elif path.suffix.lower() == ".dxf":
        if calculation is None:
            raise ValueError("保存实体剖面须使用本次实际计算实体")
        return _sections(payload, path, calculation)
    else:
        raise ValueError("全线成果请选择CSV、JSON、3DM或DXF")
    return str(path)


def _model(payload, path, calculation):
    import shutil
    import tempfile
    from tools.terrain_mesh_reader.writer import append_meshes
    source = payload.get("terrain", {}).get("path")
    attached = source if source and Path(source).suffix.lower() == ".3dm" else None
    specs = []
    topology_reports = {}
    shift = np.asarray(calculation.origin)
    for role, (label, color) in ROLES.items():
        solid = calculation.solids.get(role)
        if solid is None or solid.is_empty():
            continue
        data = solid.to_mesh64()
        points = np.asarray(data.vert_properties[:, :3], dtype=float)+shift
        faces = np.asarray(data.tri_verts, dtype=np.int64)
        points, faces, topology_reports[role] = _normalize_zero_edges(points, faces)
        strings = {"qx_role": role, "qx_input_hash": payload["input_hash"],
                   "qx_test_only": str(payload.get("test_only")), "qx_volume_m3": format(solid.volume(), ".17g"),
                   "qx_geometry_basis": payload["integration_method"]}
        specs.append({"vertices": points, "faces": faces, "name": label,
                      "layer": ("TEST · " if payload.get("test_only") else "")+label,
                      "color": color, "user_strings": strings, "require_closed": True})
    strings = {key: format(payload[key], ".17g") for key in FIELDS}
    strings.update(test_only=str(payload.get("test_only")), input_hash=payload["input_hash"])
    with tempfile.TemporaryDirectory(prefix=".network-model-", dir=path.parent) as temporary:
        temporary = Path(temporary)
        staged, audit = temporary/"model.3dm", temporary/"model.audit.json"
        metadata = append_meshes(attached, staged, specs, document_strings=strings)
        meshes = [{**mesh, 'cad_topology_normalization': topology_reports[mesh['role']]} for mesh in metadata['meshes']]
        report = {**metadata, "path": str(path), "sha256": _sha(staged), "input_hash": payload["input_hash"],
                  "original_terrain_document_attached": bool(attached),
                  "all_original_terrain_xyz_and_faces_equal": metadata["all_original_terrain_xyz_and_faces_equal"],
                  "meshes": meshes, "closed_mesh_readbacks": meshes,
                  "cad_topology_normalization": topology_reports}
        audit.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _verify_sources(payload)
        previous = temporary/"previous.3dm"
        existed = path.exists()
        if existed:
            shutil.copy2(path, previous)
        committed = False
        try:
            staged.replace(path)
            committed = True
            audit.replace(path.with_suffix(".3dm.audit.json"))
        except BaseException:
            if committed:
                if existed:
                    previous.replace(path)
                else:
                    path.unlink(missing_ok=True)
            raise
    return str(path)


def _sections(payload, path, calculation):
    import ezdxf
    from ezdxf import bbox
    import shutil
    import tempfile
    from ..services.network_alignment import NetworkAlignment
    alignment = NetworkAlignment.from_dict(payload["inputs"]["network"]["alignment"])
    document = ezdxf.new("R2013"); document.units = 6
    document.appids.new("QX_NETWORK_SECTION")
    for role, (label, color) in ROLES.items():
        document.layers.new(role, dxfattribs={"color": {"excavation": 1, "backfill": 30, "embankment": 5, "occupancy": 8}[role]})
    model = document.modelspace()
    shift = np.asarray(calculation.origin)
    records, views = [], []
    text_height, text_gap, column_gap, row_gap = 2.5, 5.0, 20.0, 20.0
    for i, asset in enumerate(payload.get("rows", payload.get("assets", []))):
        station = (asset["station_start"]+asset["station_end"])/2
        xy = np.asarray(alignment.get_xy_at_station(station))-shift[:2]
        angle = alignment.get_tangent_angle_at_station(station)
        t = np.array([np.cos(angle), np.sin(angle)]); lateral = np.array([t[1], -t[0]])
        matrix = np.array([[*lateral, 0, -float(lateral@xy)], [0, 0, 1, shift[2]],
                           [*t, 0, -float(t@xy)]])
        paths = []
        for role in ROLES:
            solid = calculation.solids.get(role)
            if solid is None or solid.is_empty(): continue
            section = solid.transform(matrix).slice(0)
            for polygon in section.to_polygons():
                if len(polygon) >= 3:
                    values = np.asarray(polygon, dtype=float)
                    if values.ndim != 2 or values.shape[1] != 2 or not np.isfinite(values).all():
                        raise ValueError("实际实体剖面含无效坐标")
                    paths.append((role, values))
        if not paths: continue
        left = min(p[:, 0].min() for _, p in paths)
        right = max(p[:, 0].max() for _, p in paths)
        bottom = min(p[:, 1].min() for _, p in paths)
        top = max(p[:, 1].max() for _, p in paths)
        title = f"{'TEST ' if payload.get('test_only') else ''}{asset['asset_id']} S={station:.3f} Z0={bottom:.3f}"
        title_entity = model.add_text(title, dxfattribs={"height": text_height, "insert": (0, 0)})
        title_box = bbox.extents([title_entity])
        text_left = float(title_box.extmin.x) if title_box.has_data else 0.0
        text_width = max(float(title_box.size.x) if title_box.has_data else 0.0,
                         len(title)*text_height*1.2)
        text_bottom = min(float(title_box.extmin.y) if title_box.has_data else 0.0, -text_height*.5)
        text_top = max(float(title_box.extmax.y) if title_box.has_data else text_height, text_height*1.2)
        views.append({"asset": asset, "station": station, "paths": paths, "left": float(left),
                      "bottom": float(bottom), "right": float(right), "top": float(top),
                      "title": title_entity, "text_left": text_left, "text_bottom": text_bottom,
                      "text_top": text_top, "width": max(float(right-left), text_width),
                      "height": float(top-bottom)+text_gap+text_top-text_bottom})
    widths = [max((v["width"] for j, v in enumerate(views) if j%4 == col), default=0.) for col in range(4)]
    xstarts = [0.]
    for width in widths[:-1]:
        xstarts.append(xstarts[-1]+width+column_gap)
    row_heights = [max(v["height"] for v in views[j:j+4]) for j in range(0, len(views), 4)]
    row_tops = [0.]
    for height in row_heights[:-1]:
        row_tops.append(row_tops[-1]-height-row_gap)
    for index, view in enumerate(views):
        col, row = index%4, index//4
        x, top = xstarts[col], row_tops[row]
        bottom = top-(view["top"]-view["bottom"])
        title_y = bottom-text_gap-view["text_top"]
        view_id = f"section-{index:05d}"
        tags = [(1000, view_id), (1040, view["station"])]
        for role, polygon in view["paths"]:
            entity = model.add_lwpolyline([(float(px-view["left"]+x), float(z-view["bottom"]+bottom))
                                          for px, z in polygon], close=True, dxfattribs={"layer": role})
            entity.set_xdata("QX_NETWORK_SECTION", tags)
        view["title"].dxf.insert = (x-view["text_left"], title_y)
        view["title"].set_xdata("QX_NETWORK_SECTION", tags)
        records.append({"asset_id": view["asset"]["asset_id"], "station": view["station"],
                        "polygon_count": len(view["paths"]), "view_id": view_id, "layout_column": col,
                        "layout_row": row, "source_section_bounds": [view["left"], view["bottom"], view["right"], view["top"]],
                        "layout_envelope": [x, title_y+view["text_bottom"], x+view["width"], top]})
    with tempfile.TemporaryDirectory(prefix=".network-sections-", dir=path.parent) as temporary:
        temporary = Path(temporary)
        staged, audit = temporary/"sections.dxf", temporary/"sections.audit.json"
        document.saveas(staged)
        saved = ezdxf.readfile(staged)
        if saved.audit().errors:
            raise ValueError("保存后DXF审计失败")
        groups = {}
        for entity in saved.modelspace():
            if entity.has_xdata("QX_NETWORK_SECTION"):
                key = entity.get_xdata("QX_NETWORK_SECTION")[0].value
                groups.setdefault(key, []).append(entity)
        if len(groups) != len(records):
            raise ValueError("保存后DXF剖面分组数量改变")
        envelopes = []
        for record in records:
            actual = bbox.extents(groups[record["view_id"]])
            if not actual.has_data:
                raise ValueError("保存后DXF剖面没有有效布局包络")
            record["saved_geometry_envelope"] = [float(actual.extmin.x), float(actual.extmin.y),
                                                 float(actual.extmax.x), float(actual.extmax.y)]
            planned = record["layout_envelope"]
            envelopes.append([min(planned[0], actual.extmin.x), min(planned[1], actual.extmin.y),
                              max(planned[2], actual.extmax.x), max(planned[3], actual.extmax.y)])
        for first in range(len(envelopes)):
            for second in range(first+1, len(envelopes)):
                a, b = envelopes[first], envelopes[second]
                if min(a[2], b[2])-max(a[0], b[0]) > 1e-8 and min(a[3], b[3])-max(a[1], b[1]) > 1e-8:
                    raise ValueError(f"保存后DXF剖面布局重叠：{records[first]['asset_id']} / {records[second]['asset_id']}")
        report = {"path": str(path), "sha256": _sha(staged), "saved_reopened": True, "audit_errors": 0,
                  "input_hash": payload["input_hash"], "sections": records,
                  "layout": {"columns": 4, "column_gap": column_gap, "row_gap": row_gap, "text_gap": text_gap,
                             "saved_envelopes": envelopes, "saved_no_overlap": True}}
        audit.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _verify_sources(payload)
        previous = temporary/"previous.dxf"
        existed = path.exists()
        if existed:
            shutil.copy2(path, previous)
        committed = False
        try:
            staged.replace(path)
            committed = True
            audit.replace(path.with_suffix(".dxf.audit.json"))
        except BaseException:
            if committed:
                if existed:
                    previous.replace(path)
                else:
                    path.unlink(missing_ok=True)
            raise
    return str(path)
