# -*- coding: utf-8 -*-
"""E2-V2-1 图表生成（图表合同：2 图；E2_V2_FORMAL_PROTOCOL_V1 §8）。

Fig E2-1：x=CV_F，三 panel (a) TSSR / (b) Rbar_eff / (c) Ubar_eff；7 方法 mean±std
  （读 results/e2_v2/e2_v2_1_formal/summary_formal.json）。
Fig E2-2：x=CV_F，三 panel (a) HHI_F / (b) F_max/F_min / (c) edge ratio
  （读 results/e2_v2/e2_v2_0_calibration/environment_diagnostics.json 的 N=170
  Layer A 环境级结构量：HHI=capacity_HHI，max/min=max_min_ratio，
  edge ratio=edge_feasible_ratio——均不依赖任何算法最终指派；
  依据 CR-THEORY-E2-CORRECTION 3J，移除 LI_dem/max rho_dem 方法相关量）。

用法：
  python scripts/reproduce/e2_v2/make_e2_v2_figure.py [--out-dir DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT_DIR = os.path.join(_PROJECT, "results", "e2_v2", "e2_v2_1_formal")
DIAG_PATH = os.path.join(_PROJECT, "results", "e2_v2", "e2_v2_0_calibration",
                         "environment_diagnostics.json")

CV_GRID = [0.0, 0.3, 0.6, 0.9, 1.2]
CV_LABELS = {0.0: "0.0", 0.3: "0.3", 0.6: "0.6", 0.9: "0.9", 1.2: "1.2"}
METHODS = ["cars", "bpso_rata_la", "jtora_adapted", "nfa_adapted",
           "reliability_only", "local_only", "foa"]
STYLE = {"cars": ("CARS", "b-", "o"), "bpso_rata_la": ("BPSO-RATA-LA", "g--", "s"),
         "jtora_adapted": ("JTORA", "m--", "^"), "nfa_adapted": ("NFA", "r-.", "D"),
         "reliability_only": ("Reliability-only", "c-.", "v"),
         "local_only": ("Local-only", "y--", "x"), "foa": ("FOA", "k:", "p")}


def _cv_key(cv):
    return ("%.1f" % cv).rstrip("0").rstrip(".") if cv != 0.0 else "0"


def make_fig_e2_1(summary, out_dir):
    # 2026-08-10 用户反馈：原图例在 (a) TSSR 面板内部（ax.legend ncol=2）遮挡曲线。
    # → 图例移出面板，改为单行（ncol=7）横放于三 panel 上方，顶部预留空间不重叠。
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.2))
    metrics = [("tssr", "TSSR"), ("rbar_eff", r"$\bar{R}_{\mathrm{eff}}$"),
               ("ubar_eff", r"$\bar{U}_{\mathrm{eff}}$")]
    for ax, (met, ylabel) in zip(axes, metrics):
        for m in METHODS:
            label, fmt, marker = STYLE[m]
            xs, ys = [], []
            for cv in CV_GRID:
                cell = summary[_cv_key(cv)].get(m, {})
                mu = (cell.get(met, {}) or {}).get("mean")
                if mu is not None:
                    xs.append(cv)
                    ys.append(mu)
            if xs:
                ax.plot(xs, ys, fmt, marker=marker, label=label, markersize=4)
        ax.set_xlabel(r"$CV_F$")
        ax.set_ylabel(ylabel)
        ax.set_xticks(CV_GRID)
        ax.grid(alpha=0.3)
    # 单行图例：从单一 panel 取唯一 handles/labels（避免 fig.legend 收集三 panel 重复项）
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 1.0),
               ncol=len(METHODS), fontsize=8, frameon=True, columnspacing=1.2)
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(out_dir, "Fig_E2_1." + ext), dpi=200)
    plt.close(fig)
    print("written: Fig_E2_1.png/.pdf")


def make_fig_e2_2(diag, out_dir):
    la = diag.get("layer_a", {})
    # N=170 的 key 为 "n170_cv0.0" 等
    def get(cv, field):
        cell = la.get("n170_cv%s" % ("%.1f" % cv))
        return (cell or {}).get(field)

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.6))
    panels = [
        ("hhi", lambda cv: get(cv, "capacity_HHI"), r"$HHI_F$"),
        ("max_min", lambda cv: get(cv, "max_min_ratio"), r"$F_{\max}/F_{\min}$"),
        ("edge_ratio", lambda cv: get(cv, "edge_feasible_ratio"), "recoverable-edge ratio"),
    ]
    for ax, (name, fn, ylabel) in zip(axes, panels):
        xs = [cv for cv in CV_GRID if fn(cv) is not None]
        ys = [fn(cv) for cv in xs]
        ax.plot(xs, ys, "b-o", markersize=5)
        ax.set_xlabel(r"$CV_F$")
        ax.set_ylabel(ylabel)
        ax.set_xticks(CV_GRID)
        ax.grid(alpha=0.3)
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(out_dir, "Fig_E2_2." + ext), dpi=200)
    plt.close(fig)
    print("written: Fig_E2_2.png/.pdf")


def main() -> int:
    ap = argparse.ArgumentParser(description="E2-V2-1 图表生成")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()
    out_dir = args.out_dir or OUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    summary_path = os.path.join(out_dir, "summary_formal.json")
    if os.path.exists(summary_path):
        summary = json.load(open(summary_path, encoding="utf-8"))["summary"]
        make_fig_e2_1(summary, out_dir)
    else:
        print("warning: %s not found — Fig E2-1 skipped（formal 结果未生成）" % summary_path)

    if os.path.exists(DIAG_PATH):
        diag = json.load(open(DIAG_PATH, encoding="utf-8"))
        make_fig_e2_2(diag, out_dir)
    else:
        print("warning: %s not found — Fig E2-2 skipped" % DIAG_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
