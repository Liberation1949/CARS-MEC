# -*- coding: utf-8 -*-
"""E4-V2-2 正式图表（2 图候选：Fig E4-1 服务性能 / Fig E4-2 quality-efficiency）。

数据来源：results/e4_v2/e4_v2_2_formal/summary_formal.json（正式均值）。
Fig E4-1：3 panel（azure/nep/shanghai），横轴 regime（LOW→TRANSITION→HIGH；
  shanghai 仅 LOW/HIGH），纵轴 TSSR，主方法折线。
Fig E4-2：quality-efficiency（x=method_runtime_ms 对数，y=TSSR），HIGH regime，
  方法 CARS/BPSO/JTORA/NFA（弱基线近零 runtime 不入图，表保留，图题说明）。

生成 png + pdf。禁止制造大量重复图表。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT_DIR = os.path.join(_PROJECT, "results", "e4_v2", "e4_v2_2_formal")
FIG_DIR = os.path.join(OUT_DIR, "figures")

MAIN_METHODS = ["cars", "bpso_rata_la", "jtora_adapted", "nfa_adapted",
                "reliability_only", "local_only"]
REGIME_ORDER = {"LOW": 0, "TRANSITION": 1, "HIGH": 2}
METHOD_LABEL = {
    "cars": "CARS", "bpso_rata_la": "BPSO-RATA-LA", "jtora_adapted": "JTORA",
    "nfa_adapted": "NFA", "reliability_only": "reliability-only", "local_only": "local-only",
}


def main() -> int:
    ap = argparse.ArgumentParser(description="E4-V2-2 figures")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()
    global OUT_DIR, FIG_DIR
    if args.out_dir:
        OUT_DIR = args.out_dir
        FIG_DIR = os.path.join(OUT_DIR, "figures")
    os.makedirs(FIG_DIR, exist_ok=True)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    summary = json.load(open(os.path.join(OUT_DIR, "summary_formal.json"), encoding="utf-8"))

    # ---------------- Fig E4-1：服务性能（TSSR vs regime，3 panel） ----------------
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), sharey=True)
    for ax, ds in zip(axes, ["azure", "nep", "shanghai"]):
        byreg = summary.get(ds, {})
        regs = sorted(byreg, key=lambda r: REGIME_ORDER.get(r, 9))
        xs = list(range(len(regs)))
        for m in MAIN_METHODS:
            ys = []
            for r in regs:
                e = byreg[r].get(m, {}).get("tssr", {}).get("mean")
                ys.append(e if e is not None else None)
            ax.plot(xs, ys, marker="o", label=METHOD_LABEL[m], linewidth=1.6)
        ax.set_title(ds.upper())
        ax.set_xticks(xs)
        ax.set_xticklabels(regs)
        ax.grid(alpha=0.3)
        if ds == "azure":
            ax.set_ylabel("TSSR")
        ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "Fig_E4_1.png"), dpi=200)
    fig.savefig(os.path.join(FIG_DIR, "Fig_E4_1.pdf"))
    plt.close(fig)

    # ---------------- Fig E4-2：quality–efficiency（HIGH regime，v3 重画） ----------------
    # 设计：方法=颜色，数据集=marker；误差棒为 TSSR std（y）+ runtime std（x，log 非对称）；
    # 无箭头注释；方法图例=颜色圆点、Trace 图例=灰色形状，均置于图外右侧不遮挡数据。
    # 数据仍为 summary_formal 正式均值。
    from matplotlib.lines import Line2D

    ds_order = ["azure", "nep", "shanghai"]
    ds_marker = {"azure": "o", "nep": "^", "shanghai": "s"}
    ds_label = {"azure": "Azure", "nep": "NEP", "shanghai": "Shanghai"}
    m_color = {"cars": "#c0392b", "bpso_rata_la": "#16a085",
               "jtora_adapted": "#8e44ad", "nfa_adapted": "#e67e22"}
    m_size = {"cars": 150, "bpso_rata_la": 95, "jtora_adapted": 95, "nfa_adapted": 95}
    qe_methods = ["cars", "bpso_rata_la", "jtora_adapted", "nfa_adapted"]

    fig, ax = plt.subplots(figsize=(11.0, 6.0))

    for m in qe_methods:
        for ds in ds_order:
            e = summary.get(ds, {}).get("HIGH", {})
            rt = e.get(m, {}).get("method_runtime_ms", {}).get("mean")
            rt_std = e.get(m, {}).get("method_runtime_ms", {}).get("std")
            t = e.get(m, {}).get("tssr", {}).get("mean")
            t_std = e.get(m, {}).get("tssr", {}).get("std")
            if rt is None or t is None:
                continue
            lo = max(rt - rt_std, 0.5)
            hi = rt + rt_std
            ax.errorbar(rt, t, yerr=t_std, xerr=[[rt - lo], [hi - rt]],
                        fmt="none", ecolor=m_color[m], elinewidth=1.0,
                        capsize=2.5, alpha=0.6, zorder=2)
            ax.scatter(rt, t, s=m_size[m], marker=ds_marker[ds], color=m_color[m],
                       edgecolors="white", linewidths=0.9, zorder=3)

    # 100 ms 在线参考阈值
    ax.axvline(100.0, color="gray", linestyle="--", linewidth=1.0, alpha=0.7)

    ax.set_xscale("log")
    ax.set_xlim(5.0, 2.5e4)
    ax.set_ylim(0.70, 1.01)
    ax.set_xlabel("Algorithm runtime $T_{\\mathrm{alg}}$ (ms, log scale)", fontsize=11.5)
    ax.set_ylabel("TSSR (HIGH regime)", fontsize=11.5)
    ax.grid(alpha=0.25, which="both", linestyle=":")

    # 显式预留右侧图例区（axes 占左 70%），图例置于预留区，避免被画布边缘裁剪
    fig.subplots_adjust(left=0.10, right=0.70, top=0.94, bottom=0.11)

    # 方法图例（颜色，圆点示例）
    m_handles = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=m_color[m],
               markeredgecolor="white", markersize=9, label=METHOD_LABEL[m])
        for m in qe_methods]
    leg_m = ax.legend(handles=m_handles, loc="upper left", bbox_to_anchor=(1.06, 1.0),
                      fontsize=9.5, frameon=True, title="Method", title_fontsize=9.5,
                      borderaxespad=0.4)
    ax.add_artist(leg_m)

    # Trace 图例（形状，灰色示例）
    ds_handles = [
        Line2D([0], [0], marker=ds_marker[ds], color="w", markerfacecolor="#7f8c8d",
               markeredgecolor="white", markersize=9, label=ds_label[ds])
        for ds in ds_order]
    ax.legend(handles=ds_handles, loc="lower left", bbox_to_anchor=(1.06, 0.42),
              fontsize=9.5, frameon=True, title="Trace", title_fontsize=9.5,
              borderaxespad=0.4)

    fig.savefig(os.path.join(FIG_DIR, "Fig_E4_2.png"), dpi=200)
    fig.savefig(os.path.join(FIG_DIR, "Fig_E4_2.pdf"))
    plt.close(fig)

    print("figures written:", [f for f in os.listdir(FIG_DIR)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
