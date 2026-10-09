"""模块 3：纯导航逻辑。

本文件不导入 ``rospy``、``geometry_msgs`` 或 ``mavros_msgs``。ROS 消息转换、
    ``PositionTarget`` 构造和 30 Hz 定时器均位于 ``navigator_node.py``。

仿真第一版约定雷达坐标系与飞控 local 坐标系重合，不在这里加入未经确认的
平移、旋转或真机外参变换。第一版航点只包含目标当前的位置 ``x/y/z``。
"""
from __future__ import annotations

import math
import warnings
from typing import Iterable, List, Optional, Sequence, Tuple

from config import NAVIGATOR_HOLD_TIMEOUT, ONBOARD
from datatypes import Track, Waypoint

__all__ = [
    "select_track",
    "waypoints_from_track",
    "send_waypoint",
    "hover_setpoint",
    "on_timer",
]


def _reject(message: str) -> bool:
    if ONBOARD:
        warnings.warn(
            "[navigator] %s；上机阶段按安全默认值处理" % message,
            RuntimeWarning,
            stacklevel=2,
        )
        return True
    raise ValueError("[navigator] " + message)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _valid_track(track: object) -> bool:
    return (
        isinstance(track, Track)
        and isinstance(track.id, int)
        and isinstance(track.age, int)
        and len(track.position) == 3
        and all(_is_number(value) and math.isfinite(float(value)) for value in track.position)
    )


def select_track(tracks: List[Track]) -> Optional[Track]:
    """选择当前导航目标：``age`` 最大；相同年龄取 ``id`` 最小。"""
    if not isinstance(tracks, list):
        if _reject("select_track: tracks 必须为 list，实际为 %r" % (tracks,)):
            return None
    valid = []
    for index, track in enumerate(tracks):
        if not _valid_track(track):
            if _reject("select_track: tracks[%d] 不是有效 Track" % index):
                continue
        valid.append(track)
    if not valid:
        return None
    return min(valid, key=lambda track: (-track.age, track.id))


def waypoints_from_track(track: Track) -> List[Waypoint]:
    """将雷达航迹转换为航点序列。

    第一版只生成当前目标位置航点；未来预测/历史航点待后续设计明确后增加。
    """
    if not _valid_track(track):
        if _reject("waypoints_from_track: track 不是有效 Track"):
            return []
    x, y, z = (float(value) for value in track.position)
    return [Waypoint(x=x, y=y, z=z)]


def _validate_waypoint(wp: Waypoint) -> Waypoint:
    """校验并返回航点，供纯算法内部复用。"""
    if not isinstance(wp, Waypoint):
        if _reject("waypoint 必须为 Waypoint，实际为 %r" % (wp,)):
            return Waypoint(0.0, 0.0, 0.0)
    if not all(_is_number(value) and math.isfinite(float(value)) for value in (wp.x, wp.y, wp.z)):
        if _reject("waypoint 坐标必须为有限数值"):
            return Waypoint(0.0, 0.0, 0.0)
    return wp


def send_waypoint(wp: Waypoint) -> None:
    """纯逻辑层的航点交接。

    ROS 发布由节点层完成；这里仅校验航点并结束，避免纯算法层依赖消息或
    publisher。节点将算法结果转换成 ``PositionTarget`` 后发布到 ``/ctrl/radar``。
    """
    _validate_waypoint(wp)


def _pose_xyz(current_pose: object) -> Optional[Waypoint]:
    """读取节点层传入的 ``(x, y, z)`` 或具有 ``x/y/z`` 的位置对象。"""
    if isinstance(current_pose, (tuple, list)) and len(current_pose) == 3:
        values = current_pose
    elif all(hasattr(current_pose, name) for name in ("x", "y", "z")):
        values = (current_pose.x, current_pose.y, current_pose.z)
    else:
        return None
    if not all(_is_number(value) and math.isfinite(float(value)) for value in values):
        return None
    return Waypoint(*(float(value) for value in values))


def hover_setpoint(current_pose: object) -> Waypoint:
    """根据当前位姿生成纯位置保持航点。"""
    waypoint = _pose_xyz(current_pose)
    if waypoint is None:
        if _reject("hover_setpoint: current_pose 必须提供有限 x/y/z"):
            return Waypoint(0.0, 0.0, 0.0)
    return waypoint


def on_timer(
    tracks: List[Track],
    valid_age: float,
    last_cmd: Optional[Waypoint],
    current_pose: object,
    hold_timeout: float = NAVIGATOR_HOLD_TIMEOUT,
) -> Waypoint:
    """时钟层三选一：新鲜航点、短时重发、长时当前位置保持。

    valid_age 是距上次非空输入的时间；断流后的非空缓存也会超时。
    """
    if not _is_number(valid_age):
        if _reject("on_timer: valid_age 必须为非负有限数值或 inf"):
            valid_age = float("inf")
    elif float(valid_age) < 0.0 or (
        not math.isfinite(float(valid_age)) and float(valid_age) != float("inf")
    ):
        if _reject("on_timer: valid_age 必须为非负有限数值或 inf"):
            valid_age = float("inf")
    if not _is_number(hold_timeout) or float(hold_timeout) < 0.0:
        if _reject("on_timer: hold_timeout 必须为非负数"):
            hold_timeout = NAVIGATOR_HOLD_TIMEOUT

    track = select_track(tracks)
    if track is not None and float(valid_age) <= float(hold_timeout):
        return _validate_waypoint(waypoints_from_track(track)[0])
    if float(valid_age) <= float(hold_timeout) and last_cmd is not None:
        return _validate_waypoint(last_cmd)
    return hover_setpoint(current_pose)
