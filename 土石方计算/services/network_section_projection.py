"""Local-coordinate analytic route projection for engineering section integration.

All objects here are 2D. Offset is positive to the right; CCW curvature k
therefore has Jacobian 1+k*u. Widths are caller-supplied conservative search
bounds, not new construction dimensions. No solid kernel is imported.
"""
from __future__ import annotations

import math
import numpy as np
from shapely.geometry import Point, box
from shapely.strtree import STRtree


def _cross(a,b):
    return float(a[0]*b[1]-a[1]*b[0])


class Catalog:
    def __init__(self, alignment, assets, origin_xy, asset_widths):
        self.alignment=alignment
        self.assets=list(assets)
        self.origin_xy=np.asarray(origin_xy,dtype=float)
        if self.origin_xy.shape!=(2,) or not np.isfinite(self.origin_xy).all():
            raise ValueError('Projection origin must be a finite XY pair')
        self.parts=[]
        for asset_index,asset in enumerate(self.assets):
            width=asset_widths[asset['asset_id']]
            if np.isscalar(width):
                u0,u1=-float(width),float(width)
            elif isinstance(width,dict):
                u0,u1=float(width['offset_min']),float(width['offset_max'])
            else:
                u0,u1=map(float,width)
            if not math.isfinite(u0+u1) or u0>u1:
                raise ValueError('Projection search widths must be ordered and finite')
            for primitive_id,e in enumerate(alignment.elements):
                # Internal ownership chainage concatenates separate physical
                # routes. A shared endpoint can differ by one floating-point
                # step; it must never allocate an asset to another route's
                # line/arc at a distant XY. Spatial overlap queries below
                # still compare real parts across all routes.
                if (asset.get('route_id') is not None and e.get('route_id') is not None
                        and asset['route_id']!=e['route_id']):
                    continue
                if e['kind']=='line' and np.array_equal(e['start_xy'],e['end_xy']):
                    # Adjacent exact fillets can leave a positive chainage
                    # residue whose two world-coordinate endpoints round to
                    # the same XY. It has no physical line or normal; omit
                    # only a residue below the coordinate representation.
                    tolerance=max(1e-9,*(8*math.ulp(max(abs(float(x)),1.))
                                           for x in e['start_xy']))
                    if float(e['length'])>tolerance:
                        raise ValueError('直线线元的起终点相同，但桩号长度超过坐标精度，请检查线路')
                    continue
                a=max(float(asset['station_start']),float(e['station_start']))
                b=min(float(asset['station_end']),float(e['station_end']))
                if b<=a:
                    continue
                self.parts.append({'part_id':len(self.parts),'primitive_id':primitive_id,
                    'asset_id':asset['asset_id'],'asset_index':asset_index,'station_start':a,
                    'station_end':b,'kind':e['kind'],'offset_min':u0,'offset_max':u1})
        self._parts_by_asset={}
        self._assets_by_id={asset['asset_id']:asset for asset in self.assets}
        for part in self.parts:
            self._parts_by_asset.setdefault(part['asset_id'],[]).append(part)
        self._boxes=[self._part_box(p) for p in self.parts]
        self._tree=STRtree(self._boxes)

    def endpoint_station(self,asset_id,station):
        """Canonicalize only real asset ends, including omitted zero-XY residues."""
        parts=self._parts_by_asset.get(asset_id,[])
        if not parts:return station
        asset=self._assets_by_id[asset_id]
        start=min(part['station_start'] for part in parts)
        end=max(part['station_end'] for part in parts)
        if (start-1e-7<=station<start
                and abs(float(asset['station_start'])-start)<=1e-7):
            return start
        if (end<station<=end+1e-7
                and abs(float(asset['station_end'])-end)<=1e-7):
            return end
        return station

    def center_tangent_curvature(self,part_id,station):
        part=self.parts[int(part_id)]
        station=self.endpoint_station(part['asset_id'],float(station))
        if not part['station_start']<=station<=part['station_end']:
            raise ValueError(f"Station is outside the asset route: asset={part['asset_id']}, "
                f"station={station:.12f}, part_start={part['station_start']:.12f}, "
                f"part_end={part['station_end']:.12f}")
        e=self.alignment.elements[part['primitive_id']]
        t=(float(station)-e['station_start'])/e['length']
        if e['kind']=='line':
            a=np.asarray(e['start_xy'],float)-self.origin_xy
            c=a+(np.asarray(e['end_xy'],float)-e['start_xy'])*t
            angle=e['tangent_angle'];k=0.
        else:
            angle=e['start_angle']+e['sweep_angle']*t
            c=np.asarray(e['center_xy'],float)-self.origin_xy+e['radius']*np.asarray([math.cos(angle),math.sin(angle)])
            angle+=math.copysign(math.pi/2,e['sweep_angle'])
            k=math.copysign(1/e['radius'],e['sweep_angle'])
        return c,np.asarray([math.cos(angle),math.sin(angle)]),k

    def _part_box(self,part):
        e=self.alignment.elements[part['primitive_id']]
        lo,hi=part['offset_min'],part['offset_max']
        points=[]
        if e['kind']=='line':
            for station in (part['station_start'],part['station_end']):
                c,t,_=self.center_tangent_curvature(part['part_id'],station)
                n=np.asarray([t[1],-t[0]])
                points.extend((c+lo*n,c+hi*n))
        else:
            angles=[e['start_angle']+e['sweep_angle']*(s-e['station_start'])/e['length']
                    for s in (part['station_start'],part['station_end'])]
            a,b=sorted(angles)
            angles.extend(i*math.pi/2 for i in range(math.ceil(a/(math.pi/2)),math.floor(b/(math.pi/2))+1))
            center=np.asarray(e['center_xy'],float)-self.origin_xy
            sign=math.copysign(1.,e['sweep_angle'])
            for rho in (e['radius']+sign*lo,e['radius']+sign*hi):
                points.extend(center+rho*np.asarray([math.cos(theta),math.sin(theta)]) for theta in angles)
        points=np.asarray(points)
        # Only the query envelope expands by a few local-coordinate ULPs.
        # Physical section/offset intervals remain unchanged.
        pad=max(1e-9,float(np.max(np.abs(points)))*np.finfo(float).eps*64)
        bounds=np.r_[points.min(axis=0)-pad,points.max(axis=0)+pad]
        return box(*bounds)

    def query(self,normal_line_local):
        return sorted(map(int,self._tree.query(normal_line_local)))

    def part_at(self,asset_id,station,side='right'):
        if side not in ('left','right'):
            raise ValueError('side must be left or right')
        station=self.endpoint_station(asset_id,float(station))
        parts=self._parts_by_asset.get(asset_id,[])
        inside=[p for p in parts if (p['station_start']<=station<p['station_end'] if side=='right'
                                     else p['station_start']<station<=p['station_end'])]
        if inside:
            return inside[0]['part_id']
        boundary=[p for p in parts if p['station_start']<=station<=p['station_end']]
        if boundary:
            return (boundary[-1] if side=='left' else boundary[0])['part_id']
        raise ValueError(f"Station is outside the asset route: asset={asset_id}, station={station:.12f}")

    def preimages(self,X_local,candidate_ids=None):
        X=np.asarray(X_local,float)
        ids=self.query(Point(X)) if candidate_ids is None else candidate_ids
        found=[]
        for part_id in ids:
            p=self.parts[int(part_id)];e=self.alignment.elements[p['primitive_id']]
            values=[]
            if e['kind']=='line':
                a=np.asarray(e['start_xy'],float)-self.origin_xy
                v=(np.asarray(e['end_xy'],float)-e['start_xy'])/e['length']
                t=np.asarray([math.cos(e['tangent_angle']),math.sin(e['tangent_angle'])])
                n=np.asarray([t[1],-t[0]]);det=_cross(v,n)
                ds=_cross(X-a,n)/det;u=_cross(v,X-a)/det
                values.append((e['station_start']+ds,u,1,False))
            else:
                delta=X-(np.asarray(e['center_xy'],float)-self.origin_xy)
                radius=float(np.linalg.norm(delta));sign=math.copysign(1.,e['sweep_angle'])
                if radius==0.:
                    # A center has a continuum of angular preimages. Its plan
                    # measure is zero: callers split quadrature at this event
                    # and use one-sided values, not this finite representative.
                    values.append(((p['station_start']+p['station_end'])/2,-sign*e['radius'],0,True))
                else:
                    alpha=math.atan2(delta[1],delta[0])
                    for branch,theta in ((1,alpha),(-1,alpha+math.pi)):
                        start=e['start_angle'];sweep=e['sweep_angle']
                        lo,hi=sorted((start,start+sweep))
                        for turn in range(math.floor((lo-theta)/(2*math.pi))-1,math.ceil((hi-theta)/(2*math.pi))+2):
                            angle=theta+turn*2*math.pi
                            ratio=(angle-start)/sweep
                            if -1e-12<=ratio<=1+1e-12:
                                values.append((e['station_start']+ratio*e['length'],sign*(branch*radius-e['radius']),branch,False))
            for station,offset,branch,singular in values:
                tol=max(1e-9,math.ulp(max(abs(station),1.))*8)
                if not p['station_start']-tol<=station<=p['station_end']+tol:
                    continue
                if not p['offset_min']-1e-8<=offset<=p['offset_max']+1e-8:
                    continue
                found.append({'part_id':p['part_id'],'primitive_id':p['primitive_id'],'asset_id':p['asset_id'],
                    'asset_index':p['asset_index'],'station':min(max(station,p['station_start']),p['station_end']),
                    'offset':float(offset),'branch':branch,'singular':singular})
        return sorted(found,key=lambda r:(r['station'],r['asset_index'],r['part_id'],r['branch']))

    def normal_events(self,C,N,uL,uR,candidates,station_knots=()):
        C,N=np.asarray(C,float),np.asarray(N,float)
        events={float(uL),float(uR)}
        def add(u):
            if math.isfinite(u) and uL<u<uR:
                events.add(float(u))
        for part_id in candidates:
            p=self.parts[int(part_id)];e=self.alignment.elements[p['primitive_id']]
            knots=station_knots.get(p['asset_id'],()) if isinstance(station_knots,dict) else station_knots
            knots=[float(k['station'] if isinstance(k,dict) else k) for k in knots]
            for station in [p['station_start'],p['station_end']]+[s for s in knots if p['station_start']<s<p['station_end']]:
                center,t,_=self.center_tangent_curvature(p['part_id'],station)
                normal=np.asarray([t[1],-t[0]])
                denominator=_cross(N,normal)
                if abs(denominator)>1e-14:
                    add(_cross(center-C,normal)/denominator)
            if e['kind']=='line':
                a=np.asarray(e['start_xy'],float)-self.origin_xy
                v=(np.asarray(e['end_xy'],float)-e['start_xy'])/e['length']
                t=np.asarray([math.cos(e['tangent_angle']),math.sin(e['tangent_angle'])])
                normal=np.asarray([t[1],-t[0]]);det=_cross(v,normal)
                rate=_cross(v,N)/det;value=_cross(v,C-a)/det
                if abs(rate)>1e-14:
                    for u in (p['offset_min'],p['offset_max']):add((u-value)/rate)
            else:
                delta=C-(np.asarray(e['center_xy'],float)-self.origin_xy)
                aa=float(N@N);bb=2*float(delta@N)
                add(-bb/(2*aa))
                sign=math.copysign(1.,e['sweep_angle'])
                for offset in (p['offset_min'],p['offset_max']):
                    radius=abs(e['radius']+sign*offset)
                    cc=float(delta@delta)-radius*radius
                    disc=bb*bb-4*aa*cc
                    if disc>=0:
                        root=math.sqrt(disc)
                        add((-bb-root)/(2*aa));add((-bb+root)/(2*aa))
        return sorted(events)
