# -*- coding: utf-8 -*-
"""最小方法协议（R3-NFA 冻结）。

MethodContext：方法运行上下文（Scenario + DerivedState + 配置 + seed + 预算）。
MethodProposal：方法返回（决策 X/A/F + 状态 + 诊断 + runtime）。
MethodProtocol：方法实现必须满足的接口（typing.Protocol）。

所有权边界（提示词 §3.1）：
- Method 只生成 X/A/F 和方法诊断；
- Runner 是统一 Evaluator 的唯一调用者（本包不 import evaluator.evaluate）；
- Scenario 输入不可修改；
- method seed 与 scenario seed 分离。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, runtime_checkable

from cars.simulator.derived_state import DerivedState


@dataclass
class MethodContext:
    """方法运行上下文。

    scenario：T0 Scenario dict（只读，方法不得修改）。
    derived：T0 DerivedState（只读）。
    config：方法参数 dict（已校验）。
    method_seed：方法独立 seed（与 scenario seed 分离）。
    soft_deadline_seconds：内部软截止期（触发 -> 标准 TIMEOUT）。
    hard_timeout_seconds：硬截止期（信息性；强制终止由 Runner 负责）。
    start_monotonic：monotonic 时钟起点（deadline 检查用）。
    """

    scenario: Dict
    derived: DerivedState
    config: Dict
    method_seed: int
    soft_deadline_seconds: float
    hard_timeout_seconds: float
    start_monotonic: float = field(default_factory=time.monotonic)

    def remaining_soft(self) -> float:
        """距软截止期的剩余时间（秒）；<=0 表示已触发。"""
        return self.soft_deadline_seconds - (time.monotonic() - self.start_monotonic)


@dataclass
class MethodProposal:
    """方法返回（决策 + 状态 + 诊断）。

    decision：Pi = {X,A,F} dict；TIMEOUT/METHOD_ERROR 时为 None
              （Contract Part 9.4：超时/异常不返回可成功计分的决策）。
    method_status：Schema common.method_status 枚举。
    timed_out：是否超时。
    runtime_seconds：方法本体运行时间（不含统一 Evaluator 时间）。
    diagnostics：方法诊断（可定位字段）。
    """

    decision: Optional[Dict]
    method_status: str
    timed_out: bool
    runtime_seconds: float
    diagnostics: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "decision": self.decision,
            "method_status": self.method_status,
            "timed_out": self.timed_out,
            "runtime_seconds": self.runtime_seconds,
            "diagnostics": self.diagnostics,
        }


@runtime_checkable
class MethodProtocol(Protocol):
    """方法接口。method_id 为注册名；run(ctx) 返回 MethodProposal。"""

    method_id: str

    def run(self, ctx: MethodContext) -> MethodProposal:  # pragma: no cover - Protocol
        ...
