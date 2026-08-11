# -*- coding: utf-8 -*-
"""E4-EXACT tiny Scenario 构造辅助（确定性；E4-EXACT-1 测试与 validation 用）。

构造满足 CARS_ACTIVE_SCHEMA_V4 的完整 T0 Scenario（全连接可选）。
参数均为显式给定（确定性，不随机），保证复现。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

SCHEMA_VERSION = "CARS_ACTIVE_SCHEMA_V4"


def default_system_params() -> Dict:
    """V4 SystemParams（Contract V4 §7 冻结默认；仅结构）。"""
    return {
        "rcla_solver": {
            "rcla_mu_tol": 1.0e-9,
            "rcla_max_iters": 200,
            "rcla_mu_lo": 1.0e-12,
            "rcla_mu_hi": 1.0e12,
            "rcla_numeric_epsilon": 1.0e-12,
        },
        "numeric_epsilon": 1.0e-12,
    }


def make_scenario(
    scenario_id: str,
    task_specs: List[Dict],
    server_specs: List[Dict],
    link_matrix: Dict[Tuple[int, int], Optional[Dict]],
) -> Dict:
    """构造 T0 Scenario。

    task_specs[i] 字段（Task + Device 合并）：
      local_cpu_rate, local_failure_rate, switch_capacitance, tx_power_watts,
      data_bits, cpu_cycles, fragility, delay_weight, energy_weight,
      min_reliability, deadline_seconds
    server_specs[j] 字段：capacity_cycles_per_sec, nominal_failure_rate
    link_matrix[(i,j)]：{bandwidth_hz, channel_gain, noise_power, error_probability}
                       或 None（无链路）
    """
    n = len(task_specs)
    m = len(server_specs)

    tasks: List[Dict] = []
    devices: List[Dict] = []
    for i, spec in enumerate(task_specs):
        tasks.append(
            {
                "task_id": "t%d" % i,
                "device_id": "d%d" % i,
                "data_bits": spec["data_bits"],
                "cpu_cycles": spec["cpu_cycles"],
                "fragility": spec["fragility"],
                "delay_weight": spec["delay_weight"],
                "energy_weight": spec["energy_weight"],
                "deadline_seconds": spec["deadline_seconds"],
                "min_reliability": spec["min_reliability"],
            }
        )
        devices.append(
            {
                "device_id": "d%d" % i,
                "local_cpu_rate": spec["local_cpu_rate"],
                "local_failure_rate": spec["local_failure_rate"],
                "switch_capacitance": spec["switch_capacitance"],
                "tx_power_watts": spec["tx_power_watts"],
            }
        )

    servers: List[Dict] = []
    for j, spec in enumerate(server_specs):
        servers.append(
            {
                "server_id": "s%d" % j,
                "capacity_cycles_per_sec": spec["capacity_cycles_per_sec"],
                "nominal_failure_rate": spec["nominal_failure_rate"],
            }
        )

    links: List[Dict] = []
    link_id = 0
    for (i, j), spec in sorted(link_matrix.items()):
        if spec is None:
            continue
        links.append(
            {
                "link_id": "l%d" % link_id,
                "source_device_id": "d%d" % i,
                "target_server_id": "s%d" % j,
                "bandwidth_hz": spec["bandwidth_hz"],
                "channel_gain": spec["channel_gain"],
                "noise_power": spec["noise_power"],
                "error_probability": spec["error_probability"],
            }
        )
        link_id += 1

    return {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": scenario_id,
        "state_timepoint": "T0",
        "system_params": default_system_params(),
        "tasks": tasks,
        "devices": devices,
        "servers": servers,
        "links": links,
    }


def default_link_spec(error_probability: float = 0.01) -> Dict:
    """默认链路参数（高带宽、强信道、低误码 -> R_tx = 1-p_err in (0,1)）。"""
    return {
        "bandwidth_hz": 2.0e9,
        "channel_gain": 1.0,
        "noise_power": 1.0,
        "error_probability": error_probability,
    }
