# -*- coding: utf-8 -*-
"""在 Rhino 读取文件前筛选测量地形，保留中心线及真实三维测点。"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
import uuid

import ezdxf
from ezdxf.addons import Importer
from ezdxf.addons import iterdxf


TERRAIN_LAYERS = ("GCD", "SQX", "JQX")
CONTOUR_TYPES = frozenset({"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE"})
PROVENANCE_APP = "QX_TERRAIN_SOURCE"
POINT_PROVENANCE = frozenset({"GCD_INSERT", "GCD_CIRCLE_CENTER"})


def _gcd_circle_markers(model, point_layers=None):
    """识别 GCD 小圆加数值标注的测点图式；高程始终取圆心真实 WCS Z。"""
    labels, candidates = {}, []
    cell_size = 3.0
    point_layers = set(point_layers or {"GCD"})
    for entity in model:
        if entity.dxf.layer.upper() not in point_layers:
            continue
        if entity.dxftype() == "TEXT":
            try:
                number = float(entity.dxf.text.strip())
                position = entity.ocs().to_wcs(entity.dxf.insert)
                if not math.isfinite(number) or not all(math.isfinite(v) for v in position):
                    continue
                key = tuple(math.floor(v / cell_size) for v in (position.x, position.y))
                labels.setdefault(key, []).append((entity.dxf.handle, position, number))
            except (ValueError, TypeError):
                continue
        elif (entity.dxftype() == "CIRCLE" and 0 < entity.dxf.radius <= 0.5
              and abs(abs(entity.dxf.extrusion.z) - 1) < 1e-10):
            candidates.append(entity)
    matches = {}
    for entity in candidates:
        center = entity.ocs().to_wcs(entity.dxf.center)
        if not all(math.isfinite(v) for v in center):
            continue
        cell = tuple(math.floor(v / cell_size) for v in (center.x, center.y))
        nearby = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for handle, position, number in labels.get((cell[0] + dx, cell[1] + dy), []):
                    distance = math.hypot(position.x - center.x, position.y - center.y)
                    if distance <= cell_size and abs(number - center.z) <= 0.051:
                        nearby.append((distance, handle, position, number))
        if nearby:
            distance, handle, position, number = min(nearby, key=lambda item: item[0])
            matches[entity.dxf.handle] = {"handle": handle, "xyz": list(position), "text_elevation": number,
                                           "distance_xy_m": distance, "circle_xyz": list(center),
                                           "text_geometry_z_difference_m": position.z - center.z}
    # 少量无关圆或孤立文字不足以启用另一种地形图式。
    if len(matches) < 3 or len(matches) < 0.9 * len(candidates):
        return {}
    return matches


def _check(token):
    if token is not None:
        token.raise_if_cancelled()


def _hash(path, token=None):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            _check(token)
            digest.update(data)
    return digest.hexdigest()


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def _clear_width(entity):
    """清除显示宽度，不改变中心线坐标、圆弧凸度及闭合属性。"""
    had_width = False
    entity.dxf.lineweight = 0
    if entity.dxftype() == "LWPOLYLINE":
        had_width = bool(entity.dxf.get("const_width", 0))
        points = list(entity.get_points("xyseb"))
        had_width |= any(start or end for _x, _y, start, end, _bulge in points)
        entity.set_points([(x, y, 0, 0, bulge) for x, y, _start, _end, bulge in points], format="xyseb")
        entity.dxf.const_width = 0
    elif entity.dxftype() == "POLYLINE":
        had_width = bool(entity.dxf.get("default_start_width", 0) or entity.dxf.get("default_end_width", 0))
        entity.dxf.default_start_width = entity.dxf.default_end_width = 0
        for vertex in entity.vertices:
            had_width |= bool(vertex.dxf.get("start_width", 0) or vertex.dxf.get("end_width", 0))
            vertex.dxf.start_width = vertex.dxf.end_width = 0
    return bool(had_width)


def _known_point_count(entity):
    # 曲线由 Rhino 按其原生长度采样，此处仅累计能确定的折线顶点，不虚报精确总数。
    kind = entity.dxftype()
    if kind == "POINT":
        return 1
    if kind == "LINE":
        return 2
    if kind == "LWPOLYLINE" and not entity.has_arc:
        return len(entity) + int(entity.closed)
    if kind == "POLYLINE" and (entity.is_3d_polyline or entity.is_2d_polyline):
        if not any(vertex.dxf.get("bulge", 0) for vertex in entity.vertices) and not entity.dxf.flags & 6:
            return len(entity.vertices) + int(entity.is_closed)
    return None


def _marked_point(entity):
    try:
        tags = entity.get_xdata(PROVENANCE_APP)
        return len(tags) >= 2 and tags[0].value in POINT_PROVENANCE
    except ezdxf.DXFValueError:
        return False


def _original_handle(entity):
    try:
        tags = entity.get_xdata(PROVENANCE_APP)
        if len(tags) >= 2 and tags[0].value in POINT_PROVENANCE | {"CONTOUR_CENTERLINE"}:
            return str(tags[1].value)
    except ezdxf.DXFValueError:
        pass
    return entity.dxf.handle


def _filter_dxf(source, output, points_path, token):
    doc = ezdxf.readfile(source)
    target = ezdxf.new("R2013")
    target.units = doc.units
    target.appids.new(PROVENANCE_APP)
    for layer in TERRAIN_LAYERS:
        target.layers.new(layer, dxfattribs={"lineweight": 0})
    importer = Importer(doc, target)
    source_counts, contours, gcd_count, width_count = Counter(), 0, 0, 0
    circle_markers = _gcd_circle_markers(doc.modelspace())
    with Path(points_path).open("w", encoding="utf-8") as provenance:
        for index, entity in enumerate(doc.modelspace()):
            if index % 256 == 0:
                _check(token)
            layer, kind = entity.dxf.layer.upper(), entity.dxftype()
            source_counts[f"{layer}/{kind}"] += 1
            if layer == "GCD" and (kind == "INSERT" or kind == "POINT" and _marked_point(entity)
                                    or kind == "CIRCLE" and entity.dxf.handle in circle_markers):
                # DXF INSERT 使用 OCS 插入点；转为 WCS 后保留零高程、负高程及完整小数。
                point = (entity.ocs().to_wcs(entity.dxf.insert) if kind == "INSERT" else
                         entity.ocs().to_wcs(entity.dxf.center) if kind == "CIRCLE" else entity.dxf.location)
                if not all(math.isfinite(value) for value in point):
                    raise ValueError(f"GCD 对象 {entity.dxf.handle} 的测点不是有限坐标")
                made = target.modelspace().add_point(point, dxfattribs={"layer": "GCD", "lineweight": 0})
                source_kind = ("GCD_CIRCLE_CENTER" if kind == "CIRCLE" else
                               entity.get_xdata(PROVENANCE_APP)[0].value if kind == "POINT" else "GCD_INSERT")
                made.set_xdata(PROVENANCE_APP, [(1000, source_kind), (1000, _original_handle(entity)), (1000, layer)])
                provenance.write(json.dumps({"handle": _original_handle(entity), "xyz": list(point),
                                             "source_kind": source_kind,
                                             "label_evidence": circle_markers.get(entity.dxf.handle)}) + "\n")
                gcd_count += 1
            elif (layer in ("SQX", "JQX") or circle_markers and layer == "GCD"
                  and kind in ("LWPOLYLINE", "POLYLINE")) and kind in CONTOUR_TYPES:
                if kind == "POLYLINE" and not (entity.is_2d_polyline or entity.is_3d_polyline):
                    continue
                # 克隆原线，只在目标实体清宽；不用文字配高程或炸块轮廓。
                importer.import_entity(entity, target_layout=target.modelspace())
                if layer == "GCD":
                    target.modelspace()[-1].dxf.layer = "SQX"
                target.modelspace()[-1].set_xdata(PROVENANCE_APP,
                    [(1000, "CONTOUR_CENTERLINE"), (1000, _original_handle(entity)), (1000, layer)])
                contours += 1
    importer.finalize()
    for entity in target.modelspace():
        entity.dxf.layer = entity.dxf.layer.upper()
        width_count += _clear_width(entity)
    for layer in target.layers:
        layer.dxf.lineweight = 0
    if not gcd_count + contours:
        raise ValueError("未找到 GCD 块参照、可识别的 GCD 测点圆或 SQX/JQX 等高线，请核对测量资料图层与测点图式")
    _check(token)
    target.saveas(output)
    return {"passed": True, "scanned_model_entities": sum(source_counts.values()),
            "source_layer_types": dict(source_counts), "gcd_insert_count": gcd_count,
            "contour_count": contours, "width_cleared_contours": width_count,
            "source_insunits": doc.units, "reader": "ezdxf",
            "gcd_circle_center_count": len(circle_markers),
            "gcd_circle_label_evidence": circle_markers,
            "source_layout": "gcd_circle_markers_with_gcd_contours" if circle_markers else "gcd_inserts_sqx_jqx"}


def find_autocad_core():
    """优先显式配置，其次查询已安装的兼容 AutoCAD，不连接当前 CAD 会话。"""
    configured = os.environ.get("QX_AUTOCAD_CORE_CONSOLE")
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise ValueError("配置的 AutoCAD Core Console 文件不存在")
        return path
    if os.name == "nt":
        import winreg
        found = []
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Autodesk\AutoCAD") as root:
                    for index in range(winreg.QueryInfoKey(root)[0]):
                        version = winreg.EnumKey(root, index)
                        # 当前读取器使用 .NET Framework SDK，AutoCAD 2025 起须另行适配。
                        try:
                            if not 23.1 <= float(version.lstrip("R")) < 25:
                                continue
                        except ValueError:
                            continue
                        with winreg.OpenKey(root, version) as release:
                            for product_index in range(winreg.QueryInfoKey(release)[0]):
                                try:
                                    with winreg.OpenKey(release, winreg.EnumKey(release, product_index)) as product:
                                        location = winreg.QueryValueEx(product, "AcadLocation")[0]
                                        path = Path(location) / "accoreconsole.exe"
                                        if path.is_file():
                                            found.append((version, path))
                                except OSError:
                                    continue
            except OSError:
                continue
        if found:
            # Prefer an isolated reader already proven on this computer.
            # This avoids repeatedly initializing an unused CAD installation.
            def priority(candidate):
                version, path = candidate
                key = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:16]
                ready = Path(tempfile.gettempdir()) / "qx-cad-profiles-v1" / key / "ready.json"
                return ready.is_file(), version
            return sorted(found, key=priority, reverse=True)[0][1]
    raise ValueError("DWG 自动筛选需要本机 AutoCAD 2020–2024；也可先在 CAD 中另存为 DXF 后导入，程序仍会自动筛选三个图层并清零线宽")


def _run(arguments, *, cwd, env, log, token, timeout, completion_file=None):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with Path(log).open("wb") as stream:
        process = subprocess.Popen([str(value) for value in arguments], cwd=cwd, env=env,
                                   stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                                   creationflags=flags)
        start = time.monotonic()
        try:
            while process.poll() is None:
                _check(token)
                if completion_file and Path(completion_file).is_file():
                    try:
                        # 原生报告在源库、目标库及输出文件关闭后写出；不等待 CAD 退出阶段。
                        completed = json.loads(Path(completion_file).read_text(encoding="utf-8-sig"))
                        if isinstance(completed.get("passed"), bool):
                            return 0
                    except (OSError, ValueError):
                        pass
                if time.monotonic() - start > timeout:
                    raise ValueError("地形前处理超时，请按工程范围裁剪或先在 CAD 中筛选后另存为 DXF")
                time.sleep(0.1)
            _check(token)
            return process.returncode
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def _filter_dwg(source, output, points_path, working, token, core_console):
    core = Path(core_console) if core_console else find_autocad_core()
    sdk = core.parent
    csc = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    helper = Path(__file__).with_name("terrain_filter_acad.cs")
    if not csc.is_file() or not helper.is_file():
        raise ValueError("DWG 读取器所需组件缺失，请使用筛选后的 DXF，或重新安装主程序")
    dll = working / "QxTerrainFilter.dll"
    compile_log = working / "compile.log"
    status = _run([csc, "/nologo", "/codepage:65001", "/target:library", "/platform:x64", f"/out:{dll}",
                   f"/reference:{sdk / 'acdbmgd.dll'}", f"/reference:{sdk / 'accoremgd.dll'}",
                   "/reference:System.Web.Extensions.dll", helper],
                  cwd=working, env=os.environ.copy(), log=compile_log, token=token, timeout=60)
    if status:
        raise ValueError("DWG 读取器编译失败：" + compile_log.read_text(encoding="utf-8", errors="replace")[-2000:])
    source_copy = working / "source.dwg"
    shutil.copyfile(source, source_copy)
    # Core Console 需要一个工作文档；优先使用小型模板，源库另行只读打开。
    candidates = [sdk / "Drawing1.dwg", *sorted((sdk / "Sample").glob("**/*.dwt"))]
    starter = next((path for path in candidates if path.is_file()), source_copy)
    host = working / "host.dwg"
    shutil.copyfile(starter, host)
    host.chmod(stat.S_IWRITE | stat.S_IREAD)
    config, report = working / "config.json", working / "native-report.json"
    _write_json(config, {"source": str(source_copy), "output": str(output), "points": str(points_path), "report": str(report)})
    script = working / "run.scr"
    script.write_text('(setvar "TRUSTEDPATHS" (strcat (getvar "TRUSTEDPATHS") ";" (getenv "QX_TERRAIN_HELPER_DIR")))\n'
                      '(command "_NETLOAD" (getenv "QX_TERRAIN_FILTER_DLL"))\nQXTERRAINFILTER\n_QUIT\n', encoding="ascii")
    environment = os.environ.copy()
    environment.update(QX_TERRAIN_FILTER_CONFIG=str(config), QX_TERRAIN_FILTER_DLL=str(dll),
                       QX_TERRAIN_HELPER_DIR=str(working.resolve()))
    # 临时读取器只加入本次隔离配置的可信目录；保持用户 CAD 安全级别与全局配置。
    profile = working / "acad-profile"
    profile.mkdir()
    status = _run([core, "/i", host, "/s", script, "/l", "en-US",
                   "/isolate", "QxTerrain" + uuid.uuid4().hex, profile], cwd=working,
                  env=environment, log=working / "autocad.log", token=token, timeout=300, completion_file=report)
    if not report.is_file():
        raise ValueError(f"AutoCAD 未完成地形筛选（退出码 {status}）；请先在 CAD 中另存 DXF 后导入")
    result = json.loads(report.read_text(encoding="utf-8-sig"))
    if status or not result.get("passed") or not Path(output).is_file():
        layers = sorted({key.rsplit("/", 1)[0] for key in result.get("source_layer_types", {})})
        detail = "；原图模型空间图层：" + "、".join(layers) if layers else ""
        raise ValueError("AutoCAD 地形筛选失败：" + result.get("error", f"退出码 {status}") + detail)
    result.update(reader="AutoCAD Core Console", helper_sha256=_hash(helper), core_console=str(core),
                  completion_basis="native_report_then_independent_dxf_audit")
    return result


def convert_dwg_to_dxf(source_path, output_path, *, cancelled=None, core_console=None, cache_dir=None):
    """Read a copied DWG in an isolated CAD process and preserve all layers.

    Layer choice belongs to the independent reader, so nonstandard survey
    layers can be confirmed without losing them during conversion. The user's
    live CAD session and original drawing are never opened for writing.
    """
    source, output = Path(source_path).resolve(), Path(output_path).resolve()
    if source == output or source.suffix.lower() != ".dwg" or not source.is_file():
        raise ValueError("DWG 转换必须读取现有原图并另存 DXF")
    class Token:
        def raise_if_cancelled(self):
            if cancelled and cancelled():
                raise InterruptedError("已取消 DWG 读取")

    token = Token()
    before = _hash(source, token)
    cache_root = Path(cache_dir) if cache_dir else source.parent / "地形自动净化" / ".dwg-cache"
    cache = cache_root / before
    cached_dxf, cached_report = cache / "survey.dxf", cache / "conversion.json"
    if cached_dxf.is_file() and cached_report.is_file():
        try:
            saved = json.loads(cached_report.read_text(encoding="utf-8"))
            if saved.get("source_sha256") == before and saved.get("dxf_sha256") == _hash(cached_dxf, token):
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(cached_dxf, output)
                return {**saved, "conversion_cache_hit": True, "conversion_cache_path": str(cached_dxf),
                        "source_unchanged": _hash(source, token) == before}
        except (OSError, ValueError):
            pass
    core = Path(core_console) if core_console else find_autocad_core()
    if not core.is_file():
        raise ValueError("配置的 AutoCAD Core Console 不存在")
    csc = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    if not csc.is_file():
        raise ValueError("DWG 自动读取组件不可用，请配置组件或将原图另存 DXF")
    output.parent.mkdir(parents=True, exist_ok=True)
    helper_source = '''using System;using System.IO;using System.Text;using System.Collections.Generic;
using System.Web.Script.Serialization;using Autodesk.AutoCAD.DatabaseServices;using Autodesk.AutoCAD.Runtime;
[assembly: CommandClass(typeof(QxSurveyExport))]
public class QxSurveyExport {
[CommandMethod("QXSURVEYEXPORT",CommandFlags.Session)]public void Export(){
var json=new JavaScriptSerializer();var cfg=json.Deserialize<Dictionary<string,string>>(File.ReadAllText(Environment.GetEnvironmentVariable("QX_SURVEY_EXPORT_CONFIG"),Encoding.UTF8));
var report=new Dictionary<string,object>();try{
using(var db=new Database(false,true)){db.ReadDwgFile(cfg["source"],FileOpenMode.OpenForReadAndReadShare,true,"");db.CloseInput(true);
report["source_insunits"]=(int)db.Insunits;db.DxfOut(cfg["output"],16,DwgVersion.AC1027);}report["passed"]=true;
}catch(System.Exception e){report["passed"]=false;report["error"]=e.ToString();}
File.WriteAllText(cfg["report"],json.Serialize(report),new UTF8Encoding(false));}}
'''
    with tempfile.TemporaryDirectory(prefix="qx-dwg-export-", ignore_cleanup_errors=True) as temporary:
        working = Path(temporary)
        helper, dll = working / "QxSurveyExport.cs", working / "QxSurveyExport.dll"
        helper.write_text(helper_source, encoding="utf-8")
        compile_log = working / "compile.log"
        status = _run([csc, "/nologo", "/target:library", "/platform:x64", f"/out:{dll}",
                       f"/reference:{core.parent / 'acdbmgd.dll'}", f"/reference:{core.parent / 'accoremgd.dll'}",
                       "/reference:System.Web.Extensions.dll", helper], cwd=working, env=os.environ.copy(),
                      log=compile_log, token=token, timeout=60)
        if status:
            raise ValueError("DWG 读取组件编译失败：" + compile_log.read_text(errors="replace")[-1200:])
        copied = working / "source.dwg"
        shutil.copyfile(source, copied)
        starters = [core.parent / "Drawing1.dwg", *sorted((core.parent / "Sample").glob("**/*.dwt"))]
        starter = next((v for v in starters if v.is_file()), copied)
        host = working / "host.dwg"
        shutil.copyfile(starter, host)
        host.chmod(stat.S_IWRITE | stat.S_IREAD)
        config, report_path = working / "config.json", working / "report.json"
        _write_json(config, {"source": str(copied), "output": str(output), "report": str(report_path)})
        script = working / "run.scr"
        script.write_text('(setq qx_original_trustedpaths (getvar "TRUSTEDPATHS"))\n'
                          '(setvar "TRUSTEDPATHS" (strcat qx_original_trustedpaths ";" (getenv "QX_SURVEY_HELPER_DIR")))\n'
                          '(command "_NETLOAD" (getenv "QX_SURVEY_EXPORT_DLL"))\n'
                          '(setvar "TRUSTEDPATHS" qx_original_trustedpaths)\nQXSURVEYEXPORT\n_QUIT\n', encoding="ascii")
        environment = os.environ.copy()
        environment.update(QX_SURVEY_EXPORT_CONFIG=str(config), QX_SURVEY_EXPORT_DLL=str(dll),
                           QX_SURVEY_HELPER_DIR=str(working))
        # A fresh /isolate folder copies the complete CAD installation on some
        # computers. Reuse our own profile; the active CAD profile stays untouched.
        profile_key = hashlib.sha256(str(core.resolve()).encode("utf-8")).hexdigest()[:16]
        profile = Path(tempfile.gettempdir()) / "qx-cad-profiles-v1" / profile_key
        profile.mkdir(parents=True, exist_ok=True)
        status = _run([core, "/i", host, "/s", script, "/l", "en-US", "/isolate",
                       "QxSurvey"+profile_key, profile], cwd=working, env=environment,
                      log=working / "autocad.log", token=token, timeout=300, completion_file=report_path)
        if not report_path.is_file():
            raise ValueError(f"DWG 自动读取未生成完成报告（状态 {status}），请配置读取组件或另存 DXF")
        report = json.loads(report_path.read_text(encoding="utf-8-sig"))
        if status or not report.get("passed") or not output.is_file():
            raise ValueError("DWG 自动读取失败："+report.get("error", str(status)))
    if _hash(source, token) != before:
        raise ValueError("DWG 读取期间原始文件发生变化，请保存完成后重新读取")
    receipt = {**report, "reader": "isolated_AutoCAD_readonly_DXF_export", "source_sha256": before,
               "dxf_sha256": _hash(output, token), "source_unchanged": True, "precision": 16,
               "core_console": str(core), "uses_rhino": False, "conversion_cache_hit": False,
               "isolated_profile_path": str(profile)}
    _write_json(profile / "ready.json", {"core_console": str(core), "passed": True})
    cache.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(output, cached_dxf)
    _write_json(cached_report, receipt)
    return receipt


def _audit_output(output, points_path, report, token, native_path=None):
    counts, actual_points, known_count, sampled_curves = Counter(), {}, 0, 0
    layer_names = set()
    native_path = Path(native_path or Path(output).with_name("terrain-native-sources.jsonl"))
    # 直接传递经过核对的中心折线，避免 Rhino DWG/DXF 导入器先生成数万个显示对象。
    with native_path.open("w", encoding="utf-8") as native:
        native.write(json.dumps({"kind": "header", "schema_version": "1.0"}) + "\n")
        _audit_entities(output, points_path, report, token, counts, actual_points, layer_names, native)
    report["native_sources_compatible"] = report["curves_requiring_native_sampling"] == 0
    if report["native_sources_compatible"]:
        report["native_sources_path"] = str(native_path)
        report["native_sources_sha256"] = _hash(native_path, token)
    else:
        native_path.unlink()


def _audit_entities(output, points_path, report, token, counts, actual_points, layer_names, native):
    known_count, sampled_curves = 0, 0
    # 完整逐条核对大文件，内存中只保留当前实体，避免再创建全图对象树。
    for index, entity in enumerate(iterdxf.modelspace(output)):
        if index % 256 == 0:
            _check(token)
        layer, kind = entity.dxf.layer.upper(), entity.dxftype()
        layer_names.add(entity.dxf.layer)
        counts[f"{layer}/{kind}"] += 1
        if entity.dxf.get("lineweight", -1) != 0:
            raise ValueError("筛选副本仍含非零显示线宽")
        if layer == "GCD" and kind == "POINT" and _marked_point(entity):
            handle = entity.get_xdata(PROVENANCE_APP)[1].value
            if handle in actual_points:
                raise ValueError("筛选后的 GCD 来源标识重复")
            actual_points[handle] = tuple(entity.dxf.location)
        elif layer in ("SQX", "JQX") and kind in CONTOUR_TYPES:
            if _clear_width(entity):
                raise ValueError("筛选副本仍含非零多段线宽度，已停止送入 Rhino")
        else:
            raise ValueError(f"筛选副本含不允许的对象：{layer}/{kind}")
        number = _known_point_count(entity)
        if number is None:
            sampled_curves += 1
        else:
            known_count += number
            if kind == "POINT":
                xyz = [list(entity.dxf.location)]
            elif kind == "LINE":
                xyz = [list(entity.dxf.start), list(entity.dxf.end)]
            else:
                positions = entity.vertices_in_wcs() if kind == "LWPOLYLINE" else entity.points_in_wcs()
                xyz = [list(point) for point in positions]
                closed = entity.closed if kind == "LWPOLYLINE" else entity.is_closed
                if closed:
                    xyz.append(xyz[0])
            if len(xyz) != number or any(not all(math.isfinite(value) for value in point) for point in xyz):
                raise ValueError("中心线的三维坐标或原始顶点数量无效")
            tags = entity.get_xdata(PROVENANCE_APP) if entity.has_xdata(PROVENANCE_APP) else []
            native.write(json.dumps({"kind": "point" if kind == "POINT" else "polyline",
                                     "layer": layer, "source_handle": _original_handle(entity),
                                     "source_kind": tags[0].value if tags else kind,
                                     "source_layer": tags[2].value if len(tags) > 2 else layer,
                                     "points": xyz}, allow_nan=False) + "\n")
    expected_count = 0
    with Path(points_path).open(encoding="utf-8") as stream:
        for row in stream:
            value = json.loads(row)
            actual = actual_points.pop(value["handle"], None)
            if actual is None or not all(math.isfinite(a) and abs(a - b) <= 1e-8 for a, b in zip(actual, value["xyz"])):
                raise ValueError("GCD 原三维测点与输出点不一致，已停止送入 Rhino")
            expected_count += 1
    if actual_points or expected_count != report["gcd_insert_count"]:
        raise ValueError("GCD 来源核对数量不一致")
    contour_count = sum(count for key, count in counts.items() if not key.startswith("GCD/"))
    if contour_count != report["contour_count"]:
        raise ValueError("等高线克隆数量不一致")
    report.update(output_layer_types=dict(counts), output_entity_count=sum(counts.values()),
                  point_count_lower_bound=known_count, curves_requiring_native_sampling=sampled_curves,
                  layer_names=sorted(layer_names),
                  gcd_coordinates_verified=True, widths_zero_verified=True)
    native.write(json.dumps({"kind": "end", "point_count": known_count, "entity_count": sum(counts.values())}) + "\n")


def prepare_terrain_source(source_path, output_dir, *, cancel_token=None, core_console=None):
    """核对原始副本，另存剔除明显异常高程后的建网资源和处理依据。"""
    source = Path(source_path).resolve()
    if source.suffix.lower() not in (".dwg", ".dxf") or not source.is_file():
        raise ValueError("请选择现有 DWG 或 DXF 地形文件")
    source_hash = _hash(source, cancel_token)
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    # 每次独立输出，取消或切换工程不会覆盖此前可核对的副本。
    destination = Path(tempfile.mkdtemp(prefix="terrain-", dir=root))
    output, points_path = destination / "terrain-filtered.dxf", destination / "gcd-source-points.jsonl"
    try:
        with tempfile.TemporaryDirectory(prefix="qx-terrain-", ignore_cleanup_errors=True) as temporary:
            if source.suffix.lower() == ".dwg":
                report = _filter_dwg(source, output, points_path, Path(temporary), cancel_token, core_console)
            else:
                report = _filter_dxf(source, output, points_path, cancel_token)
            _check(cancel_token)
            _audit_output(output, points_path, report, cancel_token)
        if report["native_sources_compatible"]:
            from .terrain_quality import clean_native_sources_file
            raw_path = Path(report["native_sources_path"])
            cleaned_path = destination / "terrain-quality-sources.jsonl"
            quality_path = destination / "terrain-quality-report.json"
            quality = clean_native_sources_file(raw_path, cleaned_path, quality_path,
                                               cancel_token=cancel_token)
            report.update(raw_native_sources_path=str(raw_path),
                          raw_native_sources_sha256=report["native_sources_sha256"],
                          native_sources_path=str(cleaned_path), native_sources_sha256=_hash(cleaned_path, cancel_token),
                          quality_report_path=str(quality_path), quality_report_sha256=_hash(quality_path, cancel_token),
                          quality_filter=quality,
                          retained_point_count=quality["output_point_count"])
        if _hash(source, cancel_token) != source_hash:
            raise ValueError("前处理期间原图发生变化，请保存完成后重新导入")
        report.update(schema_version="1.0", source_path=str(source), source_sha256=source_hash,
                      source_bytes=source.stat().st_size, output_path=str(output), output_sha256=_hash(output, cancel_token),
                      output_bytes=output.stat().st_size, filter_layers=list(TERRAIN_LAYERS),
                      ignored_entities=report["scanned_model_entities"] - report["output_entity_count"],
                      source_unchanged=True, rule="GCD_INSERT_OR_RECOGNIZED_CIRCLE_WCS_POINT; SQX_JQX_OR_RECOGNIZED_GCD_CENTERLINE; WIDTH_ZERO; NO_DECIMATION")
        report_path = destination / "terrain-filter-report.json"
        _write_json(report_path, report)
        _check(cancel_token)
        return {"source_path": str(output), "report_path": str(report_path), "report": report}
    except BaseException:
        shutil.rmtree(destination)
        raise
