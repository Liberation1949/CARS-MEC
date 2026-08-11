# -*- coding: utf-8 -*-
"""JTORA-adapted 源代价构造（原文 Eq.1/5/9/10 + 项目物化传输项）。

依据：references/JTORA-adapted.PDF Section III + 本子阶段适配合同
（R3_jtora_adaptation_contract.yaml mapping_to_X/A/F、transmission_model_adaptation）。

冻结语义（source_faithful + project_adapted）：
- 本地：t^l_i = T_loc（共享 F-01）、E^l_i = E_loc（共享 F-02）；
  beta^t_i = delay_weight、beta^e_i = energy_weight（beta^t+beta^e=1）；
  lambda_i = 1（原文默认 lambda_u=1，项目无该参数）；
- 卸载效用（Eq.10 身份）：J_u = beta^t(t^l-t)/t^l + beta^e(E^l-E)/E^l；
- 传输开销（Eq.16-19 结构）：transmission_overhead(i,j) =
  lambda_i [ beta^t_i T_tx(i,j)/t^l_i + beta^e_i E_tx(i,j)/E^l_i ]，
  T_tx/E_tx 为共享 DerivedState 物化传输项（场景固定功率；§2.4 三条件已证明）；
- CRA 权重：eta_i = lambda_i beta^t_i c_i / t^l_i；sqrt(eta_i) 用于 Eq.27。

本模块不复制任何物理公式：全部数值来自共享 DerivedState 的 task_local/link_state
与 scenario 输入。reference 与 production 共用（等价保证）。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from cars.simulator.derived_state import DerivedState


class SourceCosts:
    """预计算的 JTORA 源代价量（T0 只读；无未来信息）。"""

    def __init__(self, scenario: Dict, derived: DerivedState) -> None:
        n = len(derived.task_ids)
        m = len(derived.server_ids)
        tasks = scenario["tasks"]
        self.n = n
        self.m = m
        self.beta_t: List[float] = [float(t["delay_weight"]) for t in tasks]
        self.beta_e: List[float] = [float(t["energy_weight"]) for t in tasks]
        self.c: List[float] = [float(t["cpu_cycles"]) for t in tasks]
        self.t_loc: List[float] = [float(derived.task_local[i]["T_loc"]) for i in range(n)]
        self.e_loc: List[float] = [float(derived.task_local[i]["E_loc"]) for i in range(n)]
        self.lam: List[float] = [1.0] * n  # 原文默认 lambda_u=1
        self.eta: List[float] = [
            self.lam[i] * self.beta_t[i] * self.c[i] / self.t_loc[i] for i in range(n)
        ]
        self.w: List[float] = [math.sqrt(self.eta[i]) for i in range(n)]

        # 物化传输项（仅物理有效边；e_phy=1 才可选中）
        self.t_tx: List[List[Optional[float]]] = [[None] * m for _ in range(n)]
        self.e_tx: List[List[Optional[float]]] = [[None] * m for _ in range(n)]
        self.valid: List[List[bool]] = [[False] * m for _ in range(n)]
        for i in range(n):
            for j in range(m):
                ls = derived.link(i, j)
                if ls is not None and ls["e_phy"] == 1:
                    self.t_tx[i][j] = float(ls["T_tx"])
                    self.e_tx[i][j] = float(ls["E_tx"])
                    self.valid[i][j] = True

    def transmission_overhead(self, i: int, j: int) -> float:
        """传输开销（Eq.16-19 中 per-user 传输项；物化 T_tx/E_tx）。"""
        tt = self.t_tx[i][j]
        et = self.e_tx[i][j]
        if tt is None or et is None:
            raise ValueError("transmission_overhead called on invalid edge (%d,%d)" % (i, j))
        return self.lam[i] * (
            self.beta_t[i] * tt / self.t_loc[i] + self.beta_e[i] * et / self.e_loc[i]
        )

    def constant_utility(self, i: int) -> float:
        """Eq.29 首项：lambda_i (beta^t_i + beta^e_i)。"""
        return self.lam[i] * (self.beta_t[i] + self.beta_e[i])
