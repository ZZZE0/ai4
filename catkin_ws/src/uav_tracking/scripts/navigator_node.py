#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``/navigator`` 节点：``TrackArray`` -> ``/ctrl/radar``。

本节点只生成中间雷达导航指令，不连接最终飞控 setpoint 话题，不调用解锁、
模式切换或 command 服务。最终出口仍由现有 ``/control_mux`` 负责。
"""
from __future__ import annotations

import os
import sys

import rospy
from geometry_msgs.msg import PoseStamped
from mavros_msgs.msg import PositionTarget
from uav_tracking.msg import TrackArray

_LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

from config import NAVIGATOR_HOLD_TIMEOUT, NAVIGATOR_RATE_HZ  # noqa: E402
from datatypes import Track, Waypoint  # noqa: E402
from navigator import (  # noqa: E402
    hover_setpoint as pure_hover_setpoint,
    on_timer as pure_on_timer,
)

__all__ = [
    "TOPIC_TRACKS",
    "TOPIC_POSE",
    "TOPIC_OUTPUT",
    "POSITION_ONLY_TYPE_MASK",
    "tracks_from_msg",
    "pose_from_msg",
    "waypoint_to_position_target",
    "hover_setpoint",
    "NavigatorNode",
]

TOPIC_TRACKS = "/radar/tracks"
TOPIC_POSE = "/mavros/local_position/pose"
TOPIC_OUTPUT = "/ctrl/radar"
QUEUE_SIZE = 1
POSITION_ONLY_TYPE_MASK = (
    PositionTarget.IGNORE_VX
    | PositionTarget.IGNORE_VY
    | PositionTarget.IGNORE_VZ
    | PositionTarget.IGNORE_AFX
    | PositionTarget.IGNORE_AFY
    | PositionTarget.IGNORE_AFZ
    | PositionTarget.IGNORE_YAW
    | PositionTarget.IGNORE_YAW_RATE
)


def tracks_from_msg(msg):
    """``TrackArray`` -> ``list[datatypes.Track]``。"""
    return [
        Track(
            id=int(item.id),
            position=tuple(float(value) for value in item.position),
            velocity=tuple(float(value) for value in item.velocity),
            covariance=tuple(float(value) for value in item.covariance),
            age=int(item.age),
        )
        for item in msg.tracks
    ]


def pose_from_msg(msg):
    """``PoseStamped`` -> 纯算法使用的 ``(x, y, z)``。"""
    position = msg.pose.position
    return (float(position.x), float(position.y), float(position.z))


def waypoint_to_position_target(wp: Waypoint) -> PositionTarget:
    """将纯位置航点转换为标准位置型 ``PositionTarget``。

    仿真坐标系重合，不做外参变换；MAVROS setpoint_raw 使用标准 local NED
    frame 常量。只启用 position，屏蔽 velocity、acceleration、yaw 和 yaw_rate。
    """
    msg = PositionTarget()
    msg.coordinate_frame = PositionTarget.FRAME_LOCAL_NED
    msg.type_mask = POSITION_ONLY_TYPE_MASK
    msg.position.x = float(wp.x)
    msg.position.y = float(wp.y)
    msg.position.z = float(wp.z)
    return msg


def hover_setpoint(current_pose):
    """节点层悬停适配：纯位置保持航点 -> ``PositionTarget``。"""
    return waypoint_to_position_target(pure_hover_setpoint(current_pose))


class NavigatorNode:
    """事件层缓存 + 30 Hz 时钟层。"""

    def __init__(self):
        self.rate_hz = float(rospy.get_param("~rate_hz", NAVIGATOR_RATE_HZ))
        self.hold_timeout = float(
            rospy.get_param("~hold_timeout", NAVIGATOR_HOLD_TIMEOUT)
        )
        if self.rate_hz <= 0.0:
            raise ValueError("~rate_hz 必须 > 0")
        if self.hold_timeout < 0.0:
            raise ValueError("~hold_timeout 必须 >= 0")

        self._tracks = []
        self._last_valid_time = None
        self._current_pose = None
        self._last_waypoint = None

        self.pub = rospy.Publisher(TOPIC_OUTPUT, PositionTarget, queue_size=QUEUE_SIZE)
        rospy.Subscriber(TOPIC_TRACKS, TrackArray, self.on_tracks, queue_size=QUEUE_SIZE)
        rospy.Subscriber(TOPIC_POSE, PoseStamped, self.on_pose, queue_size=QUEUE_SIZE)
        self.timer = rospy.Timer(rospy.Duration(1.0 / self.rate_hz), self.on_timer)
        rospy.loginfo(
            "[navigator] ready: rate=%.1fHz hold_timeout=%.3fs output=%s",
            self.rate_hz,
            self.hold_timeout,
            TOPIC_OUTPUT,
        )

    def on_tracks(self, msg):
        """事件层：空数组不刷新 ``valid_age``。"""
        tracks = tracks_from_msg(msg)
        self._tracks = tracks
        if tracks:
            self._last_valid_time = rospy.Time.now()

    def on_pose(self, msg):
        self._current_pose = pose_from_msg(msg)

    def on_timer(self, _event):
        """30Hz 时钟层：生成并发布唯一的中间雷达指令。"""
        if self._current_pose is None:
            # 没有当前位置时不能构造可靠的长时悬停点；不发布伪造位置。
            return
        if self._last_valid_time is None:
            valid_age = float("inf")
        else:
            valid_age = max(0.0, (rospy.Time.now() - self._last_valid_time).to_sec())

        waypoint = pure_on_timer(
            self._tracks,
            valid_age,
            self._last_waypoint,
            self._current_pose,
            self.hold_timeout,
        )
        self._last_waypoint = waypoint
        self.pub.publish(waypoint_to_position_target(waypoint))


def main():
    rospy.init_node("navigator")
    NavigatorNode()
    rospy.spin()


if __name__ == "__main__":
    main()
