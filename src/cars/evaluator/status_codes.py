# -*- coding: utf-8 -*-
"""Evaluator 状态码与完整错误代码枚举（R2 冻结；configs/r2/evaluator_contract.yaml §1）。

Evaluator 只处理 Contract Part 9.2 三类结果中的前两类：
- 输入结构非法（INPUT_INVALID）；
- 硬约束违约（INVALID_DECISION / PHYSICAL_INFEASIBLE）。
方法内部失败（TIMEOUT/METHOD_ERROR/INTERNAL_ERROR）属于 method_status 语义
（R3 Method Runner 应用失败计分），Evaluator 是"照镜子"不判定方法内部失败。
"""

from __future__ import annotations

from enum import Enum


class EvaluatorStatus(str, Enum):
    """Evaluator 方案级状态（R2 冻结）。"""

    INPUT_INVALID = "INPUT_INVALID"
    INVALID_DECISION = "INVALID_DECISION"
    PHYSICAL_INFEASIBLE = "PHYSICAL_INFEASIBLE"
    VALID = "VALID"


class FailureReason(str, Enum):
    """任务失败原因（复用 Schema common.failure_reason；Contract Part 3.2 六条件顺序）。"""

    STRUCT_INVALID = "STRUCT_INVALID"
    PATH_AMBIGUOUS = "PATH_AMBIGUOUS"
    EXEC_INVALID = "EXEC_INVALID"
    CAPACITY_INFEASIBLE = "CAPACITY_INFEASIBLE"
    DEADLINE_VIOLATION = "DEADLINE_VIOLATION"
    RELIABILITY_VIOLATION = "RELIABILITY_VIOLATION"
    SUCCESS = "SUCCESS"


class ErrorCode(str, Enum):
    """完整错误代码枚举（R2 冻结；诊断可定位用）。

    编号段：
    - EC-1xx 输入结构非法（INPUT_INVALID）
    - EC-2xx 决策结构非法（INVALID_DECISION，C1-C3）
    - EC-3xx 物理约束违约（PHYSICAL_INFEASIBLE，C4-C6）
    - EC-4xx 任务 QoS 失败（VALID 内逐任务失败原因）
    - EC-5xx Evaluator 内部错误
    """

    # 输入
    INPUT_SCHEMA_INVALID = "EC-101"
    INPUT_NAN_INF = "EC-102"
    INPUT_DOMAIN_INVALID = "EC-103"

    # 决策结构（C1-C3）
    DECISION_DIMENSION_INVALID = "EC-201"
    DECISION_BINARY_INVALID = "EC-202"
    DECISION_PATH_AMBIGUOUS = "EC-203"  # C3: sum_j a_ij != x_i

    # 物理约束（C4-C6）
    CONSTRAINT_EDGE_INVALID = "EC-301"  # C4: a_ij=1 但 e_phy=0
    CONSTRAINT_RESOURCE_ACTIVATION = "EC-302"  # C5: a=0 但 f!=0，或 f 越界
    CONSTRAINT_CAPACITY = "EC-303"  # C6: sum_i f_ij > F_j

    # 任务 QoS（六条件顺序）
    EXEC_RESOURCE_INVALID = "EC-401"  # 卸载 f=0（EXEC_INVALID）
    DEADLINE_VIOLATION = "EC-402"
    RELIABILITY_VIOLATION = "EC-403"

    # 内部
    INTERNAL_ERROR = "EC-501"


EVALUATOR_STATUS_ORDER = [
    EvaluatorStatus.INPUT_INVALID,
    EvaluatorStatus.INVALID_DECISION,
    EvaluatorStatus.PHYSICAL_INFEASIBLE,
    EvaluatorStatus.VALID,
]
