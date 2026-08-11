# -*- coding: utf-8 -*-
"""NFA-adapted 配置校验（TEST_ONLY_NOT_FORMAL 参数白名单）。

白名单（提示词 §五）：population_size, max_generations, beta_0, gamma,
position_bounds, method_seed, objective_evaluation_cap, soft_deadline_margin,
hard_timeout_seconds。配置键使用 *_max 上界命名（本阶段不调参，上界即实际值）。
"""

from __future__ import annotations

from typing import Dict

REQUIRED_KEYS = (
    "population_size_max",
    "max_generations_max",
    "beta_0",
    "gamma",
    "position_bounds",
    "method_seed",
    "objective_evaluation_cap_max",
    "hard_timeout_seconds",
)


def validate_config(config: Dict) -> Dict:
    """校验并归一化方法配置。返回内部规范配置 dict。"""
    if not isinstance(config, dict):
        raise ValueError("NFA config must be a dict")
    for key in REQUIRED_KEYS:
        if key not in config:
            raise ValueError("NFA config missing required key %r" % key)

    pop = config["population_size_max"]
    gen = config["max_generations_max"]
    cap = config["objective_evaluation_cap_max"]
    hard_timeout = config["hard_timeout_seconds"]
    method_seed = config["method_seed"]
    beta0 = config["beta_0"]
    gamma = config["gamma"]
    bounds = config["position_bounds"]

    if not isinstance(pop, int) or pop <= 0:
        raise ValueError("population_size_max must be a positive int")
    if not isinstance(gen, int) or gen <= 0:
        raise ValueError("max_generations_max must be a positive int")
    if not isinstance(cap, int) or cap <= 0:
        raise ValueError("objective_evaluation_cap_max must be a positive int")
    if not isinstance(method_seed, int) or method_seed < 0:
        raise ValueError("method_seed must be a non-negative int")
    if not isinstance(hard_timeout, (int, float)) or hard_timeout <= 0:
        raise ValueError("hard_timeout_seconds must be positive")
    if not isinstance(beta0, (int, float)) or not (0.0 <= beta0 <= 1.0):
        raise ValueError("beta_0 must be in [0,1]")
    if not isinstance(gamma, (int, float)) or gamma < 0:
        raise ValueError("gamma must be non-negative")
    if (
        not isinstance(bounds, (list, tuple))
        or len(bounds) != 2
        or not all(isinstance(v, (int, float)) for v in bounds)
        or bounds[0] >= bounds[1]
    ):
        raise ValueError("position_bounds must be [low, high] with low < high")

    margin = config.get("soft_deadline_margin")
    expected_margin = max(1.0, 0.1 * float(hard_timeout))
    if margin is not None:
        if not isinstance(margin, (int, float)) or abs(float(margin) - expected_margin) > 1e-9:
            raise ValueError(
                "soft_deadline_margin must equal max(1, 0.1*hard_timeout)=%s" % expected_margin
            )

    # E1 落实（2026-08-08 用户授权）：加权多目标权重（成功数/效用/可靠性）
    # 格式 [w1, w2, w3]，非负且和为 1；缺省 None = 原字典序目标
    weights = config.get("objective_weights")
    if weights is not None:
        if (
            not isinstance(weights, (list, tuple))
            or len(weights) != 3
            or not all(isinstance(v, (int, float)) and v >= 0.0 for v in weights)
        ):
            raise ValueError("objective_weights must be [w1, w2, w3] with w_i >= 0")
        total = float(sum(weights))
        if total <= 0.0 or abs(total - 1.0) > 1e-9:
            raise ValueError("objective_weights must sum to 1")

    sleep = config.get("_test_hook_sleep_seconds_per_evaluation", 0.0)
    if not isinstance(sleep, (int, float)) or sleep < 0:
        raise ValueError("_test_hook_sleep_seconds_per_evaluation must be non-negative")

    return {
        "population_size": int(pop),
        "max_generations": int(gen),
        "objective_evaluation_cap": int(cap),
        "method_seed": int(method_seed),
        "hard_timeout_seconds": float(hard_timeout),
        "beta_0": float(beta0),
        "gamma": float(gamma),
        "position_bounds": [float(bounds[0]), float(bounds[1])],
        "soft_deadline_margin": float(expected_margin),
        "objective_weights": None if weights is None else (float(weights[0]), float(weights[1]), float(weights[2])),
        "_test_hook_sleep_seconds_per_evaluation": float(sleep),
    }
