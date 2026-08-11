# -*- coding: utf-8 -*-
"""JTORA-adapted 配置校验（TEST_ONLY_NOT_FORMAL 参数白名单）。

白名单（R3_jtora_adaptation_contract.yaml parameter_budget）：
max_outer_iterations, max_binary_search_iterations, absolute_tolerance,
relative_tolerance, improvement_factor_delta, method_seed,
soft_deadline_margin, hard_timeout_seconds。

说明：
- max_binary_search_iterations 为原文 UPA 二分（Algorithm 1）的测试预算上界；
  生产路径功率固定（场景输入），二分搜索不调用（binary_search_calls=0）；
- improvement_factor_delta 对应 Algorithm 2 的 (1+delta) 改进因子（原文未给
  数值，IMPLEMENTATION_SPEC_GAP，TEST_ONLY_NOT_FORMAL 默认 1e-6）；
- 方法无随机性，method_seed 仅用于复现记录。
"""

from __future__ import annotations

from typing import Dict

REQUIRED_KEYS = (
    "max_outer_iterations",
    "max_binary_search_iterations",
    "absolute_tolerance",
    "relative_tolerance",
    "improvement_factor_delta",
    "method_seed",
    "hard_timeout_seconds",
)


def validate_config(config: Dict) -> Dict:
    """校验并归一化方法配置。返回内部规范配置 dict。"""
    if not isinstance(config, dict):
        raise ValueError("JTORA config must be a dict")
    for key in REQUIRED_KEYS:
        if key not in config:
            raise ValueError("JTORA config missing required key %r" % key)

    outer = config["max_outer_iterations"]
    bis = config["max_binary_search_iterations"]
    atol = config["absolute_tolerance"]
    rtol = config["relative_tolerance"]
    delta = config["improvement_factor_delta"]
    method_seed = config["method_seed"]
    hard_timeout = config["hard_timeout_seconds"]

    if not isinstance(outer, int) or outer <= 0:
        raise ValueError("max_outer_iterations must be a positive int")
    if not isinstance(bis, int) or bis <= 0:
        raise ValueError("max_binary_search_iterations must be a positive int")
    if not isinstance(atol, (int, float)) or not (0.0 < atol < 1.0):
        raise ValueError("absolute_tolerance must be in (0,1)")
    if not isinstance(rtol, (int, float)) or not (0.0 < rtol < 1.0):
        raise ValueError("relative_tolerance must be in (0,1)")
    if not isinstance(delta, (int, float)) or not (0.0 <= delta < 1.0):
        raise ValueError("improvement_factor_delta must be in [0,1)")
    if not isinstance(method_seed, int) or method_seed < 0:
        raise ValueError("method_seed must be a non-negative int")
    if not isinstance(hard_timeout, (int, float)) or hard_timeout <= 0:
        raise ValueError("hard_timeout_seconds must be positive")

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
        "max_outer_iterations": int(outer),
        "max_binary_search_iterations": int(bis),
        "absolute_tolerance": float(atol),
        "relative_tolerance": float(rtol),
        "improvement_factor_delta": float(delta),
        "method_seed": int(method_seed),
        "hard_timeout_seconds": float(hard_timeout),
        "soft_deadline_margin": float(expected_margin),
        "_test_hook_sleep_seconds_per_evaluation": float(sleep),
    }
