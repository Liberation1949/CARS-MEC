# -*- coding: utf-8 -*-
"""E1-V2-1 Formal 图表生成（E1_V2_PROTOCOL_V1 §8：2 图 1 表）。

Fig_E1_1：三 panel（x=N；a=TSSR / b=Rbar_eff / c=Ubar_eff；6 正式方法 mean±std）
Fig_E1_2：x=N，y=total_wall_time_ms（端到端 runtime；log-y）；附 completion/timeout 注

输出：results/e1_v2/e1_v2_1_formal/figures/Fig_E1_1.png/.pdf + Fig_E1_2.png/.pdf
数据源：results/e1_v2/e1_v2_1_formal/summary_formal.json
"""
from __future__ import annotations

import json
import os
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT_DIR = os.path.join(_PROJECT, "results", "e1_v2", "e1_v2_1_formal")
FIG_DIR = os.path.join(OUT_DIR, "figures")

MAIN_METHODS = ["cars", "bpso_rata_la", "jtora_adapted", "nfa_adapted",
                "reliability_only", "local_only"]
NS = [20, 50, 80, 110, 140, 170, 200]
COLORS = {"cars": "#C44E52", "bpso_rata_la": "#4C72B0", "jtora_adapted": "#55A868",
          "nfa_adapted": "#8172B3", "reliability_only": "#DD8452", "local_only": "#937860"}
MARKERS = {"cars": "^", "bpso_rata_la": "s", "jtora_adapted": "D",
           "nfa_adapted": "o", "reliability_only": "v", "local_only": "P"}
LW = {"cars": 2.2, "bpso_rata_la": 1.6, "jtora_adapted": 1.6,
      "nfa_adapted": 1.8, "reliability_only": 1.6, "local_only": 1.4}


def main() -> int:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with open(os.path.join(OUT_DIR, "summary_formal.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    summary = data["summary"]
    os.makedirs(FIG_DIR, exist_ok=True)

    def series(m, key):
        return [summary[m][str(n)][key] for n in NS]

    # ---- Fig_E1_1：三 panel ----
    # 2026-08-10 用户反馈：①图例（原 loc="lower left"）遮挡 (a) TSSR 面板左下方
    # 的 reliability_only/local_only 低值曲线；②顶部居中图例（ncol=3 两行）压住
    # 三 panel 标题。→ 图例改为单行（ncol=6）横放于三个 panel 上方，不遮挡标题。
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.4), sharex=True)
    titles = {"tssr": "(a) Task Success Service Ratio $\\mathrm{TSSR}$",
              "rbar_eff": "(b) Effective Reliability $\\bar{R}_{\\mathrm{eff}}$",
              "ubar_eff": "(c) Effective Utility $\\bar{U}_{\\mathrm{eff}}$"}
    for ax, key in zip(axes, ["tssr", "rbar_eff", "ubar_eff"]):
        for m in MAIN_METHODS:
            mu = series(m, key + "_mean")
            sd = series(m, key + "_std")
            ax.errorbar(NS, mu, yerr=sd, label=m, color=COLORS[m], marker=MARKERS[m],
                        linewidth=LW[m], markersize=5, capsize=2)
        ax.set_xlabel("Task count $N$")
        ax.set_title(titles[key])
        ax.grid(alpha=0.3)
        if key == "tssr":
            ax.set_ylim(0.6, 1.02)
    # 单行图例（ncol=6）：从单一 panel 取 handles/labels（避免 fig.legend 默认
    # 收集全部 3 个 panel → 6 方法 × 3 = 18 个重复项）；横放于三 panel 上方，
    # 顶部预留 12% 高度，不遮挡标题。
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 1.0),
               ncol=len(MAIN_METHODS), fontsize=8, frameon=True, columnspacing=1.2)
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    fig.savefig(os.path.join(FIG_DIR, "Fig_E1_1.png"), dpi=200)
    fig.savefig(os.path.join(FIG_DIR, "Fig_E1_1.pdf"))
    plt.close(fig)

    # ---- Fig_E1_2：runtime（主口径 method_runtime_ms = 算法执行时间）----
    # 2026-08-09 用户要求：不绘制 reliability_only / local_only 折线
    # （其算法执行时间约 0–5 ms，为近零孤立点，属视觉噪声，掩盖有效方法间对比）
    RUNTIME_EXCLUDE = {"reliability_only", "local_only"}
    fig, ax = plt.subplots(figsize=(8, 5))
    for m in MAIN_METHODS:
        if m in RUNTIME_EXCLUDE:
            continue
        mu = series(m, "method_runtime_ms_mean")
        ax.plot(NS, mu, label=m, color=COLORS[m], marker=MARKERS[m],
                linewidth=LW[m], markersize=5)
    ax.set_xlabel("Task count $N$")
    ax.set_ylabel("Algorithm execution time (ms)")
    ax.set_yscale("log")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "Fig_E1_2.png"), dpi=200)
    fig.savefig(os.path.join(FIG_DIR, "Fig_E1_2.pdf"))
    plt.close(fig)

    print("figures written:", sorted(os.listdir(FIG_DIR)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
