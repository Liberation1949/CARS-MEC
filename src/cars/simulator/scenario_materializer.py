# -*- coding: utf-8 -*-
"""确定性场景物化器（R2 公共底座）。

职责（提示词 Step 3.1）：ScenarioConfig + seed -> 完整且 Schema-valid 的 Scenario。
- 同配置、同 seed 字节级稳定；
- ID、数组与候选边排序确定；
- 不使用全局随机状态（独立 random.Random(seed)）；
- 输入非法时返回明确错误；
- 不读取未来状态；
- 不处理真实 Trace。

模式：
- ``explicit``：直接使用配置中给定的 tasks/devices/servers/links（确定性，无随机）；
- ``sampled``：从配置 ``sampling`` 范围内的参数用 seed 确定性抽样生成。
"""

from __future__ import annotations

import json
import math
from typing import Dict

from cars.common.deterministic import make_rng, uniform

SCHEMA_VERSION = "CARS_ACTIVE_SCHEMA_V1"
STATE_TIMEPOINT = "T0"


def _check_range(name: str, low, high) -> None:
    if not (isinstance(low, (int, float)) and isinstance(high, (int, float))):
        raise ValueError("sampling range %s must be numeric" % name)
    if low > high:
        raise ValueError("sampling range %s: low > high" % name)


class MaterializeError(ValueError):
    """场景物化失败（配置非法或抽样生成非法）。"""


def _explicit_scenario(cfg: Dict) -> Dict:
    required = ("tasks", "devices", "servers")
    for key in required:
        if key not in cfg or not isinstance(cfg[key], list) or len(cfg[key]) == 0:
            raise MaterializeError("explicit scenario missing non-empty '%s'" % key)
    scenario_id = cfg.get("scenario_id")
    if not scenario_id:
        raise MaterializeError("explicit scenario missing scenario_id")
    return {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": scenario_id,
        "state_timepoint": STATE_TIMEPOINT,
        "system_params": cfg["system_params"],
        "tasks": cfg["tasks"],
        "devices": cfg["devices"],
        "servers": cfg["servers"],
        "links": cfg.get("links", []),
    }


def _sampled_scenario(cfg: Dict) -> Dict:
    scenario_id = cfg.get("scenario_id")
    if not scenario_id:
        raise MaterializeError("sampled scenario missing scenario_id")
    seed = cfg.get("seed")
    if not isinstance(seed, int) or seed < 0:
        raise MaterializeError("sampled scenario requires non-negative int seed")
    sampling = cfg.get("sampling")
    if not isinstance(sampling, dict):
        raise MaterializeError("sampled scenario requires 'sampling' config")

    rng = make_rng(seed)

    def draw(name, default=None):
        rng_ = sampling.get(name, default)
        if rng_ is None:
            raise MaterializeError("sampling missing range for '%s'" % name)
        low, high = rng_
        _check_range(name, low, high)
        return uniform(rng, low, high)

    n_tasks = sampling.get("n_tasks")
    n_servers = sampling.get("n_servers")
    if not isinstance(n_tasks, int) or n_tasks <= 0:
        raise MaterializeError("sampling requires positive int n_tasks")
    if not isinstance(n_servers, int) or n_servers <= 0:
        raise MaterializeError("sampling requires positive int n_servers")

    link_probability = sampling.get("link_probability", 1.0)
    if not (0.0 <= link_probability <= 1.0):
        raise MaterializeError("link_probability must be in [0,1]")

    system_params = sampling.get("system_params")
    if not isinstance(system_params, dict):
        raise MaterializeError("sampling requires 'system_params'")

    tasks = []
    devices = []
    for i in range(n_tasks):
        alpha = draw("delay_weight")
        alpha = min(max(alpha, 0.05), 0.95)  # 保证 beta = 1-alpha >= 0.05 > 0 且合法
        tasks.append(
            {
                "task_id": "t%d" % (i + 1),
                "device_id": "d%d" % (i + 1),
                "data_bits": draw("data_bits"),
                "cpu_cycles": draw("cpu_cycles"),
                "fragility": draw("fragility"),
                "delay_weight": alpha,
                "energy_weight": 1.0 - alpha,
                "deadline_seconds": draw("deadline_seconds"),
                "min_reliability": draw("min_reliability"),
            }
        )
        devices.append(
            {
                "device_id": "d%d" % (i + 1),
                "local_cpu_rate": draw("local_cpu_rate"),
                "local_failure_rate": draw("local_failure_rate"),
                "switch_capacitance": draw("switch_capacitance"),
                "tx_power_watts": draw("tx_power_watts"),
            }
        )

    servers = []
    for j in range(n_servers):
        servers.append(
            {
                "server_id": "s%d" % (j + 1),
                "capacity_cycles_per_sec": draw("capacity_cycles_per_sec"),
                "nominal_failure_rate": draw("nominal_failure_rate"),
            }
        )

    links = []
    link_id = 0
    for i in range(n_tasks):
        for j in range(n_servers):
            if rng.random() > link_probability:
                continue
            link_id += 1
            links.append(
                {
                    "link_id": "l%d" % link_id,
                    "source_device_id": "d%d" % (i + 1),
                    "target_server_id": "s%d" % (j + 1),
                    "bandwidth_hz": draw("bandwidth_hz"),
                    "channel_gain": draw("channel_gain"),
                    "noise_power": draw("noise_power"),
                    "error_probability": draw("error_probability"),
                }
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": scenario_id,
        "state_timepoint": STATE_TIMEPOINT,
        "system_params": system_params,
        "tasks": tasks,
        "devices": devices,
        "servers": servers,
        "links": links,
    }


def materialize(cfg: Dict) -> Dict:
    """从配置 dict 物化 Scenario（返回满足 scenario.schema.json 的 dict）。"""
    mode = cfg.get("mode")
    if mode == "explicit":
        return _explicit_scenario(cfg)
    if mode == "sampled":
        return _sampled_scenario(cfg)
    raise MaterializeError("unknown materializer mode: %r" % (mode,))


def materialize_from_file(path: str) -> Dict:
    """从 YAML/JSON 配置文件物化 Scenario。"""
    import os

    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if path.lower().endswith(".json"):
        import json as _json

        cfg = _json.loads(text)
    else:
        import yaml

        cfg = yaml.safe_load(text)
    return materialize(cfg)


def canonical_dumps(scenario: Dict) -> str:
    """确定性序列化（用于字节级复现比较；键排序保证稳定）。"""
    return json.dumps(scenario, sort_keys=True, separators=(",", ":"))
