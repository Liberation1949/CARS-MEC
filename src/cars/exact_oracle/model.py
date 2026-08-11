# -*- coding: utf-8 -*-
"""Exact Oracle 模型视图（E4-EXACT-1；E4_EXACT_ORACLE_CONTRACT_V1 §4）。

从当前 Scenario / DerivedState 构造 Oracle 输入；不复制物理模型、
不创建第二套可靠性公式，只调用当前公共 physical semantics
（src/cars/simulator/physical_models.py、src/cars/simulator/derived_state.py）。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from cars.simulator.derived_state import DerivedState


class OracleModel:
    """Oracle 输入视图（T0 决策前派生；全部字段来自公共 DerivedState/physical models）。"""

    def __init__(self, scenario: Dict, derived: Optional[DerivedState] = None):
        self.scenario = scenario
        self.derived = derived if derived is not None else DerivedState(scenario)
        self.n = len(scenario["tasks"])
        self.m = len(scenario["servers"])
        self._build()

    # ------------------------------------------------------------------
    def _device(self, device_id: str) -> Dict:
        for d in self.scenario["devices"]:
            if d["device_id"] == device_id:
                return d
        raise KeyError(device_id)

    def _build(self) -> None:
        # 任务本地属性（固定贡献；Evaluator F-39/F-19 语义）
        self.local: List[Dict] = []
        for i in range(self.n):
            loc = self.derived.task_local[i]
            self.local.append(
                {
                    "index": i,
                    "task_id": loc["task_id"],
                    "b_loc": loc["b_loc"],        # 本地预计成功标记
                    "R_loc": loc["R_loc"],
                    "T_loc": loc["T_loc"],
                    "E_loc": loc["E_loc"],
                }
            )

        # 每任务可用服务器列表（e_phy=1）与边属性（公共 DerivedState）
        self.edge_servers: List[List[int]] = [[] for _ in range(self.n)]
        self.edges: Dict[tuple, Dict] = {}
        for i in range(self.n):
            task = self.scenario["tasks"][i]
            device = self._device(task["device_id"])
            alpha = task["delay_weight"]
            beta = task["energy_weight"]
            c = task["cpu_cycles"]
            T_loc = self.local[i]["T_loc"]
            E_loc = self.local[i]["E_loc"]
            for j in range(self.m):
                ls = self.derived.link(i, j)
                if ls is None or ls["e_phy"] != 1:
                    continue
                server = self.derived.server_state[j]
                a = server["lambda_j"] * task["fragility"] * c   # a_i = lambda_j * nu_i * c_i
                ell_R = ls["ell_R"]                              # 公共 reliability floor（F-16）
                R_tx = ls["R_tx"]
                T_tx = ls["T_tx"]
                E_tx = ls["E_tx"]
                R_min = task["min_reliability"]
                # U_i(f) = K_u - A_u / f（Evaluator F-39 在 EDGE 路径的结构）
                A_u = alpha * c / T_loc
                K_u = alpha * (T_loc - T_tx) / T_loc + beta * (E_loc - E_tx) / E_loc
                self.edges[(i, j)] = {
                    "index": i,
                    "j": j,
                    "a": a,
                    "ell_R": ell_R,
                    "R_tx": R_tx,
                    "T_tx": T_tx,
                    "E_tx": E_tx,
                    "A_u": A_u,
                    "K_u": K_u,
                    "F_j": server["F_j"],
                    "lambda_j": server["lambda_j"],
                    "R_min": R_min,
                    # 可达性：R_tx > R_min 时 ell_R 有限（ln 分母 > 0）
                    "reachable": (R_tx > R_min),
                    # 0-floor 判定：a == 0 且 R_tx >= R_min（R 常数且可成功）
                    "zero_floor": (a == 0.0 and R_tx >= R_min),
                }
                self.edge_servers[i].append(j)

    # ------------------------------------------------------------------
    def has_edge(self, i: int, j: int) -> bool:
        return (i, j) in self.edges

    def edge(self, i: int, j: int) -> Optional[Dict]:
        return self.edges.get((i, j))

    def is_locally_successful(self, i: int) -> bool:
        """b_i^loc：本地预计成功标记（公共 DerivedState）。"""
        return self.local[i]["b_loc"] == 1
