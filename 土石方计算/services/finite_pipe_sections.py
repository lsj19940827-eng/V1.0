"""Exact radial vertical cuts of normal circular disks along a constant helix."""
from functools import lru_cache
import math
from .contracts import ConstructionInputError


class UnsupportedPipeGeometry(ConstructionInputError):
    def __init__(self,message,*,code="unsupported_coupled_pipe_curve",diagnostics=None):
        super().__init__(message)
        self.code=code;self.diagnostics=diagnostics or []


@lru_cache(maxsize=1024)
def helix_height(radius,axis_radius,grade):
    """Return true positive vertical extent and its normal-disk angle."""
    radius,axis_radius,grade=map(float,(radius,axis_radius,grade))
    if not all(math.isfinite(v) for v in (radius,axis_radius,grade)) or not 0<radius<axis_radius:
        raise UnsupportedPipeGeometry("水平弯管外径跨越曲率中心，算法不支持该自交管面",code="unsupported_pipe_curvature_radius")
    if grade==0:return radius,math.pi/2
    g2=grade*grade
    def derivative(c):
        return c*(axis_radius**2+2*axis_radius*radius*c+radius**2*(g2+c*c)/(1+g2))+g2*axis_radius*(axis_radius*c+radius)
    lo,hi=-1.,0.
    for _ in range(64):
        middle=(lo+hi)/2
        if middle==lo or middle==hi:break
        if derivative(middle)>0:hi=middle
        else:lo=middle
    beta=math.acos((lo+hi)/2)
    factor=math.hypot(1.,grade);sine=math.sin(beta)
    delta=math.atan2(-radius*sine*grade/factor,axis_radius+radius*math.cos(beta))
    return -(grade*axis_radius*delta-radius*sine/factor),beta


def pipe_height(radius,offset,plan_curvature,main_grade):
    """Vertical span for a local line profile, with main-route station metric."""
    if plan_curvature==0 or main_grade==0:return radius*math.hypot(1.,main_grade)
    metric=1+plan_curvature*offset
    if metric<=0:
        raise UnsupportedPipeGeometry("管轴跨越水平曲率中心，算法不支持该管面",code="unsupported_pipe_curvature_radius")
    return helix_height(radius,abs(1/plan_curvature+offset),main_grade/metric)[0]


def pipe_top_envelope(radius,offset,plan_curvature,main_grade):
    """Return real vertical half-height and the radial cut's actual top XY offset."""
    if plan_curvature==0 or main_grade==0:return radius*math.hypot(1.,main_grade),offset
    metric=1+plan_curvature*offset
    if metric<=0:raise UnsupportedPipeGeometry("管轴跨越水平曲率中心",code="unsupported_pipe_curvature_radius")
    r=abs(1/plan_curvature+offset);grade=main_grade/metric
    height,beta=helix_height(radius,r,grade)
    rho=math.hypot(r+radius*math.cos(beta),radius*math.sin(beta)*grade/math.hypot(1.,grade))
    return height,offset+math.copysign(1.,plan_curvature)*(rho-r)


def helix_outline(radius,offset,plan_curvature,main_grade,count):
    metric=1+plan_curvature*offset
    if metric<=0:raise UnsupportedPipeGeometry("管轴跨越水平曲率中心",code="unsupported_pipe_curvature_radius")
    axis_radius=abs(1/plan_curvature+offset);grade=main_grade/metric
    height,beta=helix_height(radius,axis_radius,grade)
    factor=math.hypot(1.,grade);sign=math.copysign(1.,plan_curvature)
    angles=sorted({2*math.pi*i/count for i in range(count)}|{0.,math.pi,beta,2*math.pi-beta})
    points=[]
    bottom_offset=None
    for angle in angles:
        cosine,sine=math.cos(angle),math.sin(angle)
        delta=math.atan2(-radius*sine*grade/factor,axis_radius+radius*cosine)
        rho=math.hypot(axis_radius+radius*cosine,radius*sine*grade/factor)
        x=offset+sign*(rho-axis_radius)
        z=grade*axis_radius*delta-radius*sine/factor
        points.append((x,z))
        if angle==beta:bottom_offset=x
    return points,height,bottom_offset
