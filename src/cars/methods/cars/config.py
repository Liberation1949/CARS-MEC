# -*- coding: utf-8 -*-
"""CARS 方法配置校验（CR-CARS-PROMOTION-E1：正式 CARS = AADA → RCLA，无 Repair）。

V4 语义（Contract V4；正文 V-A.4 Table V-1）：
- 正式 CARS 方法配置仅允许运行协议字段（method_id/config_label/scenario_config/
  eps_cmp/method_seed/hard_timeout_seconds/_test_hook_sleep_seconds）与
  AADA/RCLA 字段（aada_variant / allocation_mode / rcla_mu_tol / rcla_max_iters /
  rcla_mu_lo / rcla_mu_hi / rcla_numeric_epsilon）；
- 确定性求解器参数（rcla_*）为冻结默认值，非调参旋钮（Contract V4 §7；
  与候选 candidate_v1.yaml 一致）；
- V4 禁止 CALA/Repair 参数（kappa_R/kappa_D/cala_weights/repair_budget/
  repair_tolerances）与旧 RUAD 字段（ruad_gamma 等）——CARS 无 CALA/Repair 层，
  无混合权重；旧字段显式拒绝，禁止静默兼容（Schema V4）。

CR-RUAD-S2 历史：RUAD 无可调混合权重；ruad_gamma 已删除并加入 legacy 拒绝列表。
CR-R4-1 历史：旧三压力字段（eta_rho/eta_Q/eta_Z/s_Q/s_Z/rho_tilde/f_tilde_req）
同样被显式拒绝。

未知配置字段必须拒绝（R4 合同 §4 config_rule），不得静默忽略。
"""

from __future__ import annotations

from typing import Dict

METHOD_ID = "cars"

# 与 R2 冻结 eps_cmp 一致的默认值（evaluator_contract.yaml §5）
DEFAULT_EPS_CMP = 1.0e-9

# RCLA 确定性求解器冻结默认（Contract V4 §7；与候选 candidate_v1.yaml 一致；
# active-set 解法不使用 mu_tol/mu_lo/mu_hi，以 eps_cmp 为容差）
DEFAULT_RCLA_MU_TOL = 1.0e-9
DEFAULT_RCLA_MAX_ITERS = 200
DEFAULT_RCLA_MU_LO = 1.0e-12
DEFAULT_RCLA_MU_HI = 1.0e12
DEFAULT_RCLA_NUMERIC_EPS = 1.0e-12

# E3-V2 变体白名单（正文 VI-F.1 / 用户 2026-08-09 设计；单一变化原则）
AADA_VARIANTS = frozenset(
    {"full", "no_rescue", "rescue_only", "no_alloc_aware", "no_utility_gate"}
)
ALLOCATION_MODES = frozenset({"rcla", "ordinary_la"})

_ALLOWED_KEYS = {
    "method_id",
    "config_label",
    "scenario_config",
    "eps_cmp",
    "method_seed",
    "hard_timeout_seconds",
    "_test_hook_sleep_seconds",  # 仅测试钩子（非参数预算成员；默认 0，仅 timeout 注入测试使用）
    "aada_variant",      # full | no_rescue | rescue_only | no_alloc_aware | no_utility_gate（默认 full）
    "allocation_mode",   # rcla（默认） | ordinary_la（fixed-assignment 对照）
    "rcla_mu_tol",
    "rcla_max_iters",
    "rcla_mu_lo",
    "rcla_mu_hi",
    "rcla_numeric_epsilon",
}

# 正式 CARS 配置禁止的旧字段（顶层容器 + 嵌套字段名）
# - CR-R4-1/CR-RUAD-S2：旧三压力与 ruad_gamma（Schema V3 forbidden）；
# - CR-CARS-PROMOTION-E1：V4 另禁 CALA/Repair 参数（CARS=AADA→RCLA，无 CALA/Repair）。
_LEGACY_RUAD_PARAM_KEYS = (
    "ruad_pressure_weights",
    "ruad_smoothing",
    "eta_rho",
    "eta_Q",
    "eta_Z",
    "s_Q",
    "s_Z",
    "rho_tilde",
    "f_tilde_req",
    "ruad_gamma",
    "kappa_R",
    "kappa_D",
    "cala_weights",
    "repair_budget",
    "repair_tolerances",
)


