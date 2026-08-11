# -*- coding: utf-8 -*-
"""BPSO 内部目标（原文 Eq.9 / Eq.10）与共享指标原语。

依据：bpso-rata-la.pdf Section III（Eq.8-10）+ 本子阶段适配合同
（R3_BPSO_RATA_LA_adaptation_contract.yaml fitness_direction）。

冻结语义：
- fitness = 系统卸载效用 sum_i 兜_i（Eq.10，最大化）。
  兜_i = x_i [ alpha_i (t_loc - t_off)/t_loc + beta_i (E_loc - E_trans)/E_loc ]。
  与共享 F-39 U_i 一致：本地任务 U_i=0（x_i=0 使 Eq.10 为 0）；卸载任务
  U_i = alpha(T_loc-T_i)/T_loc + beta(E_loc-E_i)/E_loc，其中
  T_i = T_tx + c/f_ij（Eq.4）、E_i = E_tx（Eq.5）。
- reliability = 系统可靠性 R_sys = prod_i R_i（Eq.9）。
  R_i 用共享物理模型（F-10 本地 / F-11 R_tx / F-12 R_exe / F-14 R_i）：
  本地 R_i = R_loc；卸载 R_i = R_tx * R_exe。
  传输可靠性用项目共享 R_tx=1-p_err（固定名义故障率边界；原文 Eq.6
  e^(-gamma*t_trans) 不移植，见合同 project_adapted）。

fitness 不是统一正式指标；最终 (X,A,F) 由统一 Evaluator 唯一正式评价
（Runner 唯一调用者）。
"""

from __future__ import annotations

from typing import Dict, Sequence, Tuple

from cars.evaluator import metrics
from cars.simulator.derived_state import DerivedState


def source_fitness_and_reliability(
    X: Sequence[int],
    A: Sequence[Sequence[int]],
    F: Sequence[Sequence[float]],
    scenario: Dict,
    derived: DerivedState,
) -> Tuple[float, float]:
    """返回 (fitness=sum_i U_i [Eq.10], R_sys=prod_i R_i [Eq.9])。

    要求 (X,A,F) 为 RATA+LA 生成的合法解（卸载任务唯一指派且 f>0）。
    """
    n = len(derived.task_ids)
    fitness = 0.0
    rsys = 1.0
    for i in range(n):
        a_row = [int(v) for v in A[i]]
        f_row = [float(v) for v in F[i]]
        T_i, _j = metrics.task_end_to_end_delay(derived, i, int(X[i]), a_row, f_row)
        E_i = metrics.task_energy(derived, i, int(X[i]), a_row, f_row)
        R_i = metrics.task_reliability(derived, i, int(X[i]), a_row, f_row)
        U_i = metrics.task_utility(derived, i, T_i, E_i)
        fitness += U_i
        rsys *= R_i
    return fitness, rsys
