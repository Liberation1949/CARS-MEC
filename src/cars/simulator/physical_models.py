# -*- coding: utf-8 -*-
"""统一物理模型原语（R2 公共底座）。

每个公式只允许一个正式实现（提示词 Step 3.2）。本模块是 Evaluator 与
Scenario/派生状态共享的公式原语库；公式逐条对应 Contract F-01..F-17、
F-35、F-50、F-52、F-61 与 Formula Map YAML。单位明确；禁止 NaN/Inf 静默
传播（NaN 抛 ValueError）；+inf 用 float('inf') 表示，序列化时由结果构建层
转为显式 sentinel 字符串 "inf"（Contract Part 8.2）。

不实现负载放大故障率（固定名义故障率，方法边界）。
"""

from __future__ import annotations

import math

INF = float("inf")

# ---------------------------------------------------------------------------
# 数值校验
# ---------------------------------------------------------------------------


def require_finite(x: float, name: str) -> None:
    """禁止 NaN 静默传播：NaN 抛 ValueError；+inf 在允许处由调用方显式处理。"""
    if math.isnan(x):
        raise ValueError("NaN encountered in %s" % name)


# ---------------------------------------------------------------------------
# 本地执行（III-C.1）
# ---------------------------------------------------------------------------


def local_exec_delay(c: float, f_loc: float) -> float:
    """[F-01] T_i^loc = c_i / f_i^loc；c_i>0, f_i^loc>0。单位 s。"""
    require_finite(c, "c")
    require_finite(f_loc, "f_loc")
    if c <= 0 or f_loc <= 0:
        raise ValueError("local_exec_delay requires c>0, f_loc>0")
    return c / f_loc


def local_exec_energy(kappa: float, c: float, f_loc: float) -> float:
    """[F-02] E_i^loc = kappa_i * c_i * (f_i^loc)^2；kappa>0。单位见字段。"""
    require_finite(kappa, "kappa")
    require_finite(c, "c")
    require_finite(f_loc, "f_loc")
    if kappa <= 0 or c <= 0 or f_loc <= 0:
        raise ValueError("local_exec_energy requires kappa>0, c>0, f_loc>0")
    return kappa * c * f_loc * f_loc


# ---------------------------------------------------------------------------
# 无线传输（III-C.2）
# ---------------------------------------------------------------------------


def shannon_rate(B: float, p: float, h: float, sigma2: float) -> float:
    """[F-03] r_ij = B_ij * log2(1 + p_i h_ij / sigma^2)。单位 bits/s。

    参数均为场景输入（B>0, p>0, h>0, sigma2>0）。
    """
    for v, name in ((B, "B"), (p, "p"), (h, "h"), (sigma2, "sigma2")):
        require_finite(v, name)
    if B <= 0 or p <= 0 or h <= 0 or sigma2 <= 0:
        raise ValueError("shannon_rate requires B>0, p>0, h>0, sigma2>0")
    return B * math.log2(1.0 + (p * h) / sigma2)


def transmission_delay(d: float, r: float) -> float:
    """[F-04] T_ij^tx = d_i / r_ij；d>0, r>0。单位 s。"""
    require_finite(d, "d")
    require_finite(r, "r")
    if d <= 0 or r <= 0:
        raise ValueError("transmission_delay requires d>0, r>0")
    return d / r


def transmission_energy(p: float, T_tx: float) -> float:
    """[F-05] E_ij^tx = p_i * T_ij^tx。单位见字段。"""
    require_finite(p, "p")
    require_finite(T_tx, "T_tx")
    if p <= 0 or T_tx < 0:
        raise ValueError("transmission_energy requires p>0, T_tx>=0")
    return p * T_tx


# ---------------------------------------------------------------------------
# 边缘执行（III-C.3 / III-D.2）
# ---------------------------------------------------------------------------


def edge_exec_delay(c: float, f: float) -> float:
    """[F-06] 边缘执行时延（条件定义）：
    a=1, f>0 -> c/f；a=0 -> 0；a=1, f=0 -> +inf。
    本函数按 f 分支（a 由调用方处理）。
    """
    require_finite(c, "c")
    require_finite(f, "f")
    if c <= 0 or f < 0:
        raise ValueError("edge_exec_delay requires c>0, f>=0")
    if f == 0.0:
        return INF
    return c / f


def edge_exec_reliability(lambda_j: float, nu: float, c: float, f: float) -> float:
    """[F-12] 边缘执行可靠性（条件定义）：
    a=1, f>0 -> exp(-lambda_j nu_i c_i / f)；otherwise -> 0。
    本函数按 f 分支（a 由调用方处理）。
    """
    require_finite(lambda_j, "lambda_j")
    require_finite(nu, "nu")
    require_finite(c, "c")
    require_finite(f, "f")
    if lambda_j < 0 or nu < 0 or c <= 0 or f < 0:
        raise ValueError(
            "edge_exec_reliability requires lambda_j>=0, nu>=0, c>0, f>=0"
        )
    if f == 0.0:
        return 0.0
    return math.exp(-lambda_j * nu * c / f)


def offloading_reliability(R_tx: float, R_exe: float) -> float:
    """[F-13] R_ij^off = R_ij^tx * R_ij^exe（条件独立乘积）。a 分支由调用方处理。"""
    require_finite(R_tx, "R_tx")
    require_finite(R_exe, "R_exe")
    if not (0.0 <= R_tx <= 1.0) or not (0.0 <= R_exe <= 1.0):
        raise ValueError("offloading_reliability requires R_tx,R_exe in [0,1]")
    return R_tx * R_exe


