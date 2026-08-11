# -*- coding: utf-8 -*-
"""Canonical Result Record 构建器（R2 公共底座；提示词 Step 3.5）。

结果包含：scenario/config/seed 标识、method 标识、X/A/F、method status、
evaluator status、task-level metrics、system-level metrics、constraint
diagnostics、runtime/timeout 字段、schema/version 信息、reproducibility metadata。

Canonical 原则（AGENTS.md §13 / 用户记忆）：
- 墙上时钟（runtime_seconds）与随机/系统状态查询为 _NON_CANONICAL_FIELDS，
  不进入 canonical hash；
- canonical hash = 同一输入同 seed 多次运行字节级一致（SHA-256）。
"""

from __future__ import annotations

import hashlib
import json
from typing import Dict

RESULT_VERSION = "CARS_R2_CANONICAL_RESULT_V1"

# 非 canonical 字段：不进入字节复现 hash（运行时间依赖墙上时钟）
NON_CANONICAL_FIELDS = ("runtime_seconds",)


def _strip_non_canonical(obj):
    if isinstance(obj, dict):
        return {
            k: _strip_non_canonical(v)
            for k, v in obj.items()
            if k not in NON_CANONICAL_FIELDS
        }
    if isinstance(obj, list):
        return [_strip_non_canonical(v) for v in obj]
    return obj


def canonical_hash(payload: Dict) -> str:
    """对排除非 canonical 字段后的内容计算 SHA-256（字节级复现）。"""
    clean = _strip_non_canonical(payload)
    raw = json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_canonical_result(
    *,
    scenario: Dict,
    config_hash: str,
    seed: int,
    method_id: str,
    method_status: str,
    timed_out: bool,
    decision: Dict,
    evaluator_status: str,
    evaluator_output: Dict,
    diagnostics: Dict,
    runtime_seconds: float,
    python_version: str,
) -> Dict:
    """组装完整 Canonical Result dict。"""
    result = {
        "result_version": RESULT_VERSION,
        "schema_version": scenario["schema_version"],
        "scenario_id": scenario["scenario_id"],
        "config_hash": config_hash,
        "seed": seed,
        "method_id": method_id,
        "method_status": method_status,
        "evaluator_status": evaluator_status,
        "decision": decision,
        "evaluator_output": evaluator_output,
        "diagnostics": diagnostics,
        "runtime_seconds": runtime_seconds,
        "timed_out": timed_out,
        "reproducibility": {
            "python_version": python_version,
            "canonical_hash": None,  # 占位，下方计算
        },
    }
    result["reproducibility"]["canonical_hash"] = canonical_hash(result)
    return result
