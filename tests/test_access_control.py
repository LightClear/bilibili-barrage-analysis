from datetime import datetime, timedelta, timezone

from src.access_control import ActivationRule, UserLevel, can_activate, can_query


BEIJING = timezone(timedelta(hours=8))


def test_admin_can_query_without_interval_limit():
    assert can_query(UserLevel.ADMIN, now_seconds=5, last_query_seconds=4).allowed


def test_owner_can_query_without_interval_limit():
    assert can_query(UserLevel.OWNER, now_seconds=5, last_query_seconds=4).allowed


def test_normal_user_first_query_is_allowed():
    result = can_query(UserLevel.NORMAL, now_seconds=100, last_query_seconds=None)

    assert result.allowed
    assert result.wait_seconds == 0


def test_normal_user_must_wait_ten_seconds_between_queries():
    result = can_query(UserLevel.NORMAL, now_seconds=105, last_query_seconds=100)

    assert not result.allowed
    assert result.wait_seconds == 5


def test_normal_user_can_query_after_ten_seconds():
    assert can_query(UserLevel.NORMAL, now_seconds=110, last_query_seconds=100).allowed


def test_can_activate_allows_first_activation():
    rule = ActivationRule(rule_id="danmaku_search", interval_seconds=10)
    now = datetime(2026, 5, 27, 12, 0, 0, tzinfo=BEIJING)

    result = can_activate(rule, current_time=now, user_level=UserLevel.NORMAL)

    assert result.allowed
    assert result.wait_seconds == 0
    assert result.reason == "allowed"


def test_can_activate_blocks_inactive_rule():
    rule = ActivationRule(rule_id="hot_video_refresh", interval_seconds=300, active=False)
    now = datetime(2026, 5, 27, 12, 0, 0, tzinfo=BEIJING)

    result = can_activate(rule, current_time=now, user_level=UserLevel.NORMAL)

    assert not result.allowed
    assert result.reason == "inactive"


def test_can_activate_uses_beijing_time_interval():
    last = datetime(2026, 5, 27, 12, 0, 0, tzinfo=BEIJING)
    now = datetime(2026, 5, 27, 12, 0, 5, tzinfo=BEIJING)
    rule = ActivationRule(
        rule_id="danmaku_search",
        interval_seconds=10,
        last_activated_at=last,
    )

    result = can_activate(rule, current_time=now, user_level=UserLevel.NORMAL)

    assert not result.allowed
    assert result.wait_seconds == 5
    assert result.next_allowed_at == datetime(2026, 5, 27, 12, 0, 10, tzinfo=BEIJING)


def test_can_activate_allows_after_interval():
    last = datetime(2026, 5, 27, 12, 0, 0, tzinfo=BEIJING)
    now = datetime(2026, 5, 27, 12, 5, 0, tzinfo=BEIJING)
    rule = ActivationRule(
        rule_id="hot_video_refresh",
        interval_seconds=300,
        last_activated_at=last,
    )

    assert can_activate(rule, current_time=now, user_level=UserLevel.NORMAL).allowed


def test_admin_can_bypass_interval_when_rule_allows_it():
    last = datetime(2026, 5, 27, 12, 0, 0, tzinfo=BEIJING)
    now = datetime(2026, 5, 27, 12, 0, 1, tzinfo=BEIJING)
    rule = ActivationRule(
        rule_id="ai_analysis",
        interval_seconds=60,
        last_activated_at=last,
        admin_bypass=True,
    )

    result = can_activate(rule, current_time=now, user_level=UserLevel.ADMIN)

    assert result.allowed
    assert result.reason == "admin_bypass"


def test_owner_can_bypass_interval_when_rule_allows_it():
    last = datetime(2026, 5, 27, 12, 0, 0, tzinfo=BEIJING)
    now = datetime(2026, 5, 27, 12, 0, 1, tzinfo=BEIJING)
    rule = ActivationRule(
        rule_id="ai_analysis",
        interval_seconds=60,
        last_activated_at=last,
        admin_bypass=True,
    )

    result = can_activate(rule, current_time=now, user_level=UserLevel.OWNER)

    assert result.allowed
    assert result.reason == "admin_bypass"


def test_owner_does_not_bypass_when_rule_disables_bypass():
    last = datetime(2026, 5, 27, 12, 0, 0, tzinfo=BEIJING)
    now = datetime(2026, 5, 27, 12, 0, 1, tzinfo=BEIJING)
    rule = ActivationRule(
        rule_id="hot_video_refresh",
        interval_seconds=300,
        last_activated_at=last,
        admin_bypass=False,
    )

    result = can_activate(rule, current_time=now, user_level=UserLevel.OWNER)

    assert not result.allowed
    assert result.wait_seconds == 299


def test_admin_does_not_bypass_when_rule_disables_bypass():
    last = datetime(2026, 5, 27, 12, 0, 0, tzinfo=BEIJING)
    now = datetime(2026, 5, 27, 12, 0, 1, tzinfo=BEIJING)
    rule = ActivationRule(
        rule_id="hot_video_refresh",
        interval_seconds=300,
        last_activated_at=last,
        admin_bypass=False,
    )

    result = can_activate(rule, current_time=now, user_level=UserLevel.ADMIN)

    assert not result.allowed
    assert result.wait_seconds == 299
