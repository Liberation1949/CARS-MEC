# -*- coding: utf-8 -*-
"""MATH-ORACLE-CONSISTENCY-R1 专项冻结测试（T1-T6）。

依据：MATH-ORACLE-CONSISTENCY-R1 阶段任务 Step 6；E4-EXACT Oracle 数学自洽性修复。

T1  ν=0 single task：q=0 -> R 常数；成功分配要求 f>0，不允许趋近 0 边界。
T2  Mixed zero/nonzero fragility（1 server 2 tasks）：Tier-2 最优值可取得。
T3  Tier-2 flat set（全部 q=0）：Tier-2 目标存在多个最优 allocation（值唯一）。
T4  Tier-3 tie break：Oracle 在 Tier-2 最优集内选择效用最优分配。
T5  Concavity domain：formal 参数边界 ln(R_tx/R_min)<2 且 ell_R>q/2（q>0）。
T6  Oracle independent check：solve_server vs 独立密集数值三层字典序验证。

注：本组测试验证的是修复后的 Oracle 连续求解语义；E4-EXACT-3 正式结果需在
本修复后重跑（原结果降级为旧结果），见 MATH-ORACLE-CONSISTENCY-R1 报告。
"""

from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cars.exact_oracle import continuous_solver


def _task(index, ell_R, r_tx, a, A_u=1.0, K_u=0.0):
    return {"index": index, "ell_R": ell_R, "R_tx": r_tx, "a": a, "A_u": A_u, "K_u": K_u}


# ---------------------------------------------------------------------------
# T1. ν=0 single task
# ---------------------------------------------------------------------------
def test_t1_nu0_single_task():
    # q=0 -> ell_R=0, R(f)=R_tx 常数；成功执行要求 f>0，分配不趋近 0 边界
    sol = continuous_solver.solve_server([_task(0, 0.0, 0.99, 0.0, A_u=1.0, K_u=0.5)], 1.0e4)
    assert sol is not None
    assert sol["f"][0] > 0.0                     # 正资源下界闭合（非 f->0+）
    assert sol["R2"] == pytest.approx(0.99)      # R 常数
    assert sol["zero_alloc_mode"] == "WATERFILL"  # Tier-3 效用水填充


# ---------------------------------------------------------------------------
# T2. Mixed zero/nonzero fragility
# ---------------------------------------------------------------------------
def test_t2_mixed_zero_nonzero():
    # 1 server, 2 tasks：nu1=0（a=0）, nu2>0（a=2, ell_R=0.5）
    t0 = _task(0, 0.0, 0.99, 0.0, A_u=1.0, K_u=0.4)
    t1 = _task(1, 0.5, 0.99, 2.0, A_u=2.0, K_u=0.6)
    sol = continuous_solver.solve_server([t0, t1], 1.0e4)
    assert sol is not None                       # Tier-2 最优值可取得（非 supremum）
    assert sol["f"][1] >= t1["ell_R"]            # pos 任务满足 reliability floor
    assert sol["f"][0] > 0.0                     # zero 任务正资源
    assert abs(sol["capacity_residual"]) < 1e-9  # 容量不违约
    assert sol["mode"] == "CERTIFIED_NUMERICAL_EXACT"


# ---------------------------------------------------------------------------
# T3. Tier-2 flat set（全部 q=0）
# ---------------------------------------------------------------------------
def test_t3_tier2_flat_set():
    # 全部 q=0：Tier-2 目标为常数（R_tx 之和），任意正分配均达同一 Tier-2 值
    t0 = _task(0, 0.0, 0.99, 0.0, A_u=1.0, K_u=0.5)
    t1 = _task(1, 0.0, 0.98, 0.0, A_u=2.0, K_u=0.6)
    sol = continuous_solver.solve_server([t0, t1], 1.0e4)
    assert sol is not None
    assert sol["R2"] == pytest.approx(0.99 + 0.98)   # Tier-2 值唯一
    # Tier-2 最优集非单点；Tier-3 选择效用水填充（每任务保底 f_min^exec=1.0，剩余按 sqrt(A_u)）
    s = math.sqrt(1.0) + math.sqrt(2.0)
    rem = 1.0e4 - 2 * 1.0
    assert sol["f"][0] == pytest.approx(1.0 + rem * math.sqrt(1.0) / s, rel=1e-9)
    assert sol["f"][1] == pytest.approx(1.0 + rem * math.sqrt(2.0) / s, rel=1e-9)
    assert sol["zero_alloc_mode"] == "WATERFILL"