# ---------------------------------------------------------------------------
# 名义可靠性（III-D.1）
# ---------------------------------------------------------------------------


def local_reliability(lambda_loc: float, nu: float, T_loc: float) -> float:
    """[F-10] R_i^loc = exp(-lambda_i^loc * nu_i * T_i^loc)。"""
    require_finite(lambda_loc, "lambda_loc")
    require_finite(nu, "nu")
    require_finite(T_loc, "T_loc")
    if lambda_loc < 0 or nu < 0 or T_loc < 0:
        raise ValueError("local_reliability requires lambda_loc>=0, nu>=0, T_loc>=0")
    return math.exp(-lambda_loc * nu * T_loc)


def transmission_reliability(p_err: float) -> float:
    """[F-11] R_ij^tx = 1 - p_ij^err；p_err in [0,1)。"""
    require_finite(p_err, "p_err")
    if not (0.0 <= p_err < 1.0):
        raise ValueError("transmission_reliability requires p_err in [0,1)")
    return 1.0 - p_err


# ---------------------------------------------------------------------------
# 成功资源阈值（III-D.5 / VI-B Prop.1；无 deadline 模型：仅可靠性阈值）
# ---------------------------------------------------------------------------


def reliability_threshold(lambda_j: float, nu: float, c: float, R_tx: float, R_min: float):
    """[F-16] ell_ij^R 四分支（令 DeltaR = ln(R_tx/R_min)）。

    - R_tx < R_min                -> +inf
    - R_tx == R_min 且 lambda_j*nu*c > 0 -> +inf
    - R_tx == R_min 且 lambda_j*nu*c == 0 -> 0
    - R_tx > R_min                -> lambda_j*nu*c / ln(R_tx/R_min)
    """
    require_finite(lambda_j, "lambda_j")
    require_finite(nu, "nu")
    require_finite(c, "c")
    require_finite(R_tx, "R_tx")
    require_finite(R_min, "R_min")
    if lambda_j < 0 or nu < 0 or c <= 0:
        raise ValueError("reliability_threshold requires lambda_j>=0, nu>=0, c>0")
    if not (0.0 < R_tx < 1.0) or not (0.0 < R_min < 1.0):
        raise ValueError("reliability_threshold requires R_tx,R_min in (0,1)")
    base = lambda_j * nu * c
    if R_tx < R_min:
        return INF
    if R_tx == R_min:
        return INF if base > 0 else 0.0
    delta = math.log(R_tx / R_min)  # >0
    return base / delta


# ---------------------------------------------------------------------------
# 边标记与派生量（IV-A.3 / V-B.2 / V-C.2 / V-B.4）
# ---------------------------------------------------------------------------


def physical_edge_marker(r: float, T_tx: float) -> int:
    """[F-35] e_phy = 1[r>0 and T_tx<+inf]。仅排除物理不可通信边。"""
    require_finite(r, "r")
    require_finite(T_tx, "T_tx")
    return 1 if (r > 0 and T_tx < INF) else 0


def recoverability_marker(e_phy: int, ell_succ, F_j: float) -> int:
    """[F-50] e_rec = 1[e_phy=1 and ell_succ<+inf and ell_succ<=F_j]。"""
    if e_phy not in (0, 1):
        raise ValueError("recoverability_marker requires e_phy in {0,1}")
    require_finite(F_j, "F_j")
    if F_j <= 0:
        raise ValueError("recoverability_marker requires F_j>0")
    if e_phy == 1 and ell_succ < INF and ell_succ <= F_j:
        return 1
    return 0


def finite_demand_proxy(ell_succ, e_rec: int, F_j: float) -> float:
    """[F-52] f_tilde_ij^req 三分支（避免不可恢复边无穷需求）。

    - e_rec=1                 -> ell_succ
    - e_rec=0 且 ell_succ<+inf -> min(ell_succ, F_j)
    - ell_succ=+inf           -> F_j
    """
    if e_rec not in (0, 1):
        raise ValueError("finite_demand_proxy requires e_rec in {0,1}")
    require_finite(F_j, "F_j")
    if F_j <= 0:
        raise ValueError("finite_demand_proxy requires F_j>0")
    if e_rec == 1:
        return ell_succ
    if ell_succ < INF:
        return min(ell_succ, F_j)
    return F_j


def local_success_demand_R(lambda_loc: float, nu: float, c: float, R_min: float) -> float:
    """[F-53] ell_i0^R 分支：lambda_loc*nu>0 且 R_min>0 -> lambda_loc*nu*c/(-ln R_min)；否则 0。"""
    require_finite(lambda_loc, "lambda_loc")
    require_finite(nu, "nu")
    require_finite(c, "c")
    require_finite(R_min, "R_min")
    if lambda_loc < 0 or nu < 0 or c <= 0:
        raise ValueError("local_success_demand_R requires lambda_loc>=0, nu>=0, c>0")
    if not (0.0 < R_min < 1.0):
        raise ValueError("local_success_demand_R requires R_min in (0,1)")
    if lambda_loc * nu > 0:
        return (lambda_loc * nu * c) / (-math.log(R_min))
    return 0.0
