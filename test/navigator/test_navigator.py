"""模块 3 纯导航算法测试（不依赖 ROS master）。"""

import numpy as np
import pytest

import navigator
from datatypes import Track, Waypoint


def _track(track_id, age, position):
    return Track(
        id=track_id,
        position=tuple(position),
        velocity=(0.0, 0.0, 0.0),
        covariance=tuple(np.eye(6).reshape(-1)),
        age=age,
    )


def test_waypoints_from_track_uses_current_position_only():
    out = navigator.waypoints_from_track(_track(3, 2, (1.0, -2.0, 4.5)))
    assert out == [Waypoint(1.0, -2.0, 4.5)]


def test_select_track_prefers_largest_age():
    tracks = [_track(1, 4, (1, 0, 0)), _track(2, 7, (2, 0, 0))]
    assert navigator.select_track(tracks).id == 2


def test_select_track_tie_prefers_smallest_id():
    tracks = [_track(8, 7, (8, 0, 0)), _track(3, 7, (3, 0, 0))]
    assert navigator.select_track(tracks).id == 3


def test_on_timer_with_tracks_generates_selected_target_position():
    tracks = [_track(8, 2, (8, 0, 0)), _track(3, 4, (3, 2, 1))]
    out = navigator.on_timer(tracks, valid_age=0.0, last_cmd=None, current_pose=(0, 0, 0))
    assert out == Waypoint(3.0, 2.0, 1.0)


def test_on_timer_short_loss_repeats_last_position_command():
    last = Waypoint(5.0, 6.0, 7.0)
    out = navigator.on_timer([], valid_age=0.5, last_cmd=last, current_pose=(0, 0, 0), hold_timeout=0.5)
    assert out == last


def test_on_timer_long_loss_holds_current_pose():
    out = navigator.on_timer([], valid_age=0.51, last_cmd=Waypoint(9, 9, 9), current_pose=(1, 2, 3), hold_timeout=0.5)
    assert out == Waypoint(1.0, 2.0, 3.0)


@pytest.mark.parametrize("valid_age", [0.51, float("inf")])
def test_nonempty_stale_tracks_hold_current_pose(valid_age):
    tracks = [_track(1, 5, (9, 8, 7))]
    out = navigator.on_timer(tracks, valid_age, Waypoint(9, 8, 7),
                             (1, 2, 3), hold_timeout=0.5)
    assert out == Waypoint(1, 2, 3)


def test_empty_tracks_with_infinite_age_holds_current_pose():
    assert navigator.on_timer([], float("inf"), None, (4, 5, 6)) == Waypoint(4, 5, 6)


def test_invalid_track_rejected_in_dev():
    with pytest.raises(ValueError):
        navigator.waypoints_from_track(object())
