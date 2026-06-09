"""账号级别与功能激活频率控制。

模块用统一的“激活规则”描述查询、热门刷新、AI 分析等功能的触发限制。
后续接入真实账号系统时，可以把这里的 UserLevel 替换成数据库中的用户角色。

当前模块存在功能：
1. 查询权限判断
2. 功能模块激活频率控制
3. 管理员 bypass
4. 下次允许运行时间计算
5. 等待时间计算
6. 激活决策返回
7. 查询权限返回
8. 北京时间转换
9. 激活规则创建 --5.27
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from src.time_utils import BEIJING_TZ, now_beijing


class UserLevel(str, Enum):
    """当前支持的简易用户级别。"""

    NORMAL = "normal"
    ADMIN = "admin"
    OWNER = "owner"


@dataclass(frozen=True)
class ActivationRule:
    """描述某个功能模块的激活规则。"""

    rule_id: str #所属模块部分
    interval_seconds: int #间隔时间
    active: bool = True #是否激活
    last_activated_at: datetime | None = None #上次运行时间
    admin_bypass: bool = True #管理员 bypass


@dataclass(frozen=True)
class ActivationDecision:
    """功能模块是否允许激活的判断结果。"""

    allowed: bool #是否允许激活
    wait_seconds: int = 0 #等待时间
    reason: str = "allowed"
    next_allowed_at: datetime | None = None #下次允许运行时间


@dataclass(frozen=True)
class QueryPermission:
    """查询权限判断结果。"""

    allowed: bool
    wait_seconds: int = 0


def can_activate(
    rule: ActivationRule,
    current_time: datetime | None = None,
    user_level: UserLevel = UserLevel.NORMAL,
) -> ActivationDecision:
    """判断某个功能规则当前是否允许激活。

    该函数只做判断，不修改 `last_activated_at`。调用方在真正激活成功后负责记录时间。
    """

    current = _as_beijing_time(current_time or now_beijing())
    if not rule.active: #如果规则不激活，则不允许激活
        return ActivationDecision(allowed=False, reason="inactive")

    if user_level in {UserLevel.ADMIN, UserLevel.OWNER} and rule.admin_bypass: #如果用户级别为管理员或 owner，并且规则允许管理员 bypass，则允许激活
        return ActivationDecision(allowed=True, reason="admin_bypass")

    if rule.last_activated_at is None: #如果上次运行时间为空，则允许激活
        return ActivationDecision(allowed=True)

    last_activated = _as_beijing_time(rule.last_activated_at) #将上次运行时间转换为北京时间
    next_allowed_at = last_activated + timedelta(seconds=rule.interval_seconds) #计算下次允许运行时间
    if current >= next_allowed_at: #如果当前时间大于下次允许运行时间，则允许激活
        return ActivationDecision(allowed=True)

    wait_seconds = max(1, int((next_allowed_at - current).total_seconds())) #计算等待时间
    return ActivationDecision(
        allowed=False,
        wait_seconds=wait_seconds,
        reason="interval_not_reached",
        next_allowed_at=next_allowed_at,
    ) #返回激活决策


def can_query(
    user_level: UserLevel,
    now_seconds: float,
    last_query_seconds: float | None,
    interval_seconds: int = 10,
) -> QueryPermission:
    """判断当前用户是否允许发起查询。

    管理员不受频率限制；普通用户需要两次查询间隔至少 `interval_seconds` 秒。
    """

    last_activated_at = (
        datetime.fromtimestamp(last_query_seconds, tz=BEIJING_TZ)
        if last_query_seconds is not None
        else None
    ) #将上次查询时间转换为北京时间
    rule = ActivationRule(
        rule_id="danmaku_search",
        interval_seconds=interval_seconds,
        last_activated_at=last_activated_at,
    ) #创建规则
    decision = can_activate(
        rule,
        current_time=datetime.fromtimestamp(now_seconds, tz=BEIJING_TZ),
        user_level=user_level,
    ) #判断是否允许激活
    return QueryPermission(allowed=decision.allowed, wait_seconds=decision.wait_seconds) #返回查询权限


def _as_beijing_time(value: datetime) -> datetime:
    """将 datetime 统一转换为北京时间。"""

    if value.tzinfo is None:
        return value.replace(tzinfo=BEIJING_TZ)
    return value.astimezone(BEIJING_TZ)
