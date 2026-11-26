"""Preserve explicitly reviewed DXF coverage and pending chainage intervals."""
from copy import deepcopy

from .design_profiles import clip_design_profile, evaluate_profile, profile_break_stations


def awaiting_water_profile_parts(asset):
    return bool(asset.get("water_profile_parts") and not asset.get("design_profile")
                and asset.get("pipe_profile_choice") not in {"cover_depth","quantity_dxf","pending_gap"})


def _root(asset):
    return (asset.get("section_scheme_root_asset_id") or asset.get("drawing_root_asset_id")
            or asset.get("parent_asset_id") or asset["asset_id"])


def pending_gap_record(asset, route):
    return {"code":"pipe_profile_gap","asset_id":asset["asset_id"],"route_id":route,
            "name":asset.get("name"),"station_start":asset["station_start"],"station_end":asset["station_end"],
            "length_m":asset["station_end"]-asset["station_start"],"reason":"设计纵断面缺口待补"}


def pending_gap_section(inputs, asset_id, station, side):
    matches=[]
    for n in inputs.get("networks",[]):
        route=str(n.get("route_id") or n.get("network_id") or n.get("name") or "")
        for asset in n.get("assets",[]):
            part=asset.get("pipe_profile_partition")
            if not part:continue
            aliases={asset["asset_id"],_root(asset)}
            if asset_id not in aliases and asset_id not in {f"{route}::{k}" for k in aliases}:continue
            a,b=asset["station_start"],asset["station_end"]
            if a<=station<=b:matches.append((asset,route))
    if len(matches)>1:
        matches=[(a,r) for a,r in matches if (a["station_start"]<=station<a["station_end"] if side=="right"
                 else a["station_start"]<station<=a["station_end"])]
    if len(matches)!=1 or matches[0][0].get("pipe_profile_choice")!="pending_gap":return None
    from ..io.concise_quantities import station_label
    asset,route=matches[0]
    row=pending_gap_record(asset,route)
    return {"section_id":f"skipped-{asset_id}-{float(station).hex()}-{side}", "asset_id":asset_id,
            "station":station,"side":side,"view_only":True,"skipped":True,"skip_code":row["code"],
            "excluded_range":row,"roles":{},"message":f"设计纵断面缺口待补　{station_label(row['station_start'])}～{station_label(row['station_end'])}"}


def resolve_profile_gap(asset):
    partition = asset.get("pipe_profile_partition")
    if partition and partition["coverage"]=="pending":
        asset["enabled"] = partition["enabled_before_gap"]
        partition["coverage"] = "mapped"


def _set_pending(asset):
    asset.update(enabled=False, pipe_profile_choice="pending_gap")
    construction=asset.setdefault("construction",{})
    construction["burial_mode"]="actual_axis"
    construction.pop("axis_confirmed",None)
    for key in ("design_profile","profile_points","axis_source","profile_source","profile_source_file",
                "profile_import_mapping","cover_confirmation","cover_preview_confirmed","axis_cover_samples",
                "axis_preview_sha256","cover_generation_options","cover_actual_cover_summary"):
        asset.pop(key,None)
    asset.setdefault("alignment",{}).pop("profile_points",None)
    missing=asset.setdefault("missing_fields",[])
    if "design_profile" not in missing:missing.append("design_profile")


def partition_piece(asset, start, end, coverage, *, previous=None):
    part = deepcopy(asset)
    info = previous or asset.get("pipe_profile_partition") or {}
    root = info.get("root_asset_id") or _root(asset)
    part.update(asset_id=f"{root}:profile:{start:.12g}:{end:.12g}",station_start=start,station_end=end,
                section_scheme_root_asset_id=root,drawing_root_asset_id=root,parent_asset_id=root,geometry_sections=[])
    part["pipe_profile_partition"] = {
        **deepcopy(info),"root_asset_id":root,"source_asset_id":info.get("source_asset_id",asset["asset_id"]),
        "source_station_range_m":info.get("source_station_range_m",[asset["station_start"],asset["station_end"]]),
        "enabled_before_gap":info.get("enabled_before_gap",asset.get("enabled",True)),"coverage":coverage,
    }
    if info.get("coverage")=="pending" and coverage=="mapped":
        part["enabled"]=part["pipe_profile_partition"]["enabled_before_gap"]
    # Staged workbench preferences may themselves contain a partially supplied
    # profile. Retain a backup only on intervals it genuinely covers.
    for key in ("design_profile","original_design_profile","water_profile_design_profile"):
        if part.get(key):
            try:part[key]=clip_design_profile(part[key],start,end)
            except ValueError:part.pop(key,None)
    if part.get("water_profile_parts"):
        from .pipe_profile_sources import _local_water_geometry
        whole,runs=_local_water_geometry(part.pop("water_profile_parts"),start,end)
        if whole:part["water_profile_design_profile"]=whole
        elif runs:part["water_profile_parts"]=runs
    if part.get("design_profile"):
        p=part["design_profile"]
        points=[{"station":s,"elevation":evaluate_profile(p,s)[0]} for s in profile_break_stations(p)]
        part["profile_points"]=points
        part.setdefault("alignment",{})["profile_points"]=deepcopy(points)
    construction=part.setdefault("construction",{})
    if construction.get("cover_segments"):
        construction["cover_segments"]=[dict(segment,station_start=max(start,segment["station_start"]),
            station_end=min(end,segment["station_end"])) for segment in construction["cover_segments"]
            if min(end,segment["station_end"])-max(start,segment["station_start"])>1e-7]
    if part.get("section_scheme_binding"):
        from .section_scheme_bindings import _clip_record, _metadata
        _metadata(part,_clip_record(part["section_scheme_binding"],start,end))
    if coverage=="pending":_set_pending(part)
    return part


def restore_pipe_profile_partitions(inputs, previous_inputs):
    """Replay explicit source boundaries over corresponding fresh pipe assets in place."""
    def route(n):
        return (n.get("source_identity"), n.get("network_id") or n.get("route_id"))
    history={}
    for network in previous_inputs.get("networks",[]):
        for asset in network.get("assets",[]):
            info=asset.get("pipe_profile_partition")
            if info:
                key=(route(network),info["root_asset_id"])
                history.setdefault(key,[]).append(asset)
    for network in inputs.get("networks",[]):
        fresh=[]
        for asset in network.get("assets",[]):
            rows=history.get((route(network),_root(asset)),[])
            a,b=asset.get("station_start"),asset.get("station_end")
            if not rows or a is None or b is None or asset.get("kind") not in {"pipe","pressure_pipe"}:
                fresh.append(asset)
                continue
            rows=[r for r in rows if r.get("source_identity")==asset.get("source_identity")
                  and min(b,r["station_end"])-max(a,r["station_start"])>1e-7]
            if not rows:
                fresh.append(asset)
                continue
            cuts=sorted({a,b,*(max(a,min(b,r[k])) for r in rows for k in ("station_start","station_end"))})
            for left,right in zip(cuts,cuts[1:]):
                old=next((r for r in rows if r["station_start"]<=left+1e-7 and r["station_end"]>=right-1e-7),None)
                if old is None and left==a and right==b:
                    fresh.append(asset)
                    continue
                info=old.get("pipe_profile_partition") if old else None
                fresh.append(partition_piece(asset,left,right,info["coverage"] if info else "mapped",previous=info))
        network["assets"]=fresh
