# -*- coding: utf-8 -*-
"""Promoted CARS == Candidate 语义等价验证（CR-CARS-PROMOTION-E1 AC-4）。

验证目标：正式 CARS（src/cars/methods/cars/，method_id="cars"，AADA→RCLA
委托候选实现）与 E0-V2/E3-V2 使用的候选（cars_aada_rcla_candidate）在同一
(scenario, derived) 输入下产生一致的 X/A/F 决策与 pre_evaluation_xaf_hash。

- 场景：E3-V2 正式环境生成器（seed 401-410 TRANSITION 中的代表点）——与
  E3-V2-2 正式结果完全相同的场景来源；
- 正式 cars：CarsMethod（build_method 路径；method_id="cars"）；
- 候选：CarsMethod（method_id="cars_aada_rcla_candidate"）；
- 比较：offloading_decision / assignment_matrix / resource_allocation 逐值一致
  + pre_evaluation_xaf_hash 一致；
- 正式 cars decision.schema_version = CARS_ACTIVE_SCHEMA_V4（元数据；X/A/F 与
  候选一致）。

用法：python scripts/reproduce/e1_v2/check_promotion_equivalence.py
"""
from __future__ import annotations

import json
import os
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_PROJECT, "src"))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "reproduce", "e3_v2"))

from build_e3_v2_environment import build_e3_v2_environment  # noqa: E402
from cars.methods.cars.method import CarsMethod  # noqa: E402
from cars.methods.cars.method import CarsMethod  # noqa: E402
from cars.methods.protocol import MethodContext  # noqa: E402
from cars.simulator.derived_state import DerivedState  # noqa: E402
from cars.simulator.scenario_materializer import materialize  # noqa: E402

EPS = 1.0e-9
SEEDS = [401, 402, 403]
N_TRANSITION = 80
PRESSURE = "transition"


def _ctx(scen, derived, cfg, seed):
    return MethodContext(
        scenario=scen,
        derived=derived,
        config=cfg,
        method_seed=seed,
        soft_deadline_seconds=30.0,
        hard_timeout_seconds=30.0,
    )


def main() -> int:
    results = []
    all_ok = True
    for seed in SEEDS:
        cfg_env = build_e3_v2_environment(seed=seed, n_max=N_TRANSITION, pressure=PRESSURE)
        scen = materialize(cfg_env)
        derived = DerivedState(scen)

        cars_cfg = {
            "method_id": "cars",
            "config_label": "cars_promoted_v4",
            "scenario_config": "",
            "eps_cmp": EPS,
            "method_seed": 1,
            "hard_timeout_seconds": 30.0,
            "aada_variant": "full",
            "allocation_mode": "rcla",
        }
        cand_cfg = {
            "method_id": "cars_aada_rcla_candidate",
            "config_label": "candidate_v1",
            "scenario_config": "",
            "eps_cmp": EPS,
            "method_seed": 1,
            "hard_timeout_seconds": 30.0,
        }

        m_cars = CarsMethod(cars_cfg)
        m_cand = CarsMethod(cand_cfg)
        r_cars = m_cars.run(_ctx(scen, derived, cars_cfg, 1))
        r_cand = m_cand.run(_ctx(scen, derived, cand_cfg, 1))

        d_cars = r_cars.decision
        d_cand = r_cand.decision
        same = {
            "x": d_cars["offloading_decision"] == d_cand["offloading_decision"],
            "a": d_cars["assignment_matrix"] == d_cand["assignment_matrix"],
            "f": d_cars["resource_allocation"] == d_cand["resource_allocation"],
        }
        hash_cars = r_cars.diagnostics.get("pre_evaluation_xaf_hash")
        hash_cand = r_cand.diagnostics.get("pre_evaluation_xaf_hash")
        same["hash"] = hash_cars == hash_cand
        same["schema_version"] = d_cars["schema_version"]
        same["status"] = r_cars.method_status == "SUCCESS" and r_cand.method_status == "SUCCESS"
        ok = all(same[k] for k in ("x", "a", "f", "hash")) and same["status"]
        all_ok = all_ok and ok
        results.append({"seed": seed, "n": N_TRANSITION, "equivalent": ok, "details": same})
        print("seed=%d n=%d equivalent=%s" % (seed, N_TRANSITION, ok))

    out_path = os.path.join(
        _PROJECT, "results", "e1_v2", "promotion_equivalence.json"
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "stage": "CR-CARS-PROMOTION-E1",
                "check": "promoted_cars_vs_candidate_equivalence",
                "seeds": SEEDS,
                "n": N_TRANSITION,
                "pressure": PRESSURE,
                "all_equivalent": all_ok,
                "results": results,
            },
            fh,
            ensure_ascii=False,
            indent=2,
        )
    print("ALL_EQUIVALENT =", all_ok)
    print("written:", out_path)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