def _collect_legacy_keys(obj, out):
    """递归收集 dict 中出现的旧字段键。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _LEGACY_RUAD_PARAM_KEYS:
                out.append(k)
            _collect_legacy_keys(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_legacy_keys(item, out)


def _positive_float(value, name: str, default: float) -> float:
    if value is None:
        return float(default)
    if not isinstance(value, (int, float)) or not value > 0.0:
        raise ValueError("%s must be a positive number" % name)
    return float(value)


def _positive_int(value, name: str, default: int) -> int:
    if value is None:
        return int(default)
    if not isinstance(value, int) or value <= 0:
        raise ValueError("%s must be a positive int" % name)
    return int(value)


def _validate_config(config: Dict) -> Dict:
    """校验并归一化 CARS 方法配置。未知字段 / 旧字段拒绝。"""
    if not isinstance(config, dict):
        raise ValueError("cars config must be a dict")

    legacy = []
    _collect_legacy_keys(config, legacy)
    legacy = sorted(set(legacy))
    if legacy:
        raise ValueError(
            "cars: legacy RUAD/CALA/Repair params rejected by CR-CARS-PROMOTION-E1 "
            "(CARS=AADA→RCLA, no CALA/Repair): %s" % ", ".join(legacy)
        )

    unknown = sorted(set(config.keys()) - _ALLOWED_KEYS)
    if unknown:
        raise ValueError("cars config unknown fields: %s" % ", ".join(unknown))

    method_id = config.get("method_id")
    if method_id != METHOD_ID:
        raise ValueError("method_id mismatch: %r" % (method_id,))

    eps = config.get("eps_cmp", DEFAULT_EPS_CMP)
    if not isinstance(eps, (int, float)) or not (0.0 < eps < 1.0):
        raise ValueError("eps_cmp must be in (0,1)")

    seed = config.get("method_seed", 0)
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("method_seed must be a non-negative int")

    hard = config.get("hard_timeout_seconds", 10.0)
    if not isinstance(hard, (int, float)) or hard <= 0:
        raise ValueError("hard_timeout_seconds must be positive")

    hook = config.get("_test_hook_sleep_seconds", 0.0)
    if not isinstance(hook, (int, float)) or hook < 0:
        raise ValueError("_test_hook_sleep_seconds must be >= 0")

    variant = config.get("aada_variant", "full")
    if variant not in AADA_VARIANTS:
        raise ValueError(
            "cars aada_variant must be one of %s, got %r"
            % (sorted(AADA_VARIANTS), variant)
        )
    alloc_mode = config.get("allocation_mode", "rcla")
    if alloc_mode not in ALLOCATION_MODES:
        raise ValueError(
            "cars allocation_mode must be one of %s, got %r"
            % (sorted(ALLOCATION_MODES), alloc_mode)
        )

    return {
        "method_id": METHOD_ID,
        "config_label": config.get("config_label", ""),
        "scenario_config": config.get("scenario_config", ""),
        "eps_cmp": float(eps),
        "method_seed": int(seed),
        "hard_timeout_seconds": float(hard),
        "_test_hook_sleep_seconds": float(hook),
        "aada_variant": str(variant),
        "allocation_mode": str(alloc_mode),
        "rcla_mu_tol": _positive_float(config.get("rcla_mu_tol"), "rcla_mu_tol", DEFAULT_RCLA_MU_TOL),
        "rcla_max_iters": _positive_int(config.get("rcla_max_iters"), "rcla_max_iters", DEFAULT_RCLA_MAX_ITERS),
        "rcla_mu_lo": _positive_float(config.get("rcla_mu_lo"), "rcla_mu_lo", DEFAULT_RCLA_MU_LO),
        "rcla_mu_hi": _positive_float(config.get("rcla_mu_hi"), "rcla_mu_hi", DEFAULT_RCLA_MU_HI),
        "rcla_numeric_epsilon": _positive_float(
            config.get("rcla_numeric_epsilon"), "rcla_numeric_epsilon", DEFAULT_RCLA_NUMERIC_EPS
        ),
    }


def rcla_cfg_from_config(config: Dict) -> Dict:
    """从归一化配置构造 RCLA 求解器配置（Contract V4 §7；与候选 candidate_v1.yaml 一致）。"""
    return {
        "rcla_mu_tol": config["rcla_mu_tol"],
        "rcla_max_iters": config["rcla_max_iters"],
        "rcla_mu_lo": config["rcla_mu_lo"],
        "rcla_mu_hi": config["rcla_mu_hi"],
        "rcla_numeric_epsilon": config["rcla_numeric_epsilon"],
    }


def load_system_params(scenario: Dict) -> Dict:
    """LEGACY 兼容：读取 Scenario system_params 中的 RCLA 求解器参数（Schema V4）。

    CR-CARS-PROMOTION-E1 后，正式 CARS 的 RCLA 参数从**方法配置**读取
    （rcla_cfg_from_config，Contract V4 §7）；本函数仅供旧模块/历史测试
    import 兼容（V4 SystemParams = rcla_solver + numeric_epsilon）。
    返回 {rcla_* , numeric_epsilon}（与候选 candidate_v1.yaml 一致）。
    """
    sp = scenario.get("system_params")
    if not isinstance(sp, dict):
        raise ValueError("cars: scenario missing system_params dict")

    legacy = []
    _collect_legacy_keys(sp, legacy)
    legacy = sorted(set(legacy))
    if legacy:
        raise ValueError(
            "cars: legacy RUAD/CALA/Repair params rejected by CR-CARS-PROMOTION-E1 "
            "(CARS=AADA→RCLA, no CALA/Repair): %s" % ", ".join(legacy)
        )

    solver = sp.get("rcla_solver")
    if not isinstance(solver, dict):
        raise ValueError("cars: system_params missing rcla_solver (Schema V4)")

    numeric_epsilon = float(sp.get("numeric_epsilon", DEFAULT_RCLA_NUMERIC_EPS))
    if not numeric_epsilon > 0.0:
        raise ValueError("cars: numeric_epsilon must be > 0")

    return {
        "rcla_mu_tol": _positive_float(solver.get("rcla_mu_tol"), "rcla_mu_tol", DEFAULT_RCLA_MU_TOL),
        "rcla_max_iters": _positive_int(solver.get("rcla_max_iters"), "rcla_max_iters", DEFAULT_RCLA_MAX_ITERS),
        "rcla_mu_lo": _positive_float(solver.get("rcla_mu_lo"), "rcla_mu_lo", DEFAULT_RCLA_MU_LO),
        "rcla_mu_hi": _positive_float(solver.get("rcla_mu_hi"), "rcla_mu_hi", DEFAULT_RCLA_MU_HI),
        "rcla_numeric_epsilon": _positive_float(
            solver.get("rcla_numeric_epsilon"), "rcla_numeric_epsilon", DEFAULT_RCLA_NUMERIC_EPS
        ),
        "numeric_epsilon": numeric_epsilon,
    }
