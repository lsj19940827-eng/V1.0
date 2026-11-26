"""Read-only plan display from an existing TIN; no triangulation or filtering.

Run this module in a worker. Contours intersect the actual original triangular
faces with horizontal planes, and effective boundaries are the mesh's naked
edges, including holes. Display selection never introduces domain closures.
"""
from __future__ import annotations

import math
import numpy as np


def _check(cancelled):
    if cancelled and cancelled():raise InterruptedError("已停止地形显示生成")


def _intersects(xyz, bounds):
    if bounds is None:return np.ones(len(xyz),dtype=bool)
    low,high=xyz[:,:,:2].min(axis=1),xyz[:,:,:2].max(axis=1)
    return ((high[:,0]>=bounds[0]) & (high[:,1]>=bounds[1]) &
            (low[:,0]<=bounds[2]) & (low[:,1]<=bounds[3]))


def _edges(faces):
    return np.sort(faces[:,[[0,1],[1,2],[2,0]]],axis=2).reshape(-1,2)


def _naked_edges(edges, point_count, cancelled):
    _check(cancelled)
    if not len(edges):return np.empty((0,2),dtype=np.int64)
    # Integer sort needs substantially less memory/time than sorting XYZ rows.
    encoded=edges[:,0].astype(np.uint64)*np.uint64(point_count)+edges[:,1].astype(np.uint64)
    values,counts=np.unique(encoded,return_counts=True);_check(cancelled)
    values=values[counts==1]
    return np.column_stack((values//np.uint64(point_count),values%np.uint64(point_count))).astype(np.int64)


def _nice_interval(span):
    if span<=0:return 1.
    target=span/40.;scale=10.**math.floor(math.log10(target))
    return next(v*scale for v in (1.,2.,5.,10.) if v*scale>=target)


def _deduplicate(segments,cancelled):
    if not segments:return np.empty((0,2,3),dtype=float)
    xyz=np.concatenate(segments);_check(cancelled)
    reverse=(xyz[:,0,0]>xyz[:,1,0]) | ((xyz[:,0,0]==xyz[:,1,0]) & (xyz[:,0,1]>xyz[:,1,1]))
    xyz[reverse]=xyz[reverse,::-1,:]
    xyz=np.unique(xyz.reshape(-1,6),axis=0).reshape(-1,2,3);_check(cancelled)
    return xyz[np.any(xyz[:,0,:2]!=xyz[:,1,:2],axis=1)]


def _contours(points,selected,levels,chunk_size,cancelled,max_segments):
    lines=[[] for _ in levels];total=0
    for first in range(0,len(selected),chunk_size):
        _check(cancelled);faces=selected[first:first+chunk_size];xyz=points[faces]
        low,high=xyz[:,:,2].min(axis=1),xyz[:,:,2].max(axis=1)
        for k,level in enumerate(levels):
            _check(cancelled);active=(low<=level)&(high>=level)
            if not active.any():continue
            local=faces[active];coords=xyz[active]
            flat=np.all(coords[:,:,2]==level,axis=1)
            # A coplanar face is a 2D level region, not an isoline. Its internal
            # diagonals and display-selection perimeter must never be plotted.
            # Adjacent noncoplanar faces retain the actual level-region edges.
            local=local[~flat]
            if not len(local):continue
            edges=_edges(local).reshape(-1,3,2);p=points[edges]
            z0,z1=p[:,:,0,2],p[:,:,1,2]
            # Half-open crossings give two unique vertices even when a plane
            # passes through a source vertex; tangent single points are omitted.
            cross=((z0<=level)&(z1>level))|((z1<=level)&(z0>level))
            pairs=cross.sum(axis=1)==2
            if pairs.any():
                edge_points=p[pairs][cross[pairs]]
                ratio=(level-edge_points[:,0,2])/(edge_points[:,1,2]-edge_points[:,0,2])
                cut=edge_points[:,0]+ratio[:,None]*(edge_points[:,1]-edge_points[:,0])
                cut[:,2]=level;segment=cut.reshape(-1,2,3)
                lines[k].append(segment);total+=len(segment)
            horizontal=(z0==level)&(z1==level)
            if horizontal.any():
                segment=p[horizontal];lines[k].append(segment);total+=len(segment)
            if total>max_segments*2:
                raise ValueError("显示等高线过密，请增大图面等高距")
    result=[];total=0
    for level,pieces in zip(levels,lines):
        _check(cancelled)
        segments=_deduplicate(pieces,cancelled);total+=len(segments)
        if total>max_segments:raise ValueError("显示等高线过密，请增大图面等高距")
        if len(segments):result.append({"elevation":float(level),"segments":segments})
    return result


def _source_layers(tin,bounds,cancelled,max_points):
    raw=np.asarray(getattr(tin,"measured_points",np.empty((0,3))),dtype=float).reshape(-1,3)
    source_points=bool(len(raw))
    if not source_points:raw=tin.points
    selected=[]
    for first in range(0,len(raw),50000):
        _check(cancelled);part=raw[first:first+50000]
        if bounds is not None:
            part=part[(part[:,0]>=bounds[0])&(part[:,1]>=bounds[1])&(part[:,0]<=bounds[2])&(part[:,1]<=bounds[3])]
        if len(part):selected.append(part)
    shown=np.concatenate(selected) if selected else np.empty((0,3))
    shown=shown[::max(1,math.ceil(len(shown)/max_points))]
    contours=[];all_contours=[]
    for index,curve in enumerate(getattr(tin,"source_contours",[])):
        if index%32==0:_check(cancelled)
        values=np.asarray(curve.get("points",[]) if isinstance(curve,dict) else curve,dtype=float).reshape(-1,3)
        all_contours.append(values)
        if len(values)>1 and (bounds is None or _intersects(values[None,:,:],bounds)[0]):contours.append(values)
    report=getattr(tin,"import_report",{}) or {};quality=getattr(tin,"quality_report",None) or report.get("quality_report",{})
    point_ids=getattr(tin,"point_source_identities",[]);curve_ids=getattr(tin,"contour_source_identities",[])
    lookup={str(v["source_handle"]):raw[i:i+1] for i,v in enumerate(point_ids) if source_points and i<len(raw) and v.get("source_handle") is not None}
    lookup.update({str(v["source_handle"]):all_contours[i] for i,v in enumerate(curve_ids) if i<len(all_contours) and v.get("source_handle") is not None})
    anomaly_points=[];anomaly_lines=[];unlocated=0
    for value in quality.get("removed_entities",[]):
        _check(cancelled);coords=lookup.get(str(value.get("source_handle")))
        if coords is None:unlocated+=1;continue
        if len(coords)>1:anomaly_lines.append(coords)
        else:anomaly_points.extend(coords[:,:2])
    for key in ("conflicts","duplicate_point_resolutions","conflict_resolutions"):
        for value in report.get(key,[]):
            if value.get("xy") is not None:anomaly_points.append(value["xy"])
    for key in ("explicit_constraint_releases","automatic_constraint_releases"):
        for value in report.get(key,[]):
            if value.get("original_xyz"):anomaly_lines.append(np.asarray(value["original_xyz"],dtype=float))
    for value in report.get("conflict_resolutions",[]):
        anomaly_lines.extend(np.asarray(v,dtype=float) for v in value.get("yielded_segments",[]))
    anomalies=np.asarray(anomaly_points,dtype=float).reshape(-1,2)
    if bounds is not None:
        anomalies=anomalies[(anomalies[:,0]>=bounds[0])&(anomalies[:,1]>=bounds[1])&(anomalies[:,0]<=bounds[2])&(anomalies[:,1]<=bounds[3])]
        anomaly_lines=[line for line in anomaly_lines if len(line)>1 and _intersects(line[None,:,:],bounds)[0]]
    return {"measured_points":shown,"source_contours":contours,"anomaly_points":anomalies,
            "anomaly_contours":anomaly_lines,"point_label":"测点" if source_points else "网格顶点",
            "unlocated_anomaly_count":unlocated,"original_display_point_count":len(raw),"shown_point_count":len(shown)}


def build_terrain_display(tin,*,interval=0.,bounds=None,include_contours=True,include_boundary=True,
                          cancelled=None,chunk_size=50000,max_levels=200,max_segments=250000,max_points=50000):
    """Return plan layers, preserving the original TIN and source elevations.

    bounds=(xmin,ymin,xmax,ymax) only selects original faces for display. Contour
    segments are exact face/level intersections, never matplotlib re-TINs.
    interval=0 picks a readable 1/2/5 interval; any explicit interval is retained.
    """
    _check(cancelled);interval=float(interval)
    if not math.isfinite(interval) or interval<0:raise ValueError("显示等高线间隔须为零（自动）或有限正数")
    if chunk_size<=0 or max_points<=0:raise ValueError("显示分块及点数上限必须大于零")
    if bounds is not None:
        bounds=tuple(map(float,bounds))
        if len(bounds)!=4 or not np.isfinite(bounds).all() or bounds[2]<=bounds[0] or bounds[3]<=bounds[1]:raise ValueError("显示范围无效")
    points=np.asarray(tin.points);faces=np.asarray(tin.triangles)
    selected=[];mesh_edges=[];minimum=np.full(3,np.inf);maximum=-minimum.copy()
    for first in range(0,len(faces),chunk_size):
        _check(cancelled);part=faces[first:first+chunk_size];xyz=points[part]
        if include_boundary:mesh_edges.append(_edges(part))
        mask=_intersects(xyz,bounds)
        if mask.any():
            local=xyz[mask];minimum=np.minimum(minimum,local.min(axis=(0,1)));maximum=np.maximum(maximum,local.max(axis=(0,1)))
            selected.append(part[mask])
    _check(cancelled);selected=np.concatenate(selected) if selected else np.empty((0,3),dtype=np.int64)
    layers=_source_layers(tin,bounds,cancelled,max_points)
    boundary=np.empty((0,2,3));contours=[];effective_interval=interval
    if include_boundary and mesh_edges:
        ids=_naked_edges(np.concatenate(mesh_edges),len(points),cancelled);boundary=points[ids]
        if bounds is not None:boundary=boundary[_intersects(boundary,bounds)]
    if include_contours and len(selected):
        effective_interval=interval or _nice_interval(float(maximum[2]-minimum[2]))
        for attempt in range(9):
            _check(cancelled)
            first=math.ceil(float(minimum[2])/effective_interval);last=math.floor(float(maximum[2])/effective_interval)
            if last-first+1>max_levels:raise ValueError("显示等高线级数过多，请增大间隔或缩小范围；计算地形保持原精度")
            levels=np.arange(first,last+1,dtype=float)*effective_interval
            try:contours=_contours(points,selected,levels,chunk_size,cancelled,max_segments);break
            except ValueError:
                if interval or attempt==8:raise
                # Automatic display spacing can get sparser; actual face and
                # source geometry are never changed or replaced with chords.
                effective_interval*=2.
    _check(cancelled)
    return {**layers,"generated_contours":contours,"boundary_segments":boundary,
            "bounds":list(bounds) if bounds is not None else ([float(minimum[0]),float(minimum[1]),float(maximum[0]),float(maximum[1])] if len(selected) else None),
            "metadata":{"schema_version":"1.0","method":"original_triangle_horizontal_intersection",
                        "source_point_count":len(points),"source_face_count":len(faces),"selected_face_count":len(selected),
                        "display_interval":effective_interval,"generated_segment_count":sum(len(c["segments"]) for c in contours),
                        "original_tin_unchanged":True,"uses_rhino":False}}
