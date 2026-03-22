# -*- coding: utf-8 -*-
"""Shared helpers for Matplotlib section-plot titles."""


def format_flow_velocity_metrics(Q, V):
    return rf"Q={Q:.2f} $\mathregular{{m^{{3}}/s}}$, V={V:.2f} $\mathregular{{m/s}}$"


def apply_flow_velocity_title(ax, title, Q, V, *, fontsize=10):
    ax.set_title(f"{title}\n{format_flow_velocity_metrics(Q, V)}", fontsize=fontsize)
