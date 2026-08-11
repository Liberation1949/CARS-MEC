# -*- coding: utf-8 -*-
"""E1-V2 环境生成器（E1-V2-0：Environment Calibration and Freeze）。

结构继承 E1_ENVIRONMENT_V1 / E3-V2（无 deadline 模型，已验证可辨识）：
- M=8 全连接；任务 c 三带 {2000/5000/12000} (0.4/0.4/0.2)；设备 f_loc 两档
  {800/1200} (0.5/0.5)；服务器 F_j=10000·(1+0.3·(j mod 3))·s_F；
- ν profile（E1-V2-0 校准自由度之一）：
    V-MILD  = {0,6,12}  (0.4/0.3/0.3)
    V-MEDIUM= {0,8,16}  (0.4/0.3/0.3)   （= E1_ENVIRONMENT_V1 默认）
    V-HIGH  = {0,10,20} (0.4/0.3/0.3)
- s_F（E1-V2-0 校准自由度之二）：总计算容量缩放 ∈ {0.80, 1.00, 1.20}；
  仅缩放服务器容量 F_j（唯一允许改变的 capacity quantity）；
- λ_j∈U[0.001,0.003]（固定名义故障率；不随负载/环境校准改变）；λ_loc=0.002；
- R_min∈U[0.85,0.95]；无 deadline（deadline_seconds 占位，逻辑不使用）；
- system_params：Schema V4（rcla_solver + numeric_epsilon；无 cala/repair）。

嵌套生成（用户冻结）：seed 一次性生成 Gamma_200（确定性 RNG(seed)；服务器
参数在任务后抽取一次，对全部 N 前缀固定）；任意 N<=200 用 prefix_scenario
（deterministic nested prefix）。增加 N 表示增加任务而非替换实例。

用法：
  python scripts/reproduce/e1_v2/build_e1_v2_environment.py --seed 201 --n-max 200 \
      --s-f 1.0 --fragility-profile MEDIUM --out-dir DIR
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 结构参数（继承 E1_ENVIRONMENT_V1 定稿；E1-V2 N 上限 200）
M_DEFAULT = 8
N_MAX_DEFAULT = 200
COMPUTE_SCALE = 1.0
COMPUTE_TIERS_DEFAULT = [(2000, 0.4), (5000, 0.4), (12000, 0.2)]
FRAGILITY_TIERS_DEFAULT = [(0.0, 0.4), (8.0, 0.3), (16.0, 0.3)]
DEVICE_TIERS_DEFAULT = [(800, 0.5), (1200, 0.5)]
SERVER_BASE_DEFAULT = 10000

# E1-V2-0 校准自由度：任务脆弱性强度 profile（白名单冻结；E1-V2-0 合同 §3.2）
FRAGILITY_PROFILES = {
    "MILD": [(0.0, 0.4), (6.0, 0.3), (12.0, 0.3)],
    "MEDIUM": [(0.0, 0.4), (8.0, 0.3), (16.0, 0.3)],
    "HIGH": [(0.0, 0.4), (10.0, 0.3), (20.0, 0.3)],
}
# 允许的总计算容量缩放（白名单冻结；E1-V2-0 合同 §3.2）
ALLOWED_S_F = (0.80, 1.00, 1.20)
LAMBDA_LOC_DEFAULT = 0.002
LAMBDA_J_LO_DEFAULT = 0.001
LAMBDA_J_HI_DEFAULT = 0.003
R_MIN_LO_DEFAULT = 0.85
R_MIN_HI_DEFAULT = 0.95
DEADLINE_PLACEHOLDER = 1000.0  # 无 deadline：占位（字段兼容，逻辑不用）

# Schema V4 SystemParams（Contract V4 §7；无 cala/repair 参数）
SYSTEM_PARAMS_V4 = {
    "rcla_solver": {
        "rcla_mu_tol": 1.0e-9,
        "rcla_max_iters": 200,
        "rcla_mu_lo": 1.0e-12,
        "rcla_mu_hi": 1.0e12,
        "rcla_numeric_epsilon": 1.0e-12,
    },
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


def build_e1_v2_environment(
    seed: int,
    n_max: int = N_MAX_DEFAULT,
    m: int = M_DEFAULT,
    compute_tiers=COMPUTE_TIERS_DEFAULT,
    fragility_profile: str = "MEDIUM",
    device_tiers=DEVICE_TIERS_DEFAULT,
    s_f: float = 1.00,
    server_base: float = SERVER_BASE_DEFAULT,
    lambda_loc: float = LAMBDA_LOC_DEFAULT,
    lambda_j_lo: float = LAMBDA_J_LO_DEFAULT,
    lambda_j_hi: float = LAMBDA_J_HI_DEFAULT,
    r_min_lo: float = R_MIN_LO_DEFAULT,
    r_min_hi: float = R_MIN_HI_DEFAULT,
    compute_scale: float = COMPUTE_SCALE,
    deadline_placeholder: float = DEADLINE_PLACEHOLDER,
) -> dict:
    """生成 Gamma_{n_max}（无 deadline；确定性 RNG(seed)；前缀一致）。

    E1-V2-0 校准自由度（白名单冻结，E1-V2-0 合同 §3.2）：
    - s_f ∈ {0.80, 1.00, 1.20}：总计算容量缩放（仅缩放服务器 F_j）；
    - fragility_profile ∈ {"MILD", "MEDIUM", "HIGH"}：任务脆弱性强度。
    其余环境参数固定（M/拓扑/c 三带/f_loc/R_min/λ_j/无线模型/无 deadline）。
    """
    if n_max <= 0:
        raise ValueError("n_max must be positive")
    if fragility_profile not in FRAGILITY_PROFILES:
        raise ValueError(
            "fragility_profile must be one of %s, got %r"
            % (sorted(FRAGILITY_PROFILES), fragility_profile)
        )
    if s_f not in ALLOWED_S_F:
        raise ValueError(
            "s_f must be in the E1-V2-0 whitelist %s, got %r"
            % (sorted(ALLOWED_S_F), s_f)
        )
    fragility_tiers = FRAGILITY_PROFILES[fragility_profile]
    rng = random.Random(seed)
    tasks, devices, servers, links = [], [], [], []
    # 服务器先行抽取（只依赖 seed 与 s_f，不随 n_max 变——paired 结构干净；
    # 仅容量乘 s_f，λ_j 保持不变）
    for j in range(m):
        servers.append({
            "server_id": "s%d" % (j + 1),
            "capacity_cycles_per_sec": int(round(server_base * (1.0 + 0.3 * (j % 3)) * s_f)),
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
        "scenario_id": "e1v2_sf%s_v%s_n%d_m%d_seed%d" % (
            ("%.2f" % s_f).rstrip("0").rstrip("."), fragility_profile, n_max, m, seed),
        "seed": seed,
        "mode": "explicit",
        "s_f": float(s_f),
        "fragility_profile": fragility_profile,
        "system_params": {k: v for k, v in SYSTEM_PARAMS_V4.items()},
        "tasks": tasks,
        "devices": devices,
        "servers": servers,
        "links": links,
    }


# （materializer 读取 cfg["mode"]；显式 explicit 模式）


def prefix_scenario(cfg: dict, n: int) -> dict:
    """取前 n 个任务/设备/链路（deterministic prefix；服务器固定；嵌套一致）。"""
    assert n <= len(cfg["tasks"]) and n > 0
    out = json.loads(json.dumps(cfg))
    out["scenario_id"] = "e1v2_n%d_m%d_scale%s_seed%d" % (
        n, len(cfg["servers"]), COMPUTE_SCALE, cfg["seed"])
    out["tasks"] = cfg["tasks"][:n]
    out["devices"] = cfg["devices"][:n]
    out["links"] = cfg["links"][: n * len(cfg["servers"])]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="E1-V2 环境生成器（N_max=200，前缀一致）")
    ap.add_argument("--seed", type=int, default=201)
    ap.add_argument("--n-max", type=int, default=N_MAX_DEFAULT)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    cfg = build_e1_v2_environment(seed=args.seed, n_max=args.n_max)
    out_dir = args.out_dir or os.path.join(_PROJECT, "results", "e1_v2", "environments")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "e1v2_seed%d_n%d.json" % (args.seed, args.n_max))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    print("written:", path)
    print("N:", args.n_max, "| M:", len(cfg["servers"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
