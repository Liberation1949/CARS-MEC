# -*- coding: utf-8 -*-
"""CR-ALG-REDESIGN-1 测试辅助：显式微型场景构造器。

构造 explicit 模式场景（确定性，无随机），供 AADA/RCLA 单元测试与集成测试
使用。所有物理量由 R2 公共 DerivedState / physical_models 计算（测试只提供
输入参数，不重复实现公式）。
"""

from __future__ import annotations

from typing import Dict, List

SYSTEM_PARAMS_V3 = {
    "cala_weights": {"kappa_R": 0.5},
    "repair_budget": {"L_max": 10, "C_max": 100, "K_edge": 2, "K_swap": 2},
    "repair_tolerances": {"epsilon_R": 1.0e-9, "epsilon_U": 1.0e-9},
    "numeric_epsilon": 1.0e-12,
}


def build_scenario(
    tasks: List[Dict],
    devices: List[Dict],
    servers: List[Dict],
    links: List[Dict],
    scenario_id: str = "cr_alg_redesign_tiny",
) -> Dict:
    """构造 explicit 模式场景配置（materialize 前）。"""
    return {
        "scenario_id": scenario_id,
        "seed": 0,
        "mode": "explicit",
        "system_params": dict(SYSTEM_PARAMS_V3),
        "tasks": tasks,
        "devices": devices,
        "servers": servers,
        "links": links,
    }


def make_task(
    task_id: str,
    device_id: str,
    *,
    cpu_cycles: float,
    fragility: float,
    delay_weight: float,
    min_reliability: float,
    data_bits: float = 1000.0,
    deadline_seconds: float = 1000.0,
) -> Dict:
    """任务字典（无 deadline 模型：deadline 占位，逻辑不使用）。"""
    return {
        "task_id": task_id,
        "device_id": device_id,
        "data_bits": data_bits,
        "cpu_cycles": cpu_cycles,
        "fragility": fragility,
        "delay_weight": delay_weight,
        "energy_weight": round(1.0 - delay_weight, 6),
        "deadline_seconds": deadline_seconds,
        "min_reliability": min_reliability,
    }


def make_device(
    device_id: str,
    *,
    local_cpu_rate: float,
    local_failure_rate: float = 0.002,
    switch_capacitance: float = 1.0,
    tx_power_watts: float = 0.5,
) -> Dict:
    return {
        "device_id": device_id,
        "local_cpu_rate": local_cpu_rate,
        "local_failure_rate": local_failure_rate,
        "switch_capacitance": switch_capacitance,
        "tx_power_watts": tx_power_watts,
    }


def make_server(
    server_id: str,
    *,
    capacity_cycles_per_sec: float,
    nominal_failure_rate: float,
) -> Dict:
    return {
        "server_id": server_id,
        "capacity_cycles_per_sec": capacity_cycles_per_sec,
        "nominal_failure_rate": nominal_failure_rate,
    }


def make_link(
    link_id: str,
    source_device_id: str,
    target_server_id: str,
    *,
    bandwidth_hz: float = 1.0e6,
    channel_gain: float = 1.0e-9,
    noise_power: float = 1.0e-10,
    error_probability: float = 0.01,
) -> Dict:
    return {
        "link_id": link_id,
        "source_device_id": source_device_id,
        "target_server_id": target_server_id,
        "bandwidth_hz": bandwidth_hz,
        "channel_gain": channel_gain,
        "noise_power": noise_power,
        "error_probability": error_probability,
    }


def materialize_scenario(cfg: Dict) -> Dict:
    """物化场景（加 schema_version/state_timepoint 等）。"""
    from cars.simulator.scenario_materializer import materialize

    return materialize(cfg)


def derived_state(scenario: Dict):
    """构造 DerivedState。"""
    from cars.simulator.derived_state import DerivedState

    return DerivedState(scenario)
