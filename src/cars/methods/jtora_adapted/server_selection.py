# -*- coding: utf-8 -*-
"""JTORA-adapted 服务器选择（原文 x^j_us 的服务器维度 + 项目 ground set）。

依据：references/JTORA-adapted.PDF Section IV（约束 12c/12d）+ 本子阶段
适配合同（mapping_to_X/A、physical_edge_adaptation）。

冻结语义：
- ground set G = {(i,j) : 物理有效边（e_phy==1）}，按 (任务索引, 服务器索引)
  升序（确定性；tie-break 与候选遍历顺序一致）；
- 子带维度省略（项目无 OFDMA 子带；约束 30d 无对应物）；
- 每任务至多一个 (i,j)（约束 30c 保留：X 行和 <= 1）；
- 物理无效边不可选；无可用边任务仅能本地。

reference 与 production 共用本函数。
"""

from __future__ import annotations

from typing import List, Tuple

from cars.methods.jtora_adapted.source_cost import SourceCosts


def ground_set(costs: SourceCosts) -> List[Tuple[int, int]]:
    """G = {(i,j) : 物理有效边}，按 (i, j) 升序（确定性）。"""
    return [
        (i, j)
        for i in range(costs.n)
        for j in range(costs.m)
        if costs.valid[i][j]
    ]


def exchange_set(Y: frozenset, i: int, j: int) -> frozenset:
    """[Routine 1 exchange 适配] 加入 (i,j)，移除任务 i 现有卸载（至多一个）。

    满足约束 30c（每任务至多一个卸载）；无子带 -> 无需为 30d 删除同服务器冲突。
    """
    return frozenset({x for x in Y if x[0] != i}) | frozenset({(i, j)})
