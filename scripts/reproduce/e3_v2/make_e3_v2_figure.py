# -*- coding: utf-8 -*-
"""E3-V2-2：Fig E3-1（三 Panel，一张 Figure）——重设计版（2026-08-09）。

针对"曲线重叠副作用"的呈现优化（数据不变，仅改呈现）：
- Panel A：Phase-1 贡献柱状图——ΔTSSR = Full − w/o Rescue 随压力（避开 4 条
  饱和 ~1.0 的 TSSR 线重叠；柱=paired mean diff，误差棒=paired std）；
- Panel B：Ubar_eff vs pressure——只画 Full / Rescue-only / w/o Δφ 三条有区分的线
  （去掉与 Full 完全重合的 w/o Utility Gate；w/o Rescue 的 Ubar 区分度低且属另一机制）；
- Panel C：V_R vs pressure——RCLA vs ordinary LA（fixed assignment，保留，区分最好）。

数据源：results/e3_v2/e3_v2_2_formal_summary.json（正式 seeds 401-410）
输出：results/e3_v2/figures/Fig_E3_1.png / .pdf
"""
from __future__ import annotations

import json
import os
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SUMMARY_PATH = os.path.join(_PROJECT, "results", "e3_v2", "e3_v2_2_formal_summary.json")
FIG_DIR = os.path.join(_PROJECT, "results", "e3_v2", "figures")

PRESSURES = ["LOW", "TRANSITION", "HIGH"]

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

LABELS = {
    "full": "Full",
    "rescue_only": "Rescue-only",
    "no_alloc_aware": "w/o $\\Delta\\phi$",
    "fixed_rcla": "RCLA",
    "fixed_ordinary_la": "ordinary LA",
}


def main() -> int:
    s = json.load(open(SUMMARY_PATH, encoding="utf-8"))
    os.makedirs(FIG_DIR, exist_ok=True)

    def series(u, m):
        return [s["per_cell"]["%s/%s" % (p, u)][m]["mean"] for p in PRESSURES]

    xs = list(range(3))
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 3.6))

    # ---- Panel A: Phase-1 贡献 ΔTSSR（Full − w/o Rescue）随压力 ----
    ax = axes[0]
    d = s["paired"]["delta_rescue"]
    means = [d[p]["mean_diff"] for p in PRESSURES]
    stds = [d[p]["std"] for p in PRESSURES]
    ax.bar(xs, means, yerr=stds, capsize=4, color="#4C72B0", alpha=0.85,
           error_kw={"elinewidth": 1.2, "capthick": 1.2})
    for i, (m, sd) in enumerate(zip(means, stds)):
        ax.text(i, m + sd + 0.012, "%.3f" % m, ha="center", fontsize=8)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xticks(xs)
    ax.set_xticklabels(PRESSURES)
    ax.set_ylabel(r"$\Delta$TSSR (Full $-$ w/o Rescue)")
    ax.set_title("(a) Phase-1 recovery contribution")
    ax.grid(axis="y", alpha=0.3)
    ax.set_ylim(0, 0.45)

    # ---- Panel B: Ubar_eff（Full / Rescue-only / w/o Δφ）----
    ax = axes[1]
    for u in ["full", "rescue_only", "no_alloc_aware"]:
        ax.plot(xs, series(u, "Ubar_eff"), marker="s", label=LABELS[u])
    ax.set_xticks(xs)
    ax.set_xticklabels(PRESSURES)
    ax.set_ylabel(r"$\bar U_{\mathrm{eff}}$")
    ax.set_title("(b) $\\bar U_{\\mathrm{eff}}$ vs pressure")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="lower left")

    # ---- Panel C: V_R（fixed RCLA vs LA）----
    ax = axes[2]
    ax.plot(xs, series("fixed_rcla", "V_R"), marker="^", label="RCLA")
    ax.plot(xs, series("fixed_ordinary_la", "V_R"), marker="v", label="ordinary LA")
    ax.set_xticks(xs)
    ax.set_xticklabels(PRESSURES)
    ax.set_ylabel("$V_R$")
    ax.set_title("(c) $V_R$: RCLA vs LA (fixed X/A)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    ax.set_ylim(-0.005, 0.15)

    fig.tight_layout()

    for ext in ("png", "pdf"):
        path = os.path.join(FIG_DIR, "Fig_E3_1.%s" % ext)
        fig.savefig(path, dpi=200)
        print("written:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
