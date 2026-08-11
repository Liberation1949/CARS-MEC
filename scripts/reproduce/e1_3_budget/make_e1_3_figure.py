# -*- coding: utf-8 -*-
"""E1-3 Stage 3：主图（Figure E1-3 Performance–Runtime Tradeoff）+ 主表（Table E1-3）。

严格按 Stage-2 冻结统计计划输出：
  - 1 张主图：x=T_alg(ms)，y=TSSR；BPSO 与 NFA 各一条 budget trajectory
    （0.5×→1×→2×→4×）+ CARS 固定 reference point；
  - 1 张紧凑表：Method | Budget | TSSR | Rbar_eff | U_eff | T_alg | Consumed | Timeout/Failure。

数据源：results/e1_3_budget/budget_formal/formal_summary.json（正式 mean±std）。
输出：results/e1_3_budget/budget_formal/figures/Fig_E1_3.png + table_e1_3.csv
"""
from __future__ import annotations

import csv
import json
import os

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SUMMARY = os.path.join(_PROJECT, "results", "e1_3_budget", "budget_formal", "formal_summary.json")
FIG_DIR = os.path.join(_PROJECT, "results", "e1_3_budget", "budget_formal", "figures")
FIG_PATH = os.path.join(FIG_DIR, "Fig_E1_3.png")
TABLE_PATH = os.path.join(_PROJECT, "results", "e1_3_budget", "budget_formal", "table_e1_3.csv")

MULTS = [0.5, 1.0, 2.0, 4.0]
METHODS = ["bpso_rata_la", "nfa_adapted"]
METHOD_LABEL = {"bpso_rata_la": "BPSO-RATA-LA", "nfa_adapted": "NFA", "cars": "CARS"}


def main() -> int:
    s = json.load(open(SUMMARY, encoding="utf-8"))
    os.makedirs(FIG_DIR, exist_ok=True)

    # ---- 主表 ----
    rows = []
    for method in METHODS:
        for mult in MULTS:
            q = s["per_method_per_multiplier"][method][str(mult)]
            rows.append({
                "Method": METHOD_LABEL[method], "Budget": "%g×" % mult,
                "TSSR": "%.3f±%.3f" % (q["tssr"], q["tssr_std"]),
                "Rbar_eff": "%.4f" % q["rbar_eff"], "Ubar_eff": "%.4f" % q["ubar_eff"],
                "T_alg(ms)": "%.1f" % q["t_alg_ms"],
                "Consumed": ("%.0f" % q["consumed"]) if q["consumed"] is not None else "-",
                "Timeout/Failure": "%d/%s" % (q["timeout"], ",".join(q["status"])),
            })
    c = s["cars_reference"]
    rows.append({
        "Method": "CARS", "Budget": "fixed",
        "TSSR": "%.3f±%.3f" % (c["tssr"], c["tssr_std"]),
        "Rbar_eff": "%.4f" % c["rbar_eff"], "Ubar_eff": "%.4f" % c["ubar_eff"],
        "T_alg(ms)": "%.1f" % c["t_alg_ms"], "Consumed": "-",
        "Timeout/Failure": "%d/%s" % (c["timeout"], ",".join(c["status"])),
    })
    with open(TABLE_PATH, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("Table E1-3 ->", TABLE_PATH, "(%d rows)" % len(rows))

    # ---- 主图 ----
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:  # 无 matplotlib 时仅输出数据
        print("matplotlib 不可用：%s（主图数据见 table/summary）" % e)
        return 0

    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    colors = {"bpso_rata_la": "#1f77b4", "nfa_adapted": "#d62728", "cars": "#2ca02c"}
    markers = {"bpso_rata_la": "o", "nfa_adapted": "s", "cars": "D"}
    for method in METHODS:
        xs, ys = [], []
        for mult in MULTS:
            q = s["per_method_per_multiplier"][method][str(mult)]
            xs.append(q["t_alg_ms"])
            ys.append(q["tssr"])
        ax.plot(xs, ys, marker=markers[method], color=colors[method],
                label="%s" % METHOD_LABEL[method], linewidth=1.8)
        for mult, x, y in zip(MULTS, xs, ys):
            ax.annotate("%g×" % mult, (x, y), textcoords="offset points",
                        xytext=(6, 5), fontsize=8, color=colors[method])
    # NFA 4×：9/10 timeout 失真标注（仅 1/10 完成，质量值不可靠）
    n4 = s["per_method_per_multiplier"]["nfa_adapted"]["4.0"]
    ax.annotate("NFA 4×: %d/10 TIMEOUT\n(unreliable)" % n4["timeout"],
                (n4["t_alg_ms"], n4["tssr"]), textcoords="offset points",
                xytext=(8, -18), fontsize=8, color=colors["nfa_adapted"],
                bbox=dict(boxstyle="round,pad=0.3", fc="lightyellow", ec="gray", alpha=0.8))
    ax.scatter([c["t_alg_ms"]], [c["tssr"]], marker=markers["cars"], color=colors["cars"],
               s=90, zorder=5, label="CARS (fixed reference)")
    ax.set_xlabel("Algorithm runtime $T_{\\rm alg}$ (ms)")
    ax.set_ylabel("TSSR")
    ax.set_title("E1-3: Performance–Runtime Tradeoff under Baseline Budget Scaling")
    ax.set_xscale("log")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(loc="lower left")
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=200)
    print("Figure E1-3 ->", FIG_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
