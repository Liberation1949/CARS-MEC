# -*- coding: utf-8 -*-
"""完整、确定性枚举合法离散 X/A（E4-EXACT-1）。

依据：experiment_docs/III_VII.md IV-A（决策变量）、IV-B（C1-C4）；
E4_EXACT_ORACLE_CONTRACT_V1 §4.1（离散层 X/A 规格）。

- 每个任务动作空间：LOCAL（x_i=0，a 全 0）或恰一个 EDGE_SERVER_j（j 满足 e_phy=1）。
- 枚举满足 C3（sum_j a_ij = x_i）与 C4（a_ij <= e_phy）的全部 (X, A)。
- deterministic ordering：任务 index 升序、服务器 index 升序（itertools.product 字典序）。
- NAIVE_EXHAUSTIVE：无剪枝（本层 PRUNE-A 是 C4 约束本身，两模式一致）。
- EXACT_PRUNED：与 NAIVE 相同离散层；PRUNE-B 在 oracle.py 成功集枚举层生效。
- 理论状态数上界：(1 + M)^N（每任务 1 LOCAL + 至多 M EDGE）。
"""

from __future__ import annotations

from itertools import product
from typing import Dict, Iterator, List, Tuple

from cars.exact_oracle.model import OracleModel

NAIVE_EXHAUSTIVE = "NAIVE_EXHAUSTIVE"
EXACT_PRUNED = "EXACT_PRUNED"
VALID_MODES = (NAIVE_EXHAUSTIVE, EXACT_PRUNED)


def theoretical_state_bound(model: OracleModel) -> int:
    """完整离散状态数理论下界（每任务 1 LOCAL + 全部 e_phy=1 的 EDGE）。"""
    count = 1
    for i in range(model.n):
        count *= (1 + len(model.edge_servers[i]))
    return count


def per_task_action_counts(model: OracleModel) -> List[int]:
    """每任务的合法动作数（1 LOCAL + len(edge_servers)）。"""
    return [1 + len(model.edge_servers[i]) for i in range(model.n)]


def enumerate_xa(
    model: OracleModel, mode: str = EXACT_PRUNED
) -> Iterator[Tuple[List[int], List[List[int]]]]:
    """确定性枚举全部合法 (X, A)。返回 (offloading_decision, assignment_matrix)。

    mode：NAIVE_EXHAUSTIVE | EXACT_PRUNED（本层两模式离散动作空间相同；
    PRUNE-A 即 C4 约束体现在 edge_servers 定义中）。
    """
    if mode not in VALID_MODES:
        raise ValueError("unknown enumerator mode %r (valid: %s)" % (mode, VALID_MODES))
    n, m = model.n, model.m
    # 每任务动作列表：None=LOCAL；否则为服务器索引 j
    actions: List[List[object]] = []
    for i in range(n):
        acts: List[object] = [None]
        acts.extend(sorted(model.edge_servers[i]))  # server_id 升序（确定性）
        actions.append(acts)
    for combo in product(*actions):
        X = [0] * n
        A = [[0] * m for _ in range(n)]
        for i, act in enumerate(combo):
            if act is not None:
                X[i] = 1
                A[i][int(act)] = 1
        yield X, A
