# -*- coding: utf-8 -*-
"""AADA+RCLA 候选阶段专属诊断（CARS §3.5）。

组合 AADA / RCLA 诊断 + 总体字段（pre_evaluation X/A/F hash、candidate
method runtime）。TSSR / Rbar_eff / Ubar_eff / V_R 由阶段专属 runner 从统一
Evaluator 输出填写（Evaluator 是正式指标的唯一定义者；方法内部不调用完整
Evaluator）。
"""

from __future__ import annotations

import hashlib
import json
from typing import Dict, List


def _decision_hash(x: List[int], a: List[List[int]], f: List[List[float]]) -> str:
    """pre-evaluation X/A/F hash（确定性 SHA-256，规范化 JSON）。"""
    payload = {
        "offloading_decision": [int(v) for v in x],
        "assignment_matrix": [[int(v) for v in row] for row in a],
        "resource_allocation": [
            [round(float(v), 12) for v in row] for row in f
        ],
    }
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_candidate_diagnostics(
    aada_diagnostics: Dict,
    rcla_diagnostics: Dict,
    decision: Dict,
    method_runtime_seconds: float,
) -> Dict:
    """组合阶段专属诊断（可定位字段；全部确定性数值）。"""
    diag = {
        "algorithm": "AADA+RCLA",
        "phase": "CARS",
        "aada": aada_diagnostics,
        "rcla": rcla_diagnostics,
        "pre_evaluation_xaf_hash": _decision_hash(
            decision["offloading_decision"],
            decision["assignment_matrix"],
            decision["resource_allocation"],
        ),
        "candidate_method_runtime_seconds": float(method_runtime_seconds),
        # TSSR / Rbar_eff / Ubar_eff / V_R 由阶段专属 runner 从统一 Evaluator
        # 输出回填（保持 Evaluator 唯一指标计算者边界）。
        "tssr": None,
        "rbar_eff": None,
        "ubar_eff": None,
        "v_r": None,
    }
    return diag
