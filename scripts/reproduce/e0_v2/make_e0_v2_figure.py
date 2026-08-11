# -*- coding: utf-8 -*-
"""E0-V2-MANUSCRIPT：Fig E0-1 / Fig E0-2（各三 Panel，两张 Figure）。

数据源：results/e0_v2/e0_v2_2_formal/formal_summary.json（正式 seeds 601-620）
输出：results/e0_v2/figures/Fig_E0_1.png/.pdf、Fig_E0_2.png/.pdf

Fig E0-1（Load-response performance）：(a) TSSR vs N；(b) Rbar_eff vs N；
  (c) Ubar_eff vs N。三条曲线：reliability_only / BPSO-RATA-LA / AADA-RCLA。
  mean ± std（跨 20 paired seeds）。
Fig E0-2（Reliability-resource mechanism）：(a) V_R vs N；(b) V_F vs N；
  (c) max G/F vs N。median（跨 20 paired seeds）。

呈现约定（与 E3 Fig 一致）：数据零改动，仅呈现；AADA-RCLA 用最醒目线型。
"""
from __future__ import annotations

import json
import os
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SUMMARY_PATH = os.path.join(_PROJECT, "results", "e0_v2", "e0_v2_2_formal", "formal_summary.json")
FIG_DIR = os.path.join(_PROJECT, "results", "e0_v2", "figures")

GRID = [20, 50, 80, 110, 140, 170, 200]
METHODS = ["reliability_only", "bpso_rata_la", "cars_aada_rcla_candidate"]

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

LABELS = {
    "reliability_only": "reliability-only",
    "bpso_rata_la": "BPSO-RATA-LA",
    "cars_aada_rcla_candidate": "AADA-RCLA",
}
COLORS = {"reliability_only": "#DD8452", "bpso_rata_la": "#4C72B0", "cars_aada_rcla_candidate": "#C44E52"}
MARKERS = {"reliability_only": "o", "bpso_rata_la": "s", "cars_aada_rcla_candidate": "^"}
LW = {"reliability_only": 1.6, "bpso_rata_la": 1.6, "cars_aada_rcla_candidate": 2.2}


def _cell(s, N, method):
    return s["per_cell"]["%s|%s" % (N, method)]


def _plot_lines(ax, s, metric_mean, metric_std=None, ylabel=None):
    for m in METHODS:
        y = [_cell(s, N, m)[metric_mean] for N in GRID]
        if metric_std:
            e = [_cell(s, N, m)[metric_std] for N in GRID]
            ax.errorbar(GRID, y, yerr=e, fmt="none", ecolor=COLORS[m], alpha=0.4, capsize=2)
        ax.plot(GRID, y, marker=MARKERS[m], ms=5, lw=LW[m],
                color=COLORS[m], label=LABELS[m])
    ax.set_xticks(GRID)
    ax.set_xlabel(r"Workload $N$")
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)


def main() -> int:
    s = json.load(open(SUMMARY_PATH, encoding="utf-8"))
    os.makedirs(FIG_DIR, exist_ok=True)

    # ---- Fig E0-1: Load-response performance ----
    fig, axes = plt.subplots(1, 3, figsize=(13.0, 3.6))
    _plot_lines(axes[0], s, "TSSR_mean", "TSSR_std", ylabel="TSSR")
    axes[0].set_title("(a) TSSR")
    axes[0].set_ylim(0.60, 1.02)
    _plot_lines(axes[1], s, "Rbar_eff_mean", ylabel=r"$\bar R_{\mathrm{eff}}$")
    axes[1].set_title("(b) " + r"$\bar R_{\mathrm{eff}}$")
    _plot_lines(axes[2], s, "Ubar_eff_mean", ylabel=r"$\bar U_{\mathrm{eff}}$")
    axes[2].set_title("(c) " + r"$\bar U_{\mathrm{eff}}$")
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(FIG_DIR, "Fig_E0_1.%s" % ext), dpi=200)
    print("written:", os.path.join(FIG_DIR, "Fig_E0_1.png/.pdf"))

    # ---- Fig E0-2: Reliability-resource mechanism ----
    fig2, axes2 = plt.subplots(1, 3, figsize=(13.0, 3.6))
    _plot_lines(axes2[0], s, "V_R_mean", ylabel="$V_R$")
    axes2[0].set_title("(a) $V_R$")
    axes2[0].set_ylim(-0.01, 0.30)
    _plot_lines(axes2[1], s, "V_F_median", ylabel="$V_F$")
    axes2[1].set_title("(b) $V_F$")
    axes2[1].set_ylim(-0.01, 0.50)
    _plot_lines(axes2[2], s, "max_G_over_F_median", ylabel=r"$\max G/F$")
    axes2[2].set_title("(c) " + r"$\max G/F$")
    axes2[2].set_ylim(0.0, 1.6)
    fig2.tight_layout()
    for ext in ("png", "pdf"):
        fig2.savefig(os.path.join(FIG_DIR, "Fig_E0_2.%s" % ext), dpi=200)
    print("written:", os.path.join(FIG_DIR, "Fig_E0_2.png/.pdf"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
