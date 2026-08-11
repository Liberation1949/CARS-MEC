# -*- coding: utf-8 -*-
"""X/A/F 结构检查与物理可行域约束（C1-C6；Contract F-36/F-37, 正文 IV-B）。

Evaluator 固定顺序（Contract Part 3.2 / 提示词 Step 3.4）：
1. 结构校验（输入含 NaN/Inf/定义域）-> INPUT_INVALID
2. X/A/F 一致性（C1-C3 + 维度）-> INVALID_DECISION
3. 物理可行性（C4-C6）-> PHYSICAL_INFEASIBLE

本模块只做结构/物理判定，不计算指标。浮点容差 eps_cmp 用于 C5/C6 的
越界判断（吸收舍入误差），不改变数学语义。
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

from cars.evaluator.status_codes import ErrorCode

EPS_CMP = 1.0e-9  # 判定比较绝对容差（evaluator_contract.yaml §5）
# MATH-FMIN-CR-R2（2026-08-11 用户批准）：最小可调度执行计算速率 f_min^exec=1.0 cycles/s。
# 硬物理可行条件：a_ij=1 => f_ij >= f_min^exec（闭合 P0 可行域，消除 f->0+ supremum 风险）。
F_MIN_EXEC = 1.0


# ---------------------------------------------------------------------------
# 1. 输入结构校验（INPUT_INVALID）
# ---------------------------------------------------------------------------


def contains_nan_or_inf(obj) -> bool:
    """递归检测 NaN / +/-Inf。"""
    if isinstance(obj, dict):
        return any(contains_nan_or_inf(v) for v in obj.values())
    if isinstance(obj, list):
        return any(contains_nan_or_inf(v) for v in obj)
    if isinstance(obj, float):
        return math.isnan(obj) or math.isinf(obj)
    return False


def check_input_valid(scenario: Dict, decision: Dict) -> List[str]:
    """返回输入非法错误代码列表；空列表 = 通过。"""
    errors = []
    if contains_nan_or_inf(scenario) or contains_nan_or_inf(decision):
        errors.append(ErrorCode.INPUT_NAN_INF.value)
    # 决策 required 字段存在性（结构层）
    for key in ("offloading_decision", "assignment_matrix", "resource_allocation"):
        if key not in decision:
            errors.append(ErrorCode.INPUT_SCHEMA_INVALID.value)
            break
    return errors


# ---------------------------------------------------------------------------
# 2. X/A/F 一致性（C1-C3）
# ---------------------------------------------------------------------------


def check_xaf_consistency(scenario: Dict, decision: Dict) -> List[str]:
    """返回决策结构非法错误代码列表；空列表 = 满足 C1-C3。

    检查：X/A/F 维度；C1 x 二元；C2 a 二元；C3 sum_j a_ij == x_i。
    """
    errors = []
    n = len(scenario["tasks"])
    m = len(scenario["servers"])
    x = decision.get("offloading_decision")
    a = decision.get("assignment_matrix")
    f = decision.get("resource_allocation")

    if not isinstance(x, list) or len(x) != n:
        errors.append(ErrorCode.DECISION_DIMENSION_INVALID.value)
        return errors
    if not isinstance(a, list) or len(a) != n or any(len(row) != m for row in a):
        errors.append(ErrorCode.DECISION_DIMENSION_INVALID.value)
        return errors
    if not isinstance(f, list) or len(f) != n or any(len(row) != m for row in f):
        errors.append(ErrorCode.DECISION_DIMENSION_INVALID.value)
        return errors

    for i in range(n):
        if x[i] not in (0, 1):
            errors.append(ErrorCode.DECISION_BINARY_INVALID.value)
        for j in range(m):
            if a[i][j] not in (0, 1):
                errors.append(ErrorCode.DECISION_BINARY_INVALID.value)
            if not isinstance(f[i][j], (int, float)) or math.isnan(f[i][j]):
                errors.append(ErrorCode.DECISION_BINARY_INVALID.value)
    if errors:
        return errors

    for i in range(n):
        if sum(a[i]) != x[i]:
            errors.append(ErrorCode.DECISION_PATH_AMBIGUOUS.value)
            return errors
    return errors


# ---------------------------------------------------------------------------
# 3. 物理可行性（C4-C6）
# ---------------------------------------------------------------------------


def check_physical_feasibility(scenario: Dict, decision: Dict, has_phy_edge) -> List[str]:
    """返回物理约束违约错误代码列表；空列表 = 满足 C4-C6。

    has_phy_edge(i, j) -> bool：由 DerivedState 提供的 e_phy 查询。
    """
    errors = []
    n = len(scenario["tasks"])
    m = len(scenario["servers"])
    a = decision["assignment_matrix"]
    f = decision["resource_allocation"]
    f_j = [s["capacity_cycles_per_sec"] for s in scenario["servers"]]

    # C4: a_ij <= e_phy_ij
    for i in range(n):
        for j in range(m):
            if a[i][j] == 1 and not has_phy_edge(i, j):
                errors.append(ErrorCode.CONSTRAINT_EDGE_INVALID.value)
                return errors  # 首个 C4 违约即可定位

    # C5: a=0 => f=0；a=1 => f >= f_min^exec（最小可调度速率，MATH-FMIN-CR-R2）；f <= a*F_j
    for i in range(n):
        for j in range(m):
            if a[i][j] == 0 and abs(f[i][j]) > EPS_CMP:
                errors.append(ErrorCode.CONSTRAINT_RESOURCE_ACTIVATION.value)
                return errors
            if f[i][j] < -EPS_CMP:
                errors.append(ErrorCode.CONSTRAINT_RESOURCE_ACTIVATION.value)
                return errors
            if a[i][j] == 1 and f[i][j] < F_MIN_EXEC - EPS_CMP:
                errors.append(ErrorCode.CONSTRAINT_RESOURCE_ACTIVATION.value)
                return errors
            if f[i][j] > a[i][j] * f_j[j] + EPS_CMP:
                errors.append(ErrorCode.CONSTRAINT_RESOURCE_ACTIVATION.value)
                return errors

    # C6: sum_i f_ij <= F_j
    for j in range(m):
        total = sum(f[i][j] for i in range(n))
        if total > f_j[j] + EPS_CMP:
            errors.append(ErrorCode.CONSTRAINT_CAPACITY.value)
            return errors
    return errors


def g_j_cap(scenario: Dict, decision: Dict, j: int) -> int:
    """[F-18] g_j^cap = I[sum_i f_ij <= F_j]。"""
    total = sum(row[j] for row in decision["resource_allocation"])
    return 1 if total <= scenario["servers"][j]["capacity_cycles_per_sec"] + EPS_CMP else 0


def all_cap_flags(scenario: Dict, decision: Dict) -> List[int]:
    """返回全部服务器的 g_j^cap 列表（维度 M）。"""
    return [g_j_cap(scenario, decision, j) for j in range(len(scenario["servers"]))]
