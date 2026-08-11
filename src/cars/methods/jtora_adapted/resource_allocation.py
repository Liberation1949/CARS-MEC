# -*- coding: utf-8 -*-
"""JTORA-adapted 连续资源分配（原文 CRA，Eq.25/27/28）。

依据：references/JTORA-adapted.PDF Section V-B（Lemma 2）+ 本子阶段适配合同
（mapping_to_F、source_resource_allocation）。

冻结语义（source_faithful）：
- CRA 子问题（Eq.25）凸；KKT 闭式（Eq.27/41）：
  f*_ij = F_j * sqrt(eta_i) / sum_{v in Y_j} sqrt(eta_v)，eta_i = beta^t_i c_i/t^l_i；
- 容量守恒：sum_{i in Y_j} f*_ij = F_j（Eq.12g 等号）；
- 正资源：f*_ij > 0 for (i,j) in Y；未指派边 f_ij = 0；
- 空服务器无分配。

输出满足：f_ij >= 0；a_ij=0 -> f_ij=0；sum_i f_ij <= F_j + eps_cmp。
reference 与 production 共用。
"""

from __future__ import annotations

from typing import FrozenSet, List, Tuple

from cars.methods.jtora_adapted.numerical_solver import crc_closed_form
from cars.methods.jtora_adapted.source_cost import SourceCosts
from cars.simulator.derived_state import DerivedState


def allocate_resources(
    Y: FrozenSet[Tuple[int, int]], costs: SourceCosts, derived: DerivedState
) -> List[List[float]]:
    """[Eq.27] 固定 Y 生成 F（CRA 闭式）。"""
    n = costs.n
    m = costs.m
    F: List[List[float]] = [[0.0] * m for _ in range(n)]
    tasks_by_server: dict = {}
    for (i, j) in Y:
        tasks_by_server.setdefault(j, []).append(i)
    for j, tasks in tasks_by_server.items():
        F_j = float(derived.server_state[j]["F_j"])
        weights = [costs.w[i] for i in tasks]
        alloc = crc_closed_form(tasks, weights, F_j)
        for i, f in alloc.items():
            F[i][j] = f
    return F
