# -*- coding: utf-8 -*-
"""E0-E3 全面验证：AADA 准入迁移（ell_R -> ell_succ/H_j）对 E0-E3 正式场景的影响。

关键论证：若全部正式场景 AADA 输出 zero_EDGE=0（无 fragility=0 任务被卸载到
EDGE），则 H_j == G_j（H_j 只比 G_j 多 #zero_EDGE*1.0），准入条件逐位等价，
AADA 决策与修改前完全一致 -> E0-E3 FORMAL_RESULTS_UNAFFECTED。

覆盖：
  E0-V2: seed 601-610 x N {20,80,200}
  E1-V2: seed 1101/1105/1108 x N {20,50,80,140,170,200}
  E2-V2: seed 2101/2102/2103 x cv_f {0.0,0.6,1.2}, N=170
  E3:    preset 场景 seed 201/202/203 (transition_high n100 m16 preset0.52)
"""
import io
import os
import sys

import yaml

ROOT = os.getcwd()
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "reproduce", "e0_v2"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "reproduce", "e1_v2"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "reproduce", "e2_v2"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "e3"))

from cars.simulator.scenario_materializer import materialize  # noqa: E402
from cars.simulator.derived_state import DerivedState  # noqa: E402
from cars.methods.cars.pipeline import run_aada_rcla_pipeline  # noqa: E402

cfg = yaml.safe_load(io.open("configs/cars_v4/cars_frozen_v4.yaml", encoding="utf-8"))
rcla_cfg = {k: cfg[k] for k in ["rcla_mu_tol", "rcla_max_iters", "rcla_mu_lo",
                                "rcla_mu_hi", "rcla_numeric_epsilon"] if k in cfg}


def run_aada_stat(sc):
    """跑 AADA+RCLA，返回 (zero_edges, n_edges, min_f, H_max, F_max)。"""
    derived = DerivedState(sc)
    res = run_aada_rcla_pipeline(sc, derived=derived, eps_cmp=1e-9, rcla_cfg=rcla_cfg)
    dec = res["decision"]
    X = dec["offloading_decision"]
    F = dec["resource_allocation"]
    pos = [F[i][j] for i in range(len(F)) for j in range(len(F[i])) if F[i][j] > 0]
    mp = min(pos) if pos else None
    n_edges = int(sum(X))
    zero_edges = 0
    for i in range(len(sc["tasks"])):
        if X[i] == 1 and sc["tasks"][i].get("fragility", 0) == 0:
            zero_edges += 1
    diag = res.get("diagnostics", {})
    G = diag.get("per_server_final_G", [])
    Fjs = [s["capacity_cycles_per_sec"] for s in sc["servers"]]
    return zero_edges, n_edges, mp, G, Fjs


def report(name, zero_edges, n_edges, mp, G, Fjs, issues):
    flag = "OK" if zero_edges == 0 else "!!zero_EDGE>0"
    if zero_edges > 0:
        issues.append(name)
    print(f"  {name}: EDGE={n_edges} zero_EDGE={zero_edges} min_f={mp if mp is None else round(mp,1)} {flag}")


def main():
    issues = []

    # ---- E0-V2 ----
    print("=== E0-V2 (seed 601-610 x N {20,80,200}) ===")
    from build_e0_v2_environment import build_e0_v2_super_scenario, e0_prefix_scenario  # noqa
    for seed in range(601, 611):
        super_cfg = build_e0_v2_super_scenario(seed)
        for n in (20, 80, 200):
            cfg_n = e0_prefix_scenario(super_cfg, n)
            sc = materialize(cfg_n)
            ze, ne, mp, G, Fjs = run_aada_stat(sc)
            report(f"E0V2 s{seed} N{n}", ze, ne, mp, G, Fjs, issues)

    # ---- E1-V2 ----
    print("=== E1-V2 (seed 1101/1105/1108 x N 扫描) ===")
    import build_e1_v2_environment as B  # noqa
    for seed in (1101, 1105, 1108):
        env = B.build_e1_v2_environment(seed=seed, n_max=200, m=8, s_f=1.0,
                                        fragility_profile="MEDIUM")
        for n in (20, 50, 80, 140, 170, 200):
            cfg_n = B.prefix_scenario(env, n)
            sc = materialize(cfg_n)
            ze, ne, mp, G, Fjs = run_aada_stat(sc)
            report(f"E1V2 s{seed} N{n}", ze, ne, mp, G, Fjs, issues)

    # ---- E2-V2 ----
    print("=== E2-V2 (seed 2101/2102/2103 x cv_f {0.0,0.6,1.2}, N=170) ===")
    from build_e2_v2_environment import build_e2_v2_environment, e2_prefix_scenario  # noqa
    for seed in (2101, 2102, 2103):
        for cv_f in (0.0, 0.6, 1.2):
            env = build_e2_v2_environment(seed=seed, cv_f_target=cv_f, n_max=170,
                                          m=8, s_f=1.0, fragility_profile="MEDIUM")
            cfg_n = e2_prefix_scenario(env["scenario_cfg"], 170)
            sc = materialize(cfg_n)
            ze, ne, mp, G, Fjs = run_aada_stat(sc)
            report(f"E2V2 s{seed} cvf{cv_f}", ze, ne, mp, G, Fjs, issues)

    # ---- E3 ----
    print("=== E3 (preset seed 201/202/203, n100 m16) ===")
    e3_root = os.path.join("configs", "e3", "preset")
    for seed in (201, 202, 203):
        p = os.path.join(e3_root, f"scenario_transition_high_n100_m16_seed{seed}_preset0.52.yaml")
        if not os.path.exists(p):
            print(f"  (skip missing {p})")
            continue
        cfg_e3 = yaml.safe_load(io.open(p, encoding="utf-8"))
        sc = materialize(cfg_e3)
        ze, ne, mp, G, Fjs = run_aada_stat(sc)
        report(f"E3 s{seed} preset", ze, ne, mp, G, Fjs, issues)

    print()
    if issues:
        print("发现 zero_EDGE>0 的场景（需进一步评估 H_j 影响）:", issues)
    else:
        print("全部场景 zero_EDGE=0 -> H_j==G_j -> AADA 准入迁移零影响 -> E0-E3 FORMAL_RESULTS_UNAFFECTED")


if __name__ == "__main__":
    main()
