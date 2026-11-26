"""Reversible station-range scope for automatically detected unsupported pipes.

The detector owns the terrain/pipe test.  This module preserves the exact
profiles, adopted construction bindings and subsequent user edits while
temporarily omitting only its reported station intervals.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from numbers import Real

from .design_profiles import clip_design_profile, evaluate_profile, profile_break_stations
from .section_scheme_bindings import _clip_record, _root, _route, _digest as _binding_digest


AUTOMATIC_UNSUPPORTED_PIPE_POLICY = "automatic_unsupported_pipe_ranges_v1"
AUTOMATIC_UNSUPPORTED_PIPE_CODE = "automatic_unsupported_pipe_range"
AUTOMATIC_UNSUPPORTED_PIPE_FIELD = "automatic_unsupported_pipe_ranges"
_ORIGIN = "automatic_unsupported_pipe_origin"
_INACTIVE_DRAWINGS = "automatic_unsupported_pipe_inactive_drawings"
_EPS = 1e-7


@dataclass(frozen=True)
class _RangeScopePolicy:
    key: str
    code: str
    field: str
    origin: str
    inactive_drawings: str
    label: str
    child_label: str
    excluded_label: str
    reason: str
    terrain_gaps: bool = False


_PIPE_SCOPE = _RangeScopePolicy(
    AUTOMATIC_UNSUPPORTED_PIPE_POLICY, AUTOMATIC_UNSUPPORTED_PIPE_CODE,
    AUTOMATIC_UNSUPPORTED_PIPE_FIELD, _ORIGIN, _INACTIVE_DRAWINGS, "悬空区段",
    "supported", "unsupported", "管道悬空",
)


def _plain(value):
    if isinstance(value, dict):return {str(k):_plain(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)):return [_plain(v) for v in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):return value
    if isinstance(value, Real):return float(value)
    if hasattr(value, "to_dict"):return _plain(value.to_dict())
    if hasattr(value, "tolist"):return _plain(value.tolist())
    raise TypeError("Unsupported saved scope value: "+type(value).__name__)


def _digest(value):
    raw=json.dumps(_plain(value),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
    return hashlib.sha256(raw.encode("utf8")).hexdigest()


def _network_key(network):
    return str(network.get("network_id") or network.get("route_id") or network.get("source_identity") or "")


def _route_aliases(network):
    return {str(network[k]) for k in ("network_id","route_id","source_identity") if network.get(k) is not None}


def _origin_key(network, asset):
    return _digest([_network_key(network),asset["asset_id"],asset["station_start"],asset["station_end"]])[:24]


def _part_id(network, asset, start, end, policy):
    # The root and stations stay stable across repeated calculations.  Never
    # append a fresh suffix to the previous automatic child's identifier.
    route=_digest(_network_key(network))[:8]
    return f"{_root(asset)}:{policy.child_label}:{route}:{start:.9f}:{end:.9f}"


def _merge(ranges, start, end, policy):
    values=[]
    for a,b in ranges:
        a,b=float(a),float(b)
        if not math.isfinite(a+b):raise ValueError(f"{policy.label}桩号须为有限数值")
        a,b=max(start,a),min(end,b)
        if b>a+_EPS:values.append((a,b))
    answer=[]
    for a,b in sorted(values):
        if answer and a<=answer[-1][1]+_EPS:answer[-1]=(answer[-1][0],max(b,answer[-1][1]))
        else:answer.append((a,b))
    return answer


def _complement(start, end, ranges, policy):
    cursor=start;answer=[]
    for a,b in _merge(ranges,start,end,policy):
        if a>cursor+_EPS:answer.append((cursor,a))
        cursor=b
    if end>cursor+_EPS:answer.append((cursor,end))
    return answer


def _clip_asset(asset, start, end, policy, *, identifier=None):
    part=deepcopy(asset)
    changed=abs(start-float(asset["station_start"]))>_EPS or abs(end-float(asset["station_end"]))>_EPS
    if changed:
        part.update(station_start=start,station_end=end,parent_asset_id=_root(asset),drawing_root_asset_id=_root(asset))
        if part.get("design_profile"):
            part["design_profile"]=clip_design_profile(asset["design_profile"],start,end)
            points=[{"station":s,"elevation":evaluate_profile(part["design_profile"],s)[0]}
                    for s in profile_break_stations(part["design_profile"])]
            part["profile_points"]=points
            part.setdefault("alignment",{})["profile_points"]=deepcopy(points)
        part["geometry_sections"]=[]
    if identifier is not None:part["asset_id"]=identifier
    part.pop(policy.origin,None)
    return part


_EDITABLE_FIELDS=("section","construction","design_profile","profile_points","alignment","enabled",
    "parameter_sources","drawing_user_overrides","section_scheme_user_overrides",
    "section_scheme_terrain_variants","section_scheme_selectors","axis_source","profile_source_file",
    "profile_source","source_identity","source_type","kind","section_type")


def _editable(asset):
    facts={k:asset[k] for k in _EDITABLE_FIELDS if k in asset}
    facts["enabled"]=asset.get("enabled",True)
    binding=asset.get("section_scheme_binding") or asset.get("inactive_section_scheme_binding")
    if binding:
        facts["scheme_choice"]={k:binding.get(k) for k in ("scheme_id","scheme_sha256","resolved_fields","overrides")}
    return facts


def _scope_record(record, policy):
    keys=("asset_id","network_id","route_id","source_asset_id","source_asset_ref","name","source_identity","station_start",
        "station_end","length_m","code","reason","scope_status","policy")
    if policy.terrain_gaps:
        keys+=("parent_asset_id","source_original_asset_id","original_asset_id","route_name","source_type","kind")
    return {k:record.get(k) for k in keys}


def _automatic(record, policy):
    return record.get("code")==policy.code and record.get("policy")==policy.key


def _rebuild_bindings(inputs, affected, drawing_sources, policy):
    """Adopt exact per-part scopes using the ordinary binding hash contract."""
    if not affected:return
    records=[r for r in inputs.get("section_scheme_bindings",[])
             if (str(r.get("route_id")),str(r.get("asset_id"))) not in affected]
    direct=[r for r in inputs.get("drawing_bindings",[])
            if (str(r.get("route_id") or r.get("network_id")),str(r.get("asset_id"))) not in affected]
    for network in inputs.get("networks",[]):
        for part in network.get("assets",[]):
            key=(_route(network),_root(part))
            if key not in affected:continue
            a,b=part["station_start"],part["station_end"]
            binding=part.get("section_scheme_binding") or part.get("inactive_section_scheme_binding")
            if not part.get("enabled",True):
                if binding:
                    part["inactive_section_scheme_binding"]=deepcopy(binding)
                    part.pop("section_scheme_binding",None)
                inactive=[]
                for row in drawing_sources:
                    owner=(str(row.get("route_id") or row.get("network_id")),str(row.get("asset_id")))
                    lo,hi=max(a,row["station_start"]),min(b,row["station_end"])
                    if owner==key and hi>lo+_EPS:
                        saved=deepcopy(row);saved.update(station_start=lo,station_end=hi);inactive.append(saved)
                if inactive:part[policy.inactive_drawings]=inactive
            elif binding:
                current=_clip_record(binding,a,b)
                part["section_scheme_binding"]=current
                part.pop("inactive_section_scheme_binding",None)
                records.append(deepcopy(current))
            if part.get("enabled",True):
                for record in drawing_sources:
                    owner=(str(record.get("route_id") or record.get("network_id")),str(record.get("asset_id")))
                    if owner!=key:continue
                    lo,hi=max(a,record["station_start"]),min(b,record["station_end"])
                    if hi>lo+_EPS:
                        current=deepcopy(record);current.update(station_start=lo,station_end=hi);direct.append(current)
                part.pop(policy.inactive_drawings,None)
            for field in ("drawing_binding","section_scheme_material_sources"):
                if isinstance(part.get(field),dict) and "station_start" in part[field]:
                    part[field].update(station_start=a,station_end=b)
            for row in part.get("drawing_bindings",[]):
                if isinstance(row,dict) and "station_start" in row:row.update(station_start=a,station_end=b)
    if "section_scheme_bindings" in inputs or records:
        inputs["section_scheme_bindings"]=records
        inputs.setdefault("quantity_basis",{})["section_scheme_binding_sha256"]=_binding_digest(records)
    if "drawing_bindings" in inputs or direct:
        inputs["drawing_bindings"]=direct
        inputs.setdefault("quantity_basis",{}).update(drawing_binding_sha256=_binding_digest(direct),drawing_binding_count=len(direct))


def _manual_blocks(inputs, network, original, policy):
    start,end=original["station_start"],original["station_end"]
    aliases=_route_aliases(network);answer=[]
    original_ids={str(original["asset_id"]),_root(original)}
    for record in inputs.get("excluded",[]):
        if _automatic(record,policy):continue
        owner=record.get("route_id") or record.get("network_id")
        if owner is not None and str(owner) not in aliases:continue
        identity_fields=("asset_id","source_asset_id","parent_asset_id","drawing_root_asset_id",
            "section_scheme_root_asset_id","original_asset_id")
        identities={str(r[k]) for r in [record,record.get("original_asset_snapshot") or {}]
                    for k in identity_fields if r.get(k) is not None}
        same=bool(original_ids&identities)
        source=record.get("source_identity")
        if not identities and source is not None and original.get("source_identity") is not None:
            same=_digest(source)==_digest(original["source_identity"])
        route_wide=record.get("scope_kind") in {"route","network"} or record.get("scope") in {"route","network"}
        if (same or route_wide) and record.get("station_start") is not None and record.get("station_end") is not None:
            answer.append((record["station_start"],record["station_end"]))
    return _merge(answer,start,end,policy)


def restore_automatic_exclusions(inputs, *, _policy=_PIPE_SCOPE):
    """Return a copy with this policy's old gaps restored before fresh detection.

    Unedited children collapse back to their original asset. Edited/disabled
    children retain their exact current profiles and construction; only the
    other spans are restored from the single saved source snapshot.
    """
    result=deepcopy(inputs)
    state=result.get(_policy.field)
    reactivated={(_route(n),_root(a)) for n in result.get("networks",[]) for a in n.get("assets",[])
        if a.get("enabled",True) and (a.get("inactive_section_scheme_binding") or a.get(_policy.inactive_drawings))}
    inactive_drawings=[deepcopy(r) for n in result.get("networks",[]) for a in n.get("assets",[])
        if a.get("enabled",True) for r in a.get(_policy.inactive_drawings,[])]
    if not isinstance(state,dict) or state.get("policy")!=_policy.key:
        _rebuild_bindings(result,reactivated,[*result.get("drawing_bindings",[]),*inactive_drawings],_policy)
        return result
    result.pop(_policy.field,None)
    result["excluded"]=[r for r in result.get("excluded",[]) if not _automatic(r,_policy)]
    affected=set()
    for source in state.get("source_assets",[]):
        network=next((n for n in result.get("networks",[]) if _network_key(n)==source["network_id"]),None)
        if network is None:continue
        original=source["asset"]
        key=source["source_asset_ref"]
        children=[a for a in network.get("assets",[]) if (a.get(_policy.origin) or {}).get("source_asset_ref")==key
                  and (a.get(_policy.origin) or {}).get("policy")==_policy.key]
        others=[a for a in network.get("assets",[]) if a not in children]
        edited=[]
        for child in children:
            expected=_clip_asset(original,child["station_start"],child["station_end"],_policy)
            if _digest(_editable(child))!=_digest(_editable(expected)):
                current=deepcopy(child);current.pop(_policy.origin,None);edited.append(current)
        blocked=_manual_blocks(result,network,original,_policy)
        # A disabled user-owned sibling remains user-owned, including when it
        # was split from an automatic child in the editor.
        for other in others:
            if (not other.get("enabled", True) and _root(other) == _root(original)
                    and other.get("station_start") is not None and other.get("station_end") is not None):
                blocked.append((other["station_start"], other["station_end"]))
        blocked=_merge(blocked,original["station_start"],original["station_end"],_policy)
        protected=blocked+[(a["station_start"],a["station_end"]) for a in edited]
        restored=[]
        for a,b in _complement(original["station_start"],original["station_end"],protected,_policy):
            identifier=original["asset_id"] if not edited and not blocked else _part_id(network,original,a,b,_policy)
            restored.append(_clip_asset(original,a,b,_policy,identifier=identifier))
        for current in edited:
            for a,b in _complement(current["station_start"],current["station_end"],blocked,_policy):
                restored.append(_clip_asset(current,a,b,_policy,identifier=_part_id(network,original,a,b,_policy)))
        # Replace in-place in route order without changing unrelated assets.
        insertion=min((i for i,a in enumerate(network["assets"]) if a in children),default=min(source["index"],len(others)))
        others[insertion:insertion]=sorted(restored,key=lambda a:a["station_start"])
        network["assets"]=others
        affected.add((_route(network),_root(original)))
    extra_drawings=[r for r in result.get("drawing_bindings",[])
        if (str(r.get("route_id") or r.get("network_id")),str(r.get("asset_id"))) in reactivated-affected]
    _rebuild_bindings(result,affected|reactivated,
        [*state.get("source_drawing_bindings",[]),*extra_drawings,*inactive_drawings],_policy)
    return result


def _active_signature(inputs, policy):
    return [{"network_id":_network_key(n),"asset_id":a["asset_id"],"station_start":a["station_start"],
        "station_end":a["station_end"],"origin":a[policy.origin],"editable_sha256":_digest(_editable(a))}
        for n in inputs.get("networks",[]) for a in n.get("assets",[])
        if (a.get(policy.origin) or {}).get("policy")==policy.key]


def _report(state, policy):
    total=math.fsum(r["length_m"] for r in state["ranges"])
    return {"policy":policy.key,"evaluation_complete":True,
        "range_count":len(state["ranges"]),"source_asset_count":len(state["source_assets"]),
        "excluded_length_m":total,"total_length_m":total,
        "ranges":deepcopy(state["ranges"]),"baseline_sha256":state["baseline_sha256"],
        "scoped_assets_sha256":state["scoped_assets_sha256"]}


def automatic_scope_report(inputs, *, _policy=_PIPE_SCOPE):
    """Return the completed detection/scope evidence for a new result payload."""
    state=inputs.get(_policy.field)
    if not isinstance(state,dict) or state.get("policy")!=_policy.key:
        raise ValueError(f"本次尚未完成{_policy.label}识别")
    return _report(state,_policy)


def has_automatic_source_assets(inputs, *, _policy=_PIPE_SCOPE):
    state=inputs.get(_policy.field)
    return isinstance(state,dict) and state.get("policy")==_policy.key and bool(state.get("source_assets"))


def apply_detected_exclusions(inputs, detected_ranges, *, _policy=_PIPE_SCOPE):
    """Return (copied_inputs, report) for detector network/asset/global ranges."""
    result=restore_automatic_exclusions(inputs,_policy=_policy)
    rows=list(detected_ranges);consumed=set();sources=[];records=[];affected=set()
    for row in rows:
        route=row.get("network_id") or row.get("route_id")
        owners=[(n,a) for n in result.get("networks",[]) for a in n.get("assets",[])
            if a.get("asset_id")==row.get("asset_id")
            and (route is None or str(route) in _route_aliases(n))]
        if len(owners)!=1:raise ValueError(f"{_policy.label}无法唯一对应当前线路及原始对象")
    for network in result.get("networks",[]):
        assets=[]
        for index,original in enumerate(network.get("assets",[])):
            selected=[]
            for i,row in enumerate(rows):
                route=row.get("network_id") or row.get("route_id")
                if row.get("asset_id")!=original["asset_id"]:continue
                if route is not None and str(route) not in _route_aliases(network):continue
                consumed.add(i)
                if not original.get("enabled",True):continue
                from .earthwork_scope import trenchless_method
                if trenchless_method(original):continue
                selected.append((row["station_start"],row["station_end"]))
            cuts=_merge(selected,original["station_start"],original["station_end"],_policy)
            if not cuts:assets.append(original);continue
            origin=_origin_key(network,original)
            sources.append({"network_id":_network_key(network),"source_asset_ref":origin,"index":index,"asset":deepcopy(original)})
            affected.add((_route(network),_root(original)))
            for a,b in _complement(original["station_start"],original["station_end"],cuts,_policy):
                part=_clip_asset(original,a,b,_policy,identifier=_part_id(network,original,a,b,_policy))
                part[_policy.origin]={"policy":_policy.key,"source_asset_ref":origin,
                    "source_asset_id":original["asset_id"],"network_id":_network_key(network)}
                assets.append(part)
            for a,b in cuts:
                record={"asset_id":f"{_root(original)}:{_policy.excluded_label}:{_digest([origin,a,b])[:16]}",
                    "network_id":_network_key(network),"route_id":_route(network),
                    "source_asset_id":original["asset_id"],"source_asset_ref":origin,
                    "name":original.get("name"),"source_identity":deepcopy(original.get("source_identity")),
                    "kind":original.get("kind"),"section_type":original.get("section_type"),"source_type":original.get("source_type"),
                    "station_start":a,"station_end":b,"length_m":b-a,"enabled":False,
                    "code":_policy.code,"policy":_policy.key,
                    "scope_status":"automatic_excluded_interval","reason":_policy.reason}
                if _policy.terrain_gaps:
                    record.update(route_name=network.get("name") or _route(network),
                        parent_asset_id=_root(original),
                        source_original_asset_id=original.get("source_original_asset_id"),
                        original_asset_id=original.get("original_asset_id"))
                else:
                    witnesses=[row for row in rows if row.get("asset_id")==original["asset_id"]
                        and ((row.get("network_id") or row.get("route_id")) is None
                             or str(row.get("network_id") or row.get("route_id")) in _route_aliases(network))
                        and row["station_end"]>a and row["station_start"]<b]
                    if witnesses:
                        record["maximum_support_gap_m"]=max(float(r.get("maximum_support_gap_m",0.)) for r in witnesses)
                        record["pipe_indices"]=sorted({p for r in witnesses for p in r.get("pipe_indices",[])})
                records.append(record)
        network["assets"]=assets
    if len(consumed)!=len(rows):raise ValueError(f"{_policy.label}没有对应的当前线路或原始对象")
    scheme_sources=[deepcopy(r) for r in result.get("section_scheme_bindings",[])
        if (str(r.get("route_id")),str(r.get("asset_id"))) in affected]
    drawing_sources=[deepcopy(r) for r in result.get("drawing_bindings",[])
        if (str(r.get("route_id") or r.get("network_id")),str(r.get("asset_id"))) in affected]
    _rebuild_bindings(result,affected,drawing_sources,_policy)
    result.setdefault("excluded",[]).extend(records)
    state={"policy":_policy.key,"evaluation_complete":True,"source_assets":sources,
        "source_section_scheme_bindings":scheme_sources,"source_drawing_bindings":drawing_sources,
        "ranges":[_scope_record(r,_policy) for r in records]}
    state["baseline_sha256"]=_digest({k:state[k] for k in ("source_assets","source_section_scheme_bindings","source_drawing_bindings")})
    state["scoped_assets_sha256"]=_digest(_active_signature(result,_policy))
    result[_policy.field]=state
    report=_report(state,_policy)
    return result,report


def automatic_scope_matches_snapshot(payload, source, *, _policy=_PIPE_SCOPE):
    """Verify new-result scope, immutable baseline and exact exported list."""
    try:
        state=source[_policy.field]
        if state.get("policy")!=_policy.key or state.get("evaluation_complete") is not True:return False
        if state["baseline_sha256"]!=_digest({k:state[k] for k in ("source_assets","source_section_scheme_bindings","source_drawing_bindings")}):return False
        if state["scoped_assets_sha256"]!=_digest(_active_signature(source,_policy)):return False
        if payload.get(_policy.field)!=_report(state,_policy):return False
        expected=state["ranges"]
        if [_scope_record(r,_policy) for r in source.get("excluded",[]) if _automatic(r,_policy)]!=expected:return False
        if [_scope_record(r,_policy) for r in payload.get("excluded_assets",[]) if _automatic(r,_policy)]!=expected:return False
        embedded=(payload.get("inputs") or {}).get("workbench")
        if embedded is not None and embedded.get(_policy.field)!=state:return False
        origins={s["source_asset_ref"]:s for s in state["source_assets"]}
        coverage={key:[] for key in origins}
        for network in source.get("networks",[]):
            for asset in network.get("assets",[]):
                origin=asset.get(_policy.origin) or {}
                if origin.get("policy")!=_policy.key:continue
                key=origin["source_asset_ref"]
                if key not in origins or _network_key(network)!=origins[key]["network_id"]:return False
                coverage[key].append((asset["station_start"],asset["station_end"]))
        for row in expected:
            original=origins[row["source_asset_ref"]]["asset"]
            a,b=row["station_start"],row["station_end"]
            if not (original["station_start"]<=a<b<=original["station_end"]):return False
            if not math.isclose(b-a,row["length_m"],rel_tol=0,abs_tol=1e-9):return False
            coverage[row["source_asset_ref"]].append((a,b))
        for key,spans in coverage.items():
            original=origins[key]["asset"];cursor=original["station_start"]
            for a,b in sorted(spans):
                if abs(a-cursor)>_EPS or b<=a:return False
                cursor=b
            if abs(cursor-original["station_end"])>_EPS:return False
        return True
    except (KeyError,TypeError,ValueError):return False
