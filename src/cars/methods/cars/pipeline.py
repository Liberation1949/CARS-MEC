# -*- coding: utf-8 -*-
"""CARS Pipeline（AADA → RCLA；no Repair layer）。

编排（正文 V-D.1 Algorithm V）：T0 Scenario -> AADA（assignment，V-B.7
Algorithm V-1）-> RCLA（allocation，V-C.5 Algorithm V-2）-> 输出完整方案
Pi = (X, A, F) 交统一 Evaluator 评价。

Repair = OFF（正文 V-B.5：CARS 在指派阶段即维持 floor 可行性，无需事后
指派修复层；V-A.4 Table V-1 仅 AADA/RCLA 两模块）。

不调用完整统一 Evaluator（Evaluator 由 Runner 唯一调用，T5）；仅引用共享
指标原语 cars.evaluator.metrics。
"""

from __future__ import annotations

import time
from typing import Dict

from cars.methods.cars.aada import run_aada
from cars.methods.cars.diagnostics import build_candidate_diagnostics
from cars.methods.cars.rcla import run_ordinary_la, run_rcla
from cars.methods.cars.state import CandidateStateView

# 正式 CARS 决策 Schema 版本（Schema V4；仅元数据，不改变 X/A/F 数学语义）
DECISION_SCHEMA_VERSION = "CARS_ACTIVE_SCHEMA_V4"

def run_aada_rcla_pipeline(
    scenario: Dict,
    derived,
    *,
    eps_cmp: float,
    rcla_cfg: Dict,
    aada_variant: str = "full",
    allocation_mode: str = "rcla",
) -> Dict:
    """CARS 主流程（AADA + allocation）。返回 {decision, method_status, diagnostics}。

    - aada_variant：full | no_rescue | rescue_only | no_alloc_aware |
      no_utility_gate（E3-V2 组件消融；见 aada.run_aada）；
    - allocation_mode：rcla（默认，reliability floor）| ordinary_la
      （fixed-assignment 普通 LA 对照，同一 X/A 只换 allocation）。
    """
    t0 = time.monotonic()

    # ---- 决策前状态视图（只读）----
    t_pre = time.monotonic()
    view = CandidateStateView(scenario, derived)
    preprocess_ms = (time.monotonic() - t_pre) * 1000.0

    # ---- AADA（assignment；阶段一 rescue + 阶段二 P0 字典序门控）----
    aada_result = run_aada(
        view, eps_cmp=eps_cmp, rcla_cfg=rcla_cfg, variant=aada_variant
    )

    # ---- Allocation（固定 AADA 的 A；Repair OFF）----
    if allocation_mode == "ordinary_la":
        rcla_result = run_ordinary_la(view, aada_result["assignment_matrix"])
    else:
        rcla_result = run_rcla(
            view,
            aada_result["assignment_matrix"],
            eps_cmp=eps_cmp,
            rcla_cfg=rcla_cfg,
        )

    decision = {
        "schema_version": DECISION_SCHEMA_VERSION,
        "offloading_decision": list(aada_result["offloading_decision"]),
        "assignment_matrix": [list(row) for row in aada_result["assignment_matrix"]],
        "resource_allocation": [
            list(row) for row in rcla_result["resource_allocation"]
        ],
    }

    diagnostics = build_candidate_diagnostics(
        aada_diagnostics=aada_result["diagnostics"],
        rcla_diagnostics=rcla_result["diagnostics"],
        decision=decision,
        method_runtime_seconds=time.monotonic() - t0,
    )

    # ---- E3-V2 运行时细分（§VI-E.1 / §V-D.2 快照式复杂度实测基线）----
    diagnostics["aada_variant"] = aada_variant
    diagnostics["allocation_mode"] = allocation_mode
    diagnostics["runtime_breakdown"] = {
        "preprocess_ms": round(float(preprocess_ms), 3),
        "aada_phase1_ms": round(
            float(aada_result["diagnostics"]["phase1_runtime_ms"]), 3
        ),
        "aada_phase2_ms": round(
            float(aada_result["diagnostics"]["phase2_runtime_ms"]), 3
        ),
        "rcla_ms": round(float(rcla_result["diagnostics"]["runtime_ms"]), 3),
        "total_ms": round(float((time.monotonic() - t0) * 1000.0), 3),
    }

    return {
        "decision": decision,
        "method_status": "SUCCESS",
        "diagnostics": diagnostics,
    }


def run_cars_pipeline(
    scenario: Dict,
    derived,
    params: Dict,
    eps_cmp: float,
    *,
    aada_variant: str = "full",
    allocation_mode: str = "rcla",
) -> Dict:
    """正式 CARS 主流程（AADA→RCLA；默认 full/rcla）。

    params：RCLA 求解器配置（rcla_mu_tol/rcla_max_iters/rcla_mu_lo/
    rcla_mu_hi/rcla_numeric_epsilon；Contract V4 §7）。

    返回 {decision, method_status, diagnostics, module_statuses}：
    - decision = {schema_version: V4, offloading_decision, assignment_matrix,
      resource_allocation}（X/A/F 与候选逐值一致；仅 schema_version 元数据为 V4）；
    - diagnostics = 候选 AADA/RCLA 组合诊断（pre_evaluation_xaf_hash 等）；
    - module_statuses = [aada SUCCESS, rcla SUCCESS]（无 Repair）。
    """
    result = run_aada_rcla_pipeline(
        scenario,
        derived,
        eps_cmp=eps_cmp,
        rcla_cfg=dict(params),
        aada_variant=aada_variant,
        allocation_mode=allocation_mode,
    )
    result["decision"]["schema_version"] = DECISION_SCHEMA_VERSION
    result["module_statuses"] = [
        {"module": "aada", "status": "SUCCESS"},
        {"module": "rcla", "status": "SUCCESS"},
    ]
    return result


def run_cars_with_params(scenario: Dict, derived, params: Dict, eps_cmp: float) -> Dict:
    """便捷入口：直接运行正式 CARS Pipeline（默认 full/rcla）。"""
    return run_cars_pipeline(scenario, derived, params, eps_cmp)
