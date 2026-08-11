# -*- coding: utf-8 -*-
"""R5 公共决策前状态（T0；Scenario + DerivedState 确定性构造，只读语义）。

职责（R5 提示词 §3.1）：
- 复用 R2 已有 Scenario Materializer / DerivedState，不重复创建第二套公式；
- 由 Runner（以及 worker）在每次方法调用前统一构造；
- 对同一 scenario/seed 产生相同内容（确定性 content_hash）；
- 字段严格来自 Contract V2 / Schema V2 允许的 T0 决策前字段；
- 不包含最终 X/A/F、最终资源分配压力、其他方法结果或未来状态
  （FUTURE_TIMEPOINT_FIELDS 显式拒绝）；
- CARS 内部逐步 Q/Z 更新属于 RUAD 内部，不属于公共状态（本模块不计算）。

只读语义：方法在子进程中运行（进程隔离），Runner 持有的公共状态在每次
调用前重新构造，方法无法原位修改 Runner 的公共状态；本模块提供
snapshot() 深拷贝视图与 content_hash 供测试与审计验证。
"""

from __future__ import annotations

import hashlib
import json
from typing import Dict, List

from cars.simulator.derived_state import DerivedState
from cars.simulator.scenario_materializer import canonical_dumps, materialize_from_file

# T2-T4 产物字段：禁止出现在 T0 决策前状态
# （Contract Part 5.2, Assumption 2；与 validate_active_schema.py
#   FUTURE_TIMEPOINT_FIELDS 保持一致）
FUTURE_TIMEPOINT_FIELDS = (
    "offloading_decision",
    "assignment_matrix",
    "resource_allocation",
    "final_plan",
    "repair_diagnostics",
    "module_statuses",
    "task_results",
    "system_metrics",
)


class PredecisionStateError(ValueError):
    """公共决策前状态构造失败（场景非法或含未来信息字段）。"""


class PredecisionState:
    """T0 公共决策前状态 = Scenario（RUAD 合法输入）+ DerivedState。

    scenario：T0 Scenario dict（只读语义；Runner 持有，每次调用前构造）。
    derived：T0 DerivedState（决策前派生量；无最终 X/A/F）。
    """

    def __init__(self, scenario: Dict, derived: DerivedState):
        self.scenario = scenario
        self.derived = derived
        self._validate()

    # ------------------------------------------------------------------
    # 校验
    # ------------------------------------------------------------------

    def _validate(self) -> None:
        if not isinstance(self.scenario, dict):
            raise PredecisionStateError("public state: scenario must be a dict")
        if self.scenario.get("state_timepoint") != "T0":
            raise PredecisionStateError(
                "public state requires state_timepoint == 'T0', got %r"
                % (self.scenario.get("state_timepoint"),)
            )
        present = [f for f in FUTURE_TIMEPOINT_FIELDS if f in self.scenario]
        if present:
            raise PredecisionStateError(
                "public state contains future-timepoint field(s): %s"
                % ", ".join(present)
            )

    # ------------------------------------------------------------------
    # 确定性内容与只读视图
    # ------------------------------------------------------------------

    def content_hash(self) -> str:
        """确定性内容摘要（同一 scenario/seed 多次构造一致）。"""
        raw = canonical_dumps(self.scenario)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def snapshot(self) -> Dict:
        """深拷贝只读视图（供测试验证：方法修改副本不影响原状态）。"""
        return json.loads(json.dumps(self.scenario, ensure_ascii=False))

    def task_ids(self) -> List[str]:
        return self.derived.task_ids

    def server_ids(self) -> List[str]:
        return self.derived.server_ids


def build_predecision_state(scenario_cfg_path: str) -> PredecisionState:
    """统一公共决策前状态构造（R5 §3.1）。

    Scenario Materializer（确定性）+ DerivedState（T0 派生量）-> 校验 ->
    PredecisionState。同一配置路径、同一 seed 产生相同内容。
    """
    scenario = materialize_from_file(scenario_cfg_path)
    derived = DerivedState(scenario)
    return PredecisionState(scenario, derived)
