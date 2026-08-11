# -*- coding: utf-8 -*-
"""R5 统一方法解析与决策归一化适配层。

职责（R5 提示词 §3.2/§3.3）：
- METHOD_WHITELIST：七方法正式白名单（cars + 六 Baseline），确定性元组顺序；
- resolve_method：统一方法解析——白名单校验 -> 全局 Registry（六 Baseline）
  -> 最小动态导入（仅白名单内的 CARS，R4 worker fallback 扩展点保留）；
- normalize_decision：将方法返回 decision 的 schema_version 归一化为当前
  正式版本（CARS_ACTIVE_SCHEMA_V4，CR-CARS-PROMOTION-E1）。V1/V2/V4 的
  schedule_decision 结构完全一致（仅 schema_version const 值不同），归一化
  只改元数据字符串，不改变 X/A/F 与任何数学语义。

边界（R5 提示词 §3.2/§3.5）：
- 所有七种方法最终必须通过同一 MethodRunner.run() 调用（子进程隔离）；
  本层只做解析与元数据归一化，不为 CARS 或任何 Baseline 建立特殊执行分支；
- 不修改六 Baseline 算法核心（AC-8）：归一化发生在 Runner 返回对象上，
  六方法文件零改动；
- 超出白名单的 method_id -> KeyError -> worker METHOD_ERROR（R3 行为不退化）。
"""

from __future__ import annotations

import importlib
from typing import Dict, Optional

# 七方法正式白名单（R5 提示词 §一；确定性元组顺序，同时作为白名单集合）
METHOD_WHITELIST = (
    "cars",
    "nfa_adapted",
    "bpso_rata_la",
    "jtora_adapted",
    "reliability_only",
    "local_only",
    "foa",
)

# 当前正式决策 Schema 版本（CR-CARS-PROMOTION-E1 后为 V4）
CURRENT_DECISION_SCHEMA_VERSION = "CARS_ACTIVE_SCHEMA_V4"

# 接受归一化的历史版本（六 Baseline 返回 V1；结构一致仅版本标识不同）
ACCEPTED_DECISION_SCHEMA_VERSIONS = (
    "CARS_ACTIVE_SCHEMA_V1",
    "CARS_ACTIVE_SCHEMA_V2",
    "CARS_ACTIVE_SCHEMA_V4",
)


def resolve_method(registry_obj, method_id: str, method_config: Dict):
    """统一方法解析（R5 §3.2）。

    顺序：
    1. 白名单校验（超出七方法白名单 -> KeyError -> worker METHOD_ERROR）；
    2. 全局 MethodRegistry（六 Baseline，R3 冻结不变）；
    3. 最小动态导入（cars.methods.<id>，仅白名单内方法；CARS 经此路径）。

    与 R4 worker fallback 行为保持一致：未注册且 import 失败 -> KeyError。
    """
    if not isinstance(method_id, str) or method_id not in METHOD_WHITELIST:
        raise KeyError(
            "method %r not in R5 whitelist; allowed=%s"
            % (method_id, sorted(METHOD_WHITELIST))
        )
    if registry_obj.has(method_id):
        return registry_obj.get(method_id, method_config)
    try:
        mod = importlib.import_module("cars.methods." + method_id)
    except ImportError as exc:
        raise KeyError(
            "method %r not registered; available=%s"
            % (method_id, registry_obj.available())
        ) from exc
    factory = getattr(mod, "build_method", None)
    if factory is None:
        raise KeyError("method %r has no build_method" % (method_id,))
    return factory(method_config)


def normalize_decision(decision: Optional[Dict]) -> Optional[Dict]:
    """将方法返回 decision 的 schema_version 归一化为当前正式版本（V2）。

    - decision=None（TIMEOUT/METHOD_ERROR）-> 返回 None（原样，不构造决策）；
    - schema_version in {V1, V2} -> 返回新 dict（schema_version 改写为 V2）；
      返回新对象，原 decision 不变（不可变适配）；
    - 其他 schema_version -> ValueError（明确错误，不静默兼容）。

    只改元数据标识；X/A/F 结构与数学语义不变（V1/V2 schedule_decision
    结构一致，仅 const 值不同）。
    """
    if decision is None:
        return None
    if not isinstance(decision, dict):
        raise ValueError("normalize_decision: decision must be a dict or None")
    sv = decision.get("schema_version")
    if sv not in ACCEPTED_DECISION_SCHEMA_VERSIONS:
        raise ValueError(
            "unsupported decision schema_version: %r (allowed=%s)"
            % (sv, sorted(ACCEPTED_DECISION_SCHEMA_VERSIONS))
        )
    if sv == CURRENT_DECISION_SCHEMA_VERSION:
        return decision
    normalized = dict(decision)
    normalized["schema_version"] = CURRENT_DECISION_SCHEMA_VERSION
    return normalized
