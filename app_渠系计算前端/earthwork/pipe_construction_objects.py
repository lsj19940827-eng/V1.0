"""Pipe construction objects and longitudinal source scopes in the workbench."""
from 土石方计算.services.pipe_construction_objects import construction_objects, pipe_objects_by_scope

from .pipe_profile_mapping import profile_key


def profile_source_groups(inputs):
    return {profile_key(*members[0]): tuple(members) for members in pipe_objects_by_scope(inputs).values()}


def source_scope_asset(members):
    """Return the chainage extent used for the scope label."""
    first = members[0][1]
    starts = [asset["station_start"] for _, asset in members if asset.get("station_start") is not None]
    ends = [asset["station_end"] for _, asset in members if asset.get("station_end") is not None]
    return {**first, "station_start": min(starts, default=None), "station_end": max(ends, default=None)}


def source_scope_key(groups, member_key):
    return next((key for key, members in groups.items()
                 if any(profile_key(*member) == member_key for member in members)), None)
