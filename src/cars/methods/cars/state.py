# -*- coding: utf-8 -*-
"""AADA+RCLA 候选决策前状态视图（CARS；只读）。

复用 R2 公共 DerivedState（task_local / link_state / server_state 均为 T0
决策前已确定量），不重复实现第二套物理模型，不读取未来状态。

候选所需量（全部来自冻结原语）：
- 任务基础量：a_i = alpha_i * f_i^loc（LA Theorem 3/Eq.25 分子代理）；
  s_i = sqrt(max(a_i, 0))；local success = b_loc（derived_state 冻结语义）；
- 边属性：ell_R_ij（F-16，reliability floor）、e_phy / e_rec（F-35/F-50）、
  R_tx / T_tx / E_tx（F-11/F-04/F-05）；
- 服务器：F_j、lambda_j。

本视图只做索引与薄封装，公式计算全部复用 DerivedState / physical_models /
evaluator.metrics 原语；构造后不修改 scenario/derived。
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

from cars.simulator import physical_models as pm

INF = pm.INF


class CandidateStateView:
    """AADA+RCLA 决策前状态视图（确定性，只读）。"""

    def __init__(self, scenario: Dict, derived) -> None:
        self.scenario = scenario
        self.derived = derived
        self.task_ids: List[str] = derived.task_ids
        self.server_ids: List[str] = derived.server_ids
        self.n = len(derived.task_ids)
        self.m = len(derived.server_ids)
        self._task_by_id = {t["task_id"]: t for t in scenario["tasks"]}
        self._device_by_id = {d["device_id"]: d for d in scenario["devices"]}
        self._build()

    # ------------------------------------------------------------------
    # 构造（确定性；全部复用 DerivedState / 冻结物理原语）
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self.tasks: List[Dict] = []
        for i, task in enumerate(self.scenario["tasks"]):
            device = self._device_by_id[task["device_id"]]
            loc = self.derived.task_local[i]
            alpha = float(task["delay_weight"])
            f_loc = float(device["local_cpu_rate"])
            a_i = alpha * f_loc
            self.tasks.append(
                {
                    "task_id": task["task_id"],
                    "device_id": task["device_id"],
                    "c": float(task["cpu_cycles"]),
                    "nu": float(task["fragility"]),
                    "alpha": alpha,
                    "beta": float(task["energy_weight"]),
                    "R_min": float(task["min_reliability"]),
                    "f_loc": f_loc,
                    "lambda_loc": float(device["local_failure_rate"]),
                    "R_loc": float(loc["R_loc"]),
                    "b_loc": int(loc["b_loc"]),
                    "a_i": a_i,          # LA 权重分子（Theorem 3/Eq.25）
                    "s_i": math.sqrt(max(a_i, 0.0)),  # LA sqrt 权重
                }
            )
        self.servers: List[Dict] = []
        for j, sstate in enumerate(self.derived.server_state):
            self.servers.append(
                {
                    "server_id": self.server_ids[j],
                    "F_j": float(sstate["F_j"]),
                    "lambda_j": float(sstate["lambda_j"]),
                }
            )
        # 边（i,j）：仅存在链路时登记；e_rec=1 表示该边可满足可靠性
        self.edges: Dict[Tuple[int, int], Dict] = {}
        for i in range(self.n):
            for j in range(self.m):
                ls = self.derived.link(i, j)
                if ls is None:
                    continue
                self.edges[(i, j)] = {
                    "ell_R": float(ls["ell_R"]),
                    "ell_succ": float(ls["ell_succ"]),
                    "e_phy": int(ls["e_phy"]),
                    "e_rec": int(ls["e_rec"]),
                    "R_tx": float(ls["R_tx"]),
                    "T_tx": float(ls["T_tx"]),
                    "E_tx": float(ls["E_tx"]),
                    "F_j": self.servers[j]["F_j"],
                }

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def edge(self, i: int, j: int) -> Dict:
        """边 (i,j) 属性；不存在返回 None。"""
        return self.edges.get((i, j))

    def edge_feasible(self, i: int, j: int) -> bool:
        """candidate edge feasibility：该边在当前物理模型下可满足可靠性。

        等价于派生 e_rec=1（e_phy=1 且 ell_succ<+inf 且 ell_succ<=F_j；
        F-50），其中 ell_succ = max(ell_R, f_min^exec)（f_min^exec=1.0，§III-D；
        无 deadline 模型下对 nu>0 任务 ell_succ == ell_R）。不可满足可靠性（ell_R=+inf 或 ell_R>F_j 或物理不可达）
        的边一律 candidate_edge_feasible=false。
        """
        e = self.edges.get((i, j))
        return e is not None and e["e_rec"] == 1

    def local_success(self, i: int) -> bool:
        """local_success_i = (R_i^loc >= R_i^min)（derived b_loc 冻结语义）。"""
        return self.tasks[i]["b_loc"] == 1
