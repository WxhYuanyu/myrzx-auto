"""每日委托的阶段。类型1、类型2共用这一套，具体走哪几步由配方决定。"""

from __future__ import annotations

from enum import Enum


class Phase(str, Enum):
    ACCEPT = "ACCEPT"
    GO_STAGE = "GO_STAGE"
    IN_BATTLE = "IN_BATTLE"
    CLAIM = "CLAIM"
    DONE = "DONE"
