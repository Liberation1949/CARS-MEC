# -*- coding: utf-8 -*-
"""local_only 弱 Baseline（本地执行边界参考，PROJECT_DEFINED）。

固定全本地方案：x_i=0（全部任务本地执行），A/F 为 N x M 全零矩阵。
不使用无线卸载、边缘服务器指派或边缘计算资源；不使用服务器/链路/QoS 字段
参与决策；无算法参数、无随机性（method seed 被忽略）。

职责边界（CARS_R3_LOCAL_ONLY_CONTRACT_V1）：
- 方法只生成 X/A/F 与方法诊断（METHOD_PROPOSAL_GENERATED）；
- 本地时延/能耗/可靠性/deadline/reliability 违约/z_i/TSSR/有效可靠性/有效效用
  由统一 Evaluator 在方法输出后计算；
- 本地 QoS 失败是该边界方法的真实实验结果，不得触发卸载或 Repair。
"""

from __future__ import annotations

import time
from typing import Dict, List

from cars.methods.protocol import MethodContext, MethodProposal
from cars.methods.registry import get_registry

METHOD_ID = "local_only"
BASELINE_IDENTITY = "local_execution_boundary_reference"

# 允许的配置键白名单（无算法参数；未知键 -> 拒绝）
_ALLOWED_CONFIG_KEYS = {
    "method_id",
    "config_label",
    "scenario_config",
    "method_seed",
    "hard_timeout_seconds",
}


def _validate_config(config: Dict) -> Dict:
    """校验配置：拒绝未知算法参数（合同 §5.4）；method_id 必须匹配。"""
    if not isinstance(config, dict):
        raise ValueError("local_only config must be a dict")
    unknown = set(config.keys()) - _ALLOWED_CONFIG_KEYS
    if unknown:
        raise ValueError(
            "local_only: unknown algorithm parameter(s): %s" % sorted(unknown)
        )
    if config.get("method_id") != METHOD_ID:
        raise ValueError("method_id mismatch: %r" % (config.get("method_id"),))
    seed = config.get("method_seed", 0)
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("method_seed must be a non-negative int")
    hard = config.get("hard_timeout_seconds", 10.0)
    if not isinstance(hard, (int, float)) or hard <= 0:
        raise ValueError("hard_timeout_seconds must be positive")
    return dict(config)


class LocalOnlyMethod:
    """固定全本地方案（确定性；seed 忽略）。"""

    method_id = METHOD_ID

    def __init__(self, config: Dict) -> None:
        self.config = _validate_config(config)

    def run(self, ctx: MethodContext) -> MethodProposal:
        t0 = time.monotonic()
        scenario = ctx.scenario
        # 只读取 N（任务数量）与 M（服务器数量）用于构造输出维度
        n = len(scenario["tasks"])
        m = len(scenario["servers"])

        X: List[int] = [0] * n
        A: List[List[int]] = [[0] * m for _ in range(n)]
        F: List[List[float]] = [[0.0] * m for _ in range(n)]

        decision = {
            "schema_version": "CARS_ACTIVE_SCHEMA_V1",
            "offloading_decision": X,
            "assignment_matrix": A,
            "resource_allocation": F,
        }

        runtime = time.monotonic() - t0
        diagnostics = {
            "method_id": METHOD_ID,
            "baseline_identity": BASELINE_IDENTITY,
            "task_count": n,
            "server_count": m,
            "local_task_count": n,
            "edge_task_count": 0,
            "offload_ratio": 0.0,
            "uses_randomness": False,
            "seed_ignored": True,
            "algorithm_parameter_count": 0,
            "proposal_generated": True,  # METHOD_PROPOSAL_GENERATED
            "method_runtime": runtime,
            "cleanup_completed": True,
        }
        return MethodProposal(
            decision=decision,
            method_status="SUCCESS",
            timed_out=False,
            runtime_seconds=runtime,
            diagnostics=diagnostics,
        )


def _factory(config: Dict) -> LocalOnlyMethod:
    return LocalOnlyMethod(config)


get_registry().register(METHOD_ID, _factory)
