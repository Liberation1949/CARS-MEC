# -*- coding: utf-8 -*-
"""P0 可行性必要/充分检查与 safe pruning rules（E4-EXACT-1）。

依据：E4_EXACT_ORACLE_CONTRACT_V1 §3.1/§5（Exact 资格、安全剪枝）；
experiment_docs/III_VII.md IV-B（C1-C6）、III-D.4（任务可靠性）。

每条 pruning rule 必须携带 rule_id + mathematical_condition + source + proof_of_safety。
未登记/未证明的 pruning rule 一律拒绝（unsafe pruning 默认禁止）。
"""

from __future__ import annotations

from typing import Dict, List

from cars.exact_oracle.model import OracleModel

# ---------------------------------------------------------------------------
# 登记的安全剪枝规则（全部有直接数学证明）
# ---------------------------------------------------------------------------
PRUNING_RULES: Dict[str, Dict] = {
    "PRUNE-A": {
        "mathematical_condition": "a_ij = 1 要求 e_ij^phy = 1（正文 IV-B C4）",
        "source": "experiment_docs/III_VII.md IV-B C4 / IV-A.3",
        "proof_of_safety": (
            "C4 是 Omega_phy 硬约束：任何 a_ij=1 且 e_phy=0 的方案不属于可行域，"
            "不可能属于任何 P0 全局最优。枚举层直接排除 e_phy=0 边，不删除任何可行状态。"
        ),
        "implementation": "discrete_enumerator 仅对 e_phy=1 边生成 EDGE 动作（OracleModel.edge_servers）",
    },
    "PRUNE-B": {
        "mathematical_condition": (
            "任务 i 必败：b_i^loc=0（本地 R_i^loc < R_i^min）且不存在任何可达 EDGE"
            "（对全部 j：R_tx <= R_i^min 或边不存在）"
        ),
        "source": "experiment_docs/III_VII.md III-D.4 / III-E.2 / IV-C.1",
        "proof_of_safety": (
            "R_i^off(f) = R_tx * exp(-lambda*nu*c/f) <= R_tx（任意 f>0）。若 R_tx <= R_i^min，"
            "则任意 f 下 R_i^off < R_i^min，z_i 恒为 0；本地同样 b_loc=0。故该任务在任何"
            "合法决策下 z_i 恒 0，不进入任何成功集，不影响 P0 目标值。将其固定为失败"
            "不删除任何可能的全局最优。"
        ),
        "implementation": "oracle.py 成功集枚举时排除 doomed 任务（feasibility.doomed_tasks）",
    },
}


def safe_pruning_rules() -> List[str]:
    """已登记的安全剪枝规则 id 列表。"""
    return sorted(PRUNING_RULES.keys())


def validate_pruning_request(requested: List[str]) -> None:
    """拒绝任何未登记剪枝规则（unsafe pruning 默认禁止；Contract §3.3/§5）。"""
    unknown = [r for r in requested if r not in PRUNING_RULES]
    if unknown:
        raise ValueError(
            "unsafe/unregistered pruning rule(s) requested: %s; "
            "allowed safe rules: %s" % (unknown, safe_pruning_rules())
        )


def pruning_rule(id_: str) -> Dict:
    if id_ not in PRUNING_RULES:
        raise KeyError(id_)
    return PRUNING_RULES[id_]


# ---------------------------------------------------------------------------
# PRUNE-B 支持：必败任务集合
# ---------------------------------------------------------------------------
def doomed_tasks(model: OracleModel) -> List[int]:
    """返回必败任务索引（PRUNE-B；z_i 恒 0 的证明见 PRUNING_RULES）。"""
    doomed = []
    for i in range(model.n):
        if model.local[i]["b_loc"] == 1:
            continue
        reachable = False
        for j in model.edge_servers[i]:
            e = model.edge(i, j)
            if e is not None and e["reachable"]:
                reachable = True
                break
        if not reachable:
            doomed.append(i)
    return doomed
