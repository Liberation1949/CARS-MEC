# -*- coding: utf-8 -*-
"""E3-V2 无 deadline 三压力环境生成器（E3-0 冻结；AADA–RCLA 组件消融）。

背景（2026-08-09）：
- 新版 E3 = "AADA–RCLA 组件消融与机制验证"（用户 2026-08-09 设计；正文 VI-F.1
  已登记理论—实验映射）。旧 E3 preset（RUAD/CALA/Repair 服务）不再适用；
- 环境三压力档（用户设计；Pilot 只允许按"机制是否被触发"选环境，不能按
  "Full 是否赢最多"）：
    Low        本地成功多、RCLA floor 大多不激活 -> 验证 RCLA→LA 退化性质；
    Transition local-success 与 local-failure 混合，Phase-1/2 都真正触发
               -> 主消融场景；
    High       rescue 任务多、(G_j/F_j) 较高、floor 大量激活，但系统尚未
               完全不可服务 -> AADA/RCLA stress test。

结构继承 E1_ENVIRONMENT_V1（无 deadline 模型，已验证可辨识）：
- M=8 全连接；任务 c 三带 {2000/5000/12000} (0.4/0.4/0.2)；设备 f_loc 两档
  {800/1200} (0.5/0.5)；服务器 F_j=10000·(1+0.3·(j mod 3))；
- ν∈{0:0.4, 8:0.3, 16:0.3}（可靠性成为有效压力源；本地不可行 21-35%）；
- λ_j∈U[0.001,0.003]（与本地 λ_loc=0.002 相当/略低，卸载有真实可靠性收益）；
- R_min∈U[0.85,0.95]；无 deadline（deadline_seconds 占位，逻辑不使用）；
- system_params 只 kappa_R（无 deadline 模型）。

三档压力通过 N 控制（前缀一致性；服务器固定）。N 值为候选起点，E3-1 pilot
按机制触发标准（见 configs/e3_v2/e3_v2_environment_definition.yaml）确认后
冻结为正式三档。

用法：
  python scripts/reproduce/e3_v2/build_e3_v2_environment.py --seed 201 --pressure high --out-dir DIR
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_PROJECT, "src"))

# ---------------------------------------------------------------------------
# E3-V2 三压力档 N 候选（前缀一致性；正式值待 E3-1 pilot 按机制触发标准确认）
# ---------------------------------------------------------------------------
PRESSURE_N_CANDIDATE = {
    "low": 20,
    "transition": 80,
    "high": 150,
}
PRESSURE_ORDER = ["low", "transition", "high"]

# 结构参数（继承 E1_ENVIRONMENT_V1 定稿）
M_DEFAULT = 8
N_MAX_DEFAULT = 250
COMPUTE_SCALE = 1.0
COMPUTE_TIERS_DEFAULT = [(2000, 0.4), (5000, 0.4), (12000, 0.2)]
FRAGILITY_TIERS_DEFAULT = [(0.0, 0.4), (8.0, 0.3), (16.0, 0.3)]
DEVICE_TIERS_DEFAULT = [(800, 0.5), (1200, 0.5)]
SERVER_BASE_DEFAULT = 10000
LAMBDA_LOC_DEFAULT = 0.002
LAMBDA_J_LO_DEFAULT = 0.001
LAMBDA_J_HI_DEFAULT = 0.003
R_MIN_LO_DEFAULT = 0.85
R_MIN_HI_DEFAULT = 0.95
DEADLINE_PLACEHOLDER = 1000.0  # 无 deadline：占位（字段兼容，逻辑不用）

SYSTEM_PARAMS_V3 = {
    "cala_weights": {"kappa_R": 0.5},
    "repair_budget": {"L_max": 10, "C_max": 100, "K_edge": 2, "K_swap": 2},
    "repair_tolerances": {"epsilon_R": 1.0e-9, "epsilon_U": 1.0e-9},
    "numeric_epsilon": 1.0e-12,
}


def _weighted_choice(rng, tiers):
    r = rng.random()
    acc = 0.0
    for val, w in tiers:
        acc += w
        if r < acc:
            return val
    return tiers[-1][0]


def build_e3_v2_environment(
    seed: int,
    n_max: int = N_MAX_DEFAULT,
    pressure: str = "transition",
    m: int = M_DEFAULT,
    compute_tiers=COMPUTE_TIERS_DEFAULT,
    fragility_tiers=FRAGILITY_TIERS_DEFAULT,
    device_tiers=DEVICE_TIERS_DEFAULT,
    server_base: float = SERVER_BASE_DEFAULT,
    lambda_loc: float = LAMBDA_LOC_DEFAULT,
    lambda_j_lo: float = LAMBDA_J_LO_DEFAULT,
    lambda_j_hi: float = LAMBDA_J_HI_DEFAULT,
    r_min_lo: float = R_MIN_LO_DEFAULT,
    r_min_hi: float = R_MIN_HI_DEFAULT,
    compute_scale: float = COMPUTE_SCALE,
    deadline_placeholder: float = DEADLINE_PLACEHOLDER,
) -> dict:
    """生成 Γ_{n_max}（无 deadline 模型；确定性 RNG(seed)；前缀一致性保证）。

    pressure 仅用于 scenario_id / 语义标记，不改变生成规则（同一 seed 同 N
    的实例与 pressure 无关——保证三档共享同前缀、可 paired）。
    """
    if pressure not in PRESSURE_N_CANDIDATE:
        raise ValueError("pressure must be one of %s, got %r" % (PRESSURE_ORDER, pressure))
    rng = random.Random(seed)
    tasks, devices, servers, links = [], [], [], []
    # 服务器先行抽取（只依赖 seed，不随 n_max 变——保证三压力档共享同一
    # 服务器集合，paired 结构干净；E3-V2 生成器冻结语义）
    for j in range(m):
        servers.append({
            "server_id": "s%d" % (j + 1),
            "capacity_cycles_per_sec": int(round(server_base * (1.0 + 0.3 * (j % 3)))),
            "nominal_failure_rate": round(rng.uniform(lambda_j_lo, lambda_j_hi), 4),
        })
    for i in range(n_max):
        fragility = _weighted_choice(rng, fragility_tiers)
        alpha = round(rng.uniform(0.5, 0.8), 2)
        cpu_cycles = _weighted_choice(rng, compute_tiers)
        local_rate = _weighted_choice(rng, device_tiers)
        tasks.append({
            "task_id": "t%d" % (i + 1),
            "device_id": "d%d" % (i + 1),
            "data_bits": 1000,
            "cpu_cycles": int(round(cpu_cycles * compute_scale)),
            "fragility": fragility,
            "delay_weight": alpha,
            "energy_weight": round(1.0 - alpha, 2),
            "deadline_seconds": deadline_placeholder,
            "min_reliability": round(rng.uniform(r_min_lo, r_min_hi), 3),
        })
        devices.append({
            "device_id": "d%d" % (i + 1),
            "local_cpu_rate": int(round(local_rate)),
            "local_failure_rate": lambda_loc,
            "switch_capacitance": 1.0,
            "tx_power_watts": 0.5,
        })
    link_id = 0
    for i in range(n_max):
        for j in range(m):
            link_id += 1
            links.append({
                "link_id": "l%d" % link_id,
                "source_device_id": "d%d" % (i + 1),
                "target_server_id": "s%d" % (j + 1),
                "bandwidth_hz": 1000000,
                "channel_gain": 1.0e-9,
                "noise_power": 1.0e-10,
                "error_probability": 0.01,
            })
    return {
        "scenario_id": "e3v2_%s_n%d_m%d_s%s_seed%d" % (
            pressure, n_max, m, compute_scale, seed),
        "seed": seed,
        "mode": "explicit",
        "pressure": pressure,
        "system_params": dict(SYSTEM_PARAMS_V3),
        "tasks": tasks,
        "devices": devices,
        "servers": servers,
        "links": links,
    }


def prefix_scenario(cfg: dict, n: int) -> dict:
    """取前 n 个任务/设备/链路（deterministic prefix；服务器固定）。"""
    assert n <= len(cfg["tasks"]) and n > 0
    out = json.loads(json.dumps(cfg))
    out["scenario_id"] = "e3v2_%s_n%d_m%d_s%s_seed%d" % (
        cfg.get("pressure", "transition"), n, len(cfg["servers"]),
        COMPUTE_SCALE, cfg["seed"])
    out["tasks"] = cfg["tasks"][:n]
    out["devices"] = cfg["devices"][:n]
    out["links"] = cfg["links"][: n * len(cfg["servers"])]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="E3-V2 三压力环境生成器（E3-0 冻结）")
    ap.add_argument("--seed", type=int, default=201)
    ap.add_argument("--pressure", choices=PRESSURE_ORDER, default="transition")
    ap.add_argument("--n-max", type=int, default=None,
                    help="默认取该 pressure 的候选 N（低/中/高 = 20/80/150）")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    n_max = args.n_max or PRESSURE_N_CANDIDATE[args.pressure]
    cfg = build_e3_v2_environment(seed=args.seed, n_max=n_max, pressure=args.pressure)

    out_dir = args.out_dir or os.path.join(_PROJECT, "results", "e3_v2", "environments")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "e3v2_%s_seed%d_n%d.json" % (args.pressure, args.seed, n_max))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    print("written:", path)
    print("pressure:", args.pressure, "| N:", n_max)
    return 0


if __name__ == "__main__":
    sys.exit(main())
