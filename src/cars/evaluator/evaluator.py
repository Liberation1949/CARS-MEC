# -*- coding: utf-8 -*-
"""统一 Evaluator 主流程（R2 公共底座；提示词 Step 3.4）。

固定执行顺序：结构校验 -> X/A/F 一致性 -> 物理可行性 -> 时延/能耗/可靠性计算
-> QoS 成功判定 -> 指标汇总 -> 状态与诊断 -> Canonical Result。

Evaluator 是"照镜子"：只根据实际证据（Scenario + DerivedState + decision）判定，
不修改方法决策，不修复方法结果（Contract Part 6.5）。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from cars.evaluator import constraints
from cars.evaluator.metrics import evaluate_all_metrics
from cars.evaluator.status_codes import ErrorCode, EvaluatorStatus, FailureReason
from cars.simulator.derived_state import DerivedState


def _failed_tasks_for_invalid(scenario: Dict, error_codes: List[str]) -> List[Dict]:
    """INVALID_DECISION 方案：全部任务 z_i=0，保留失败原因。"""
    reason = (
        FailureReason.PATH_AMBIGUOUS.value
        if ErrorCode.DECISION_PATH_AMBIGUOUS.value in error_codes
        else FailureReason.STRUCT_INVALID.value
    )
    results = []
    for task in scenario["tasks"]:
        results.append(
            {
                "task_id": task["task_id"],
                "success": 0,
                "evaluable": 0,
                "end_to_end_delay_seconds": "inf",
                "end_to_end_reliability": 0.0,
                "effective_reliability": 0.0,
                "utility": 0.0,
                "effective_utility": 0.0,
                "failure_reason": reason,
            }
        )
    return results


def _zero_system_metrics() -> Dict:
    # 无 deadline 模型（E1-CR 2026-08-08）：V_D 系列字段删除，仅 V_R
    return {
        "tssr": 0.0,
        "mean_effective_reliability": 0.0,
        "mean_effective_utility": 0.0,
        "reliability_violation_rate": 0.0,
    }


def _constraint_diagnostics(scenario: Dict, decision: Dict, phy_errors: List[str], has_phy_edge) -> List[Dict]:
    """构造约束违约诊断（可定位到 task_id / server_id；observed / bound / stage）。"""
    diag = []
    n = len(scenario["tasks"])
    m = len(scenario["servers"])
    a = decision.get("assignment_matrix") or []
    f = decision.get("resource_allocation") or []
    f_j = [s["capacity_cycles_per_sec"] for s in scenario["servers"]]

    if ErrorCode.CONSTRAINT_EDGE_INVALID.value in phy_errors:
        for i in range(n):
            for j in range(m):
                if i < len(a) and j < len(a[i]) and a[i][j] == 1 and not has_phy_edge(i, j):
                    diag.append(
                        {
                            "code": ErrorCode.CONSTRAINT_EDGE_INVALID.value,
                            "stage": "physical_feasibility",
                            "task_id": scenario["tasks"][i]["task_id"],
                            "server_id": scenario["servers"][j]["server_id"],
                            "observed": "a=1",
                            "required": "e_phy=1",
                        }
                    )
                    return diag
    if ErrorCode.CONSTRAINT_RESOURCE_ACTIVATION.value in phy_errors:
        for i in range(n):
            for j in range(m):
                if i < len(a) and j < len(a[i]):
                    if a[i][j] == 0 and abs(f[i][j]) > constraints.EPS_CMP:
                        diag.append(
                            {
                                "code": ErrorCode.CONSTRAINT_RESOURCE_ACTIVATION.value,
                                "stage": "physical_feasibility",
                                "task_id": scenario["tasks"][i]["task_id"],
                                "server_id": scenario["servers"][j]["server_id"],
                                "observed": "f=%.6g with a=0" % f[i][j],
                                "required": "f=0",
                            }
                        )
                        return diag
                    if f[i][j] > a[i][j] * f_j[j] + constraints.EPS_CMP:
                        diag.append(
                            {
                                "code": ErrorCode.CONSTRAINT_RESOURCE_ACTIVATION.value,
                                "stage": "physical_feasibility",
                                "task_id": scenario["tasks"][i]["task_id"],
                                "server_id": scenario["servers"][j]["server_id"],
                                "observed": "f=%.6g" % f[i][j],
                                "required": "f<=a*F_j=%.6g" % (a[i][j] * f_j[j]),
                            }
                        )
                        return diag
    if ErrorCode.CONSTRAINT_CAPACITY.value in phy_errors:
        for j in range(m):
            total = sum(f[i][j] for i in range(n)) if f else 0.0
            if total > f_j[j] + constraints.EPS_CMP:
                diag.append(
                    {
                        "code": ErrorCode.CONSTRAINT_CAPACITY.value,
                        "stage": "physical_feasibility",
                        "server_id": scenario["servers"][j]["server_id"],
                        "observed": "sum_i f_ij=%.6g" % total,
                        "required": "<=F_j=%.6g" % f_j[j],
                    }
                )
                return diag
    return diag


def evaluate(scenario: Dict, decision: Dict, derived_state: Optional[DerivedState] = None) -> Dict:
    """Evaluator 主流程。返回 {evaluator_status, evaluator_output, diagnostics}。

    - evaluator_output：符合 evaluator_io.schema.json 的 EvaluatorOutput dict；
      INPUT_INVALID 时为 None（拒绝计算）。
    - diagnostics：约束/QoS 违约诊断（可定位）。
    """
    derived = derived_state if derived_state is not None else DerivedState(scenario)
    n = len(scenario["tasks"])

    # ---- 1. 结构校验（INPUT_INVALID）----
    input_errors = constraints.check_input_valid(scenario, decision)
    if input_errors:
        return {
            "evaluator_status": EvaluatorStatus.INPUT_INVALID,
            "evaluator_output": None,
            "diagnostics": {
                "input_errors": input_errors,
                "constraint": [],
                "predecision_infeasible": derived.predecision_infeasible,
            },
        }

    # ---- 2. X/A/F 一致性（INVALID_DECISION）----
    struct_errors = constraints.check_xaf_consistency(scenario, decision)
    if struct_errors:
        task_results = _failed_tasks_for_invalid(scenario, struct_errors)
        return {
            "evaluator_status": EvaluatorStatus.INVALID_DECISION,
            "evaluator_output": {
                "schema_version": scenario["schema_version"],
                "state_timepoint": "T4",
                "scenario_id": scenario["scenario_id"],
                "task_results": task_results,
                "system_metrics": _zero_system_metrics(),
            },
            "diagnostics": {
                "input_errors": [],
                "constraint": [
                    {
                        "code": ec,
                        "stage": "xaf_consistency",
                        "task_id": None,
                        "server_id": None,
                        "observed": "decision structure",
                        "required": "C1-C3",
                    }
                    for ec in struct_errors
                ],
                "predecision_infeasible": derived.predecision_infeasible,
            },
        }

    # ---- 3. 物理可行性（PHYSICAL_INFEASIBLE / VALID）----
    phy_errors = constraints.check_physical_feasibility(
        scenario, decision, derived.has_physical_edge
    )
    cap_flags = constraints.all_cap_flags(scenario, decision)
    evaluator_status = (
        EvaluatorStatus.PHYSICAL_INFEASIBLE if phy_errors else EvaluatorStatus.VALID
    )
    constraint_diag = _constraint_diagnostics(
        scenario, decision, phy_errors, derived.has_physical_edge
    )

    # ---- 4-6. 时延/能耗/可靠性计算 -> QoS 判定 -> 指标汇总 ----
    metrics = evaluate_all_metrics(derived, decision, cap_flags)

    # ---- 7. 状态与诊断 ----
    qos_diag = []
    for r in metrics["task_results"]:
        if r["failure_reason"] != FailureReason.SUCCESS.value:
            qos_diag.append(
                {
                    "task_id": r["task_id"],
                    "failure_reason": r["failure_reason"],
                    "delay": r["end_to_end_delay_seconds"],
                    "reliability": r["end_to_end_reliability"],
                }
            )

    return {
        "evaluator_status": evaluator_status,
        "evaluator_output": {
            "schema_version": scenario["schema_version"],
            "state_timepoint": "T4",
            "scenario_id": scenario["scenario_id"],
            "task_results": metrics["task_results"],
            "system_metrics": metrics["system_metrics"],
        },
        "diagnostics": {
            "input_errors": [],
            "constraint": constraint_diag,
            "qos_failures": qos_diag,
            "predecision_infeasible": derived.predecision_infeasible,
        },
    }