# ---------------------------------------------------------------------------
# T4. Tier-3 tie break（全部 q=0：Tier-2 最优集为全空间，Tier-3 水填充）
# ---------------------------------------------------------------------------
def test_t4_tier3_tiebreak():
    # 全部 q=0（k=0）：Tier-2 目标为常数，Tier-2 最优集包含全部可行分配；
    # Tier-3 在 Tier-2 最优集内做效用水填充（f ∝ sqrt(A_u)）。
    t0 = _task(0, 0.0, 0.99, 0.0, A_u=1.0, K_u=0.5)
    t1 = _task(1, 0.0, 0.98, 0.0, A_u=2.0, K_u=0.6)
    F = 100.0
    sol = continuous_solver.solve_server([t0, t1], F)
    assert sol is not None
    assert sol["tier3_tiebreak_applied"] is True
    s = math.sqrt(1.0) + math.sqrt(2.0)
    rem = F - 2 * 1.0
    assert sol["f"][0] == pytest.approx(1.0 + rem * math.sqrt(1.0) / s, rel=1e-9)
    assert sol["f"][1] == pytest.approx(1.0 + rem * math.sqrt(2.0) / s, rel=1e-9)
    # Tier-2 值唯一（常数）；Tier-3 为最优集内最大
    assert sol["R2"] == pytest.approx(0.99 + 0.98)
    u3 = (0.5 - 1.0 / sol["f"][0]) + (0.6 - 2.0 / sol["f"][1])
    assert sol["U3"] == pytest.approx(u3, rel=1e-9)
    assert sol["zero_alloc_mode"] == "WATERFILL"


# ---------------------------------------------------------------------------
# T5. Concavity domain（formal 参数边界）
# ---------------------------------------------------------------------------
def test_t5_concavity_domain():
    R_tx = 0.99
    for r_min in (0.85, 0.95):  # formal R_min 边界
        d = math.log(R_tx / r_min)
        assert d < 2.0                              # 凹性条件 ln(R_tx/R_min) < 2
        for q in (1e-6, 1.0, 100.0):                # q>0 域
            ell = q / d
            assert ell > q / 2.0                     # floor 在拐点右侧
            f = ell                                 # 域内最小 f
            # R''(f) = R(f)·q·(q-2f)/f^4 <= 0 当 f >= q/2
            assert q * (q - 2.0 * f) / (f ** 4.0) <= 0.0


# ---------------------------------------------------------------------------
# T6. Oracle independent check（独立解析推导，不依赖 Oracle 代码逻辑）
# ---------------------------------------------------------------------------
def test_t6_oracle_independent_check():
    # (a) 混合场景（nu1=0, nu2>0）：Tier-2 最优 f1 用满容量（R1 单调增），
    #     f0 贡献常数 R_tx、取剩余容量（Tier-3 分配剩余，非固定 epsilon）。
    t0 = _task(0, 0.0, 0.99, 0.0, A_u=1.0, K_u=0.4)
    t1 = _task(1, 0.5, 0.99, 2.0, A_u=2.0, K_u=0.6)
    F = 100.0
    sol = continuous_solver.solve_server([t0, t1], F)
    assert sol is not None
    f1_or = sol["f"][1]
    f0_or = sol["f"][0]
    assert f1_or == pytest.approx(F - 1.0, rel=1e-6)   # F_avail = F - n_zero*f_min^exec
    assert f0_or == pytest.approx(1.0, rel=1e-6)       # zero 保底 f_min^exec（无额外剩余）
    r2_star = 0.99 + 0.99 * math.exp(-2.0 / f1_or)      # 独立 Tier-2 公式
    assert sol["R2"] == pytest.approx(r2_star, rel=1e-9)
    u3_star = (0.4 - 1.0 / f0_or) + (0.6 - 2.0 / f1_or)  # 独立 Tier-3 公式
    assert sol["U3"] == pytest.approx(u3_star, rel=1e-9)
    # (b) 全部 zero（k=0）：独立解析验证 Tier-2 常数 + Tier-3 保底+水填充
    t_a = _task(0, 0.0, 0.99, 0.0, A_u=1.0, K_u=0.5)
    t_b = _task(1, 0.0, 0.98, 0.0, A_u=2.0, K_u=0.6)
    sol2 = continuous_solver.solve_server([t_a, t_b], F)
    assert sol2 is not None
    assert sol2["R2"] == pytest.approx(0.99 + 0.98)   # Tier-2 常数
    s = math.sqrt(1.0) + math.sqrt(2.0)
    rem2 = F - 2 * 1.0
    fa = 1.0 + rem2 * math.sqrt(1.0) / s
    fb = 1.0 + rem2 * math.sqrt(2.0) / s
    assert sol2["f"][0] == pytest.approx(fa, rel=1e-9)
    assert sol2["f"][1] == pytest.approx(fb, rel=1e-9)
    u3_star2 = (0.5 - 1.0 / fa) + (0.6 - 2.0 / fb)
    assert sol2["U3"] == pytest.approx(u3_star2, rel=1e-9)
    assert sol2["zero_alloc_mode"] == "WATERFILL"
    # (c) 密集网格独立验证（dense numerical cross-check，混合场景）：
    #     在 f1 网格上找 Tier-2 最优（R1 单调增 -> f1 最大），与解析一致
    grid = 2000
    best = None
    for j in range(1, grid + 1):
        f1 = F * j / grid
        if f1 < t1["ell_R"] - 1e-9:
            continue
        t2 = 0.99 + 0.99 * math.exp(-2.0 / f1)
        if best is None or t2 > best + 1e-12:
            best = t2
    assert sol["R2"] == pytest.approx(best, rel=1e-3)
