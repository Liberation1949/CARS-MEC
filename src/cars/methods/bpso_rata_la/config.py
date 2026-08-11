# -*- coding: utf-8 -*-
"""BPSO-RATA-LA 配置校验（TEST_ONLY_NOT_FORMAL 参数白名单）。

白名单（R3_BPSO_RATA_LA_adaptation_contract.yaml parameter_budget）：
population_size_max, max_iterations_max, particle_evaluation_cap_max,
reliability_threshold, inertia_weight, cognitive_coefficient,
social_coefficient, method_seed, soft_deadline_margin, hard_timeout_seconds。

配置键使用 *_max 上界命名（本阶段不调参，上界即实际值）。
varrho/zeta1/zeta2 数值为测试默认（原文 Table II 为图片不可提取，
IMPLEMENTATION_SPEC_GAP；Warning）。
"""

from __future__ import annotations

from typing import Dict

REQUIRED_KEYS = (
    "population_size_max",
    "max_iterations_max",
    "particle_evaluation_cap_max",
    "reliability_threshold",
    "inertia_weight",
    "cognitive_coefficient",
    "social_coefficient",
    "method_seed",
    "hard_timeout_seconds",
)


def validate_config(config: Dict) -> Dict:
    """校验并归一化方法配置。返回内部规范配置 dict。"""
    if not isinstance(config, dict):
        raise ValueError("BPSO-RATA-LA config must be a dict")
    for key in REQUIRED_KEYS:
        if key not in config:
            raise ValueError("BPSO-RATA-LA config missing required key %r" % key)

    pop = config["population_size_max"]
    iters = config["max_iterations_max"]
    cap = config["particle_evaluation_cap_max"]
    hard_timeout = config["hard_timeout_seconds"]
    method_seed = config["method_seed"]
    r_th = config["reliability_threshold"]
    inertia = config["inertia_weight"]
    c1 = config["cognitive_coefficient"]
    c2 = config["social_coefficient"]

    if not isinstance(pop, int) or pop <= 0:
        raise ValueError("population_size_max must be a positive int")
    if not isinstance(iters, int) or iters <= 0:
        raise ValueError("max_iterations_max must be a positive int")
    if not isinstance(cap, int) or cap <= 0:
        raise ValueError("particle_evaluation_cap_max must be a positive int")
    if not isinstance(method_seed, int) or method_seed < 0:
        raise ValueError("method_seed must be a non-negative int")
    if not isinstance(hard_timeout, (int, float)) or hard_timeout <= 0:
        raise ValueError("hard_timeout_seconds must be positive")
    if not isinstance(r_th, (int, float)) or not (0.0 < r_th < 1.0):
        raise ValueError("reliability_threshold must be in (0,1)")
    if not isinstance(inertia, (int, float)) or not (0.0 <= inertia < 1.0):
        raise ValueError("inertia_weight must be in [0,1)")
    if not isinstance(c1, (int, float)) or c1 <= 0:
        raise ValueError("cognitive_coefficient must be positive")
    if not isinstance(c2, (int, float)) or c2 <= 0:
        raise ValueError("social_coefficient must be positive")

    margin = config.get("soft_deadline_margin")
    expected_margin = max(1.0, 0.1 * float(hard_timeout))
    if margin is not None:
        if not isinstance(margin, (int, float)) or abs(float(margin) - expected_margin) > 1e-9:
            raise ValueError(
                "soft_deadline_margin must equal max(1, 0.1*hard_timeout)=%s" % expected_margin
            )

    sleep = config.get("_test_hook_sleep_seconds_per_evaluation", 0.0)
    if not isinstance(sleep, (int, float)) or sleep < 0:
        raise ValueError("_test_hook_sleep_seconds_per_evaluation must be non-negative")

    return {
        "population_size": int(pop),
        "max_iterations": int(iters),
        "particle_evaluation_cap": int(cap),
        "reliability_threshold": float(r_th),
        "inertia_weight": float(inertia),
        "cognitive_coefficient": float(c1),
        "social_coefficient": float(c2),
        "method_seed": int(method_seed),
        "hard_timeout_seconds": float(hard_timeout),
        "soft_deadline_margin": float(expected_margin),
        "_test_hook_sleep_seconds_per_evaluation": float(sleep),
    }
