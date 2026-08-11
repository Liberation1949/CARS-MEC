# -*- coding: utf-8 -*-
"""foa 边界诊断方法（PROJECT_NATIVE 全卸载边界）。

身份（CARS_R3_FOA_CONTRACT_V1）：
  method_id: foa
  method_role: boundary_diagnostic
  baseline_identity: full_offloading_boundary
  source_type: project_defined（无原始论文；不得添加虚假文献元数据）
  reproduction_status: project_native
  exact_reproduction: false

冻结语义：
- 全部任务强制卸载：x_i = 1（合法场景，禁止本地回退）；
- 有效边感知的确定性轮询指派（eligibility_aware_round_robin）：任务按规范化
  task_id 升序处理，服务器按规范化 server_id 升序排列；全局轮询游标 p 从 0
  开始；对任务 i 从 p 循环扫描（p, p+1, ..., M-1, 0, ..., p-1），选第一台与
  任务 i 存在物理有效边的服务器 j*；p <- (index(j*)+1) mod M；
- 服务器内等份资源（equal_split）：对 Gamma_j 非空，f_ij = F_j / n_j；
  非指派边 f_ij = 0；
- 无有效边 -> 不本地回退、不删除任务、不选无效边、不伪造完整方案；按
  evaluator_contract 标准状态返回 METHOD_ERROR（方法不可行）并记录任务 ID；
- 无随机性：uses_randomness=false、uses_seed_for_decision=false、seed 忽略；
- 输入边界：只读取 task_id 顺序、server_id 顺序、N/M、物理有效边集合
  （derived.has_physical_edge 布尔）、服务器容量 F_j、eps_cmp；
  禁止读取 deadline/可靠性/故障率/传输数值/时延/能耗/效用/RUAD/CALA/Repair。

职责边界：方法只生成 X/A/F 与方法诊断；统一 Evaluator 由 MethodRunner 唯一
调用并如实记录 QoS 失败（FOA 不做任何修复；失败即边界诊断结果）。
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from cars.methods.protocol import MethodContext, MethodProposal
from cars.methods.registry import get_registry

METHOD_ID = "foa"
DISPLAY_NAME = "FOA"
METHOD_ROLE = "boundary_diagnostic"
BASELINE_IDENTITY = "full_offloading_boundary"
SOURCE_TYPE = "project_defined"
REPRODUCTION_STATUS = "project_native"
ASSIGNMENT_POLICY = "eligibility_aware_round_robin"
RESOURCE_POLICY = "equal_split"

# R2 冻结判定容差（evaluator_contract.yaml §5 eps_cmp = 1.0e-9）
EPS_CMP = 1.0e-9

# 允许的配置键白名单（无算法参数；未知键 -> 拒绝）
_ALLOWED_CONFIG_KEYS = {
    "method_id",
    "config_label",
    "scenario_config",
    "method_seed",
    "hard_timeout_seconds",
}


def _validate_config(config: Dict) -> Dict:
    """校验配置：拒绝未知算法参数（合同 §5.7）；method_id 必须匹配。"""
    if not isinstance(config, dict):
        raise ValueError("foa config must be a dict")
    unknown = set(config.keys()) - _ALLOWED_CONFIG_KEYS
    if unknown:
        raise ValueError("foa: unknown algorithm parameter(s): %s" % sorted(unknown))
    if config.get("method_id") != METHOD_ID:
        raise ValueError("method_id mismatch: %r" % (config.get("method_id"),))
    seed = config.get("method_seed", 0)
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("method_seed must be a non-negative int")
    hard = config.get("hard_timeout_seconds", 10.0)
    if not isinstance(hard, (int, float)) or hard <= 0:
        raise ValueError("hard_timeout_seconds must be positive")
    return dict(config)


def _build_diagnostics(
    task_ids: List[str],
    server_ids: List[str],
    selected_server_by_task: List[Optional[str]],
    eligible_by_task: List[List[str]],
    cursor_before: List[int],
    cursor_after: List[int],
    server_task_counts: List[int],
    server_capacity: List[float],
    allocated_capacity: List[float],
    no_eligible: List[str],
    runtime: float,
    success: bool,
    seed_ignored: bool,
) -> Dict:
    """构建诊断（合同 §5.8 字段）。

    success=False（无有效边不可行）时按实际状态记录，不伪造成功诊断。
    """
    n = len(task_ids)
    m = len(server_ids)
    if success:
        local_task_count = 0
        edge_task_count = n
        offloading_ratio = 1.0
        proposal_generated = True
    else:
        edge_eligible = n - len(no_eligible)
        local_task_count = 0  # FOA 从不选择本地
        edge_task_count = edge_eligible
        offloading_ratio = (float(edge_eligible) / n) if n else 0.0
        proposal_generated = False
    utilization = [
        (allocated_capacity[j] / server_capacity[j]) if server_capacity[j] > 0 else 0.0
        for j in range(m)
    ]
    return {
        "method_id": METHOD_ID,
        "baseline_identity": BASELINE_IDENTITY,
        "task_count": n,
        "server_count": m,
        "local_task_count": local_task_count,
        "edge_task_count": edge_task_count,
        "offloading_ratio": offloading_ratio,
        "canonical_task_order": list(task_ids),
        "canonical_server_order": list(server_ids),
        "assignment_policy": ASSIGNMENT_POLICY,
        "resource_policy": RESOURCE_POLICY,
        "selected_server_by_task": selected_server_by_task,
        "eligible_server_ids_by_task": eligible_by_task,
        "round_robin_cursor_before": cursor_before,
        "round_robin_cursor_after": cursor_after,
        "server_task_counts": server_task_counts,
        "server_capacity": server_capacity,
        "allocated_capacity_by_server": allocated_capacity,
        "capacity_utilization_by_server": utilization,
        "no_eligible_edge_task_ids": no_eligible,
        "uses_randomness": False,
        "seed_ignored": seed_ignored,
        "repair_used": False,
        "proposal_generated": proposal_generated,
        "method_runtime": runtime,
        "cleanup_completed": True,  # 进程内无子进程；进程树清理由 Runner 记录
    }


class FoaMethod:
    """全卸载边界诊断（确定性；seed 忽略）。"""

    method_id = METHOD_ID

    def __init__(self, config: Dict) -> None:
        self.config = _validate_config(config)

    def run(self, ctx: MethodContext) -> MethodProposal:
        t0 = time.monotonic()
        scenario = ctx.scenario
        derived = ctx.derived
        n = len(derived.task_ids)
        m = len(derived.server_ids)
        task_ids = list(derived.task_ids)
        server_ids = list(derived.server_ids)

        # X 全一（合法场景；禁止本地回退）
        X: List[int] = [1] * n

        A: List[List[int]] = [[0] * m for _ in range(n)]
        p = 0  # 全局轮询游标（p_0 = 0）
        selected_server_by_task: List[Optional[str]] = []
        eligible_by_task: List[List[str]] = []
        cursor_before: List[int] = []
        cursor_after: List[int] = []
        no_eligible: List[str] = []

        for i in range(n):
            # 只读取"该边是否有效"（derived.has_physical_edge 布尔；不读派生字段）
            eligible = [j for j in range(m) if derived.has_physical_edge(i, j)]
            eligible_by_task.append([server_ids[j] for j in eligible])
            cursor_before.append(p)
            if not eligible:
                no_eligible.append(task_ids[i])
                selected_server_by_task.append(None)
                cursor_after.append(p)
                continue
            # 从游标 p 循环扫描，选第一台物理有效服务器
            j_star: Optional[int] = None
            for k in range(m):
                j = (p + k) % m
                if j in eligible:
                    j_star = j
                    break
            assert j_star is not None
            A[i][j_star] = 1
            selected_server_by_task.append(server_ids[j_star])
            p = (j_star + 1) % m
            cursor_after.append(p)

        runtime = time.monotonic() - t0

        server_task_counts = [sum(1 for i in range(n) if A[i][j] == 1) for j in range(m)]
        server_capacity = [float(derived.server_state[j]["F_j"]) for j in range(m)]

        if no_eligible:
            # 无有效边 -> 标准 METHOD_ERROR（方法不可行；不得伪造完整方案）
            diag = _build_diagnostics(
                task_ids, server_ids, selected_server_by_task, eligible_by_task,
                cursor_before, cursor_after, server_task_counts, server_capacity,
                [0.0] * m, no_eligible, runtime, success=False,
                seed_ignored=True,
            )
            return MethodProposal(
                decision=None,
                method_status="METHOD_ERROR",
                timed_out=False,
                runtime_seconds=runtime,
                diagnostics=diag,
            )

        # 服务器内等份资源分配（equal_split；禁止 CALA/LA/个性化权重）
        F: List[List[float]] = [[0.0] * m for _ in range(n)]
        allocated_capacity = [0.0] * m
        for j in range(m):
            members = [i for i in range(n) if A[i][j] == 1]
            if members:
                alloc = server_capacity[j] / len(members)
                for i in members:
                    F[i][j] = alloc
                allocated_capacity[j] = server_capacity[j]

        decision = {
            "schema_version": "CARS_ACTIVE_SCHEMA_V1",
            "offloading_decision": X,
            "assignment_matrix": A,
            "resource_allocation": F,
        }
        diag = _build_diagnostics(
            task_ids, server_ids, selected_server_by_task, eligible_by_task,
            cursor_before, cursor_after, server_task_counts, server_capacity,
            allocated_capacity, no_eligible, runtime, success=True,
            seed_ignored=True,
        )
        return MethodProposal(
            decision=decision,
            method_status="SUCCESS",
            timed_out=False,
            runtime_seconds=runtime,
            diagnostics=diag,
        )


def _factory(config: Dict) -> FoaMethod:
    return FoaMethod(config)


get_registry().register(METHOD_ID, _factory)
