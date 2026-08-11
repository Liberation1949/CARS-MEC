# reference_results 参考结果

轻量机器可读参考结果摘要，从论文既有正式实验提取，数值不随本仓库重新计算。

Lightweight machine-readable reference-result summaries, extracted from the paper's existing formal experiments; values are not recomputed in this repository.

## 内容 Contents

| 目录 Directory | 正式实验 Formal experiment | 内容 Content |
|------|---------|------|
| `E0_load_induced_degradation/` | E0 负载诱导服务退化与机制表征 / load-induced degradation & mechanism | formal_summary.json |
| `E1_task_scale/` | E1 任务规模增长下的性能与可扩展性 / performance & scalability under task-scale growth | claim_audit / paired_delta / summary / table_e1_1.csv |
| `E1b_compute_heterogeneity/` | E1 子实验二：异构计算资源鲁棒性 / robustness under heterogeneous compute | claim_audit / paired_delta / summary_formal / table_e2_1.csv |
| `E2_component_ablation/` | E2 组件消融与机制分析 / component ablation & mechanism | formal_meta.json |
| `E3_trace_enhanced/` | E3 真实 Trace 增强外部有效性评估 / real Trace-enhanced external validity | claim_audit / window manifest / paired_delta / summary / table |
| `E4_exact_oracle/` | E4 小规模精确最优参照 / small-scale exact-optimal reference | formal_aggregated / formal_manifest / table_e4_exact_1.csv |

## 说明 Notes

- 数值来自论文既有正式实验，未重新计算或重跑； / values come from the paper's existing formal experiments and are not recomputed or rerun;
- 仅含聚合摘要，不含逐实例的完整原始输出； / aggregate summaries only — full per-instance raw outputs are not included;
- smoke / pilot 结果不在此目录； / smoke / pilot results are not in this directory;
- 本目录用于查阅论文引用的数值，不作为实验输入； / this directory exists to look up values cited in the paper, not as experiment input;
- 完整逐实例结果与内部报告不随本公开仓库分发； / full per-instance results and internal reports are not distributed with this public repository;
- 复现与范围说明见 [docs/REPRODUCIBILITY.md](../docs/REPRODUCIBILITY.md)。 / see [docs/REPRODUCIBILITY.md](../docs/REPRODUCIBILITY.md) for reproduction and scope notes.
