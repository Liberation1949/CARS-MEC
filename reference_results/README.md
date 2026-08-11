# reference_results

轻量机器可读参考结果摘要，从既有冻结正式实验提取（OS1），数值不随本仓库重新计算。

## 内容

| 目录 | 正式实验 | 内容 |
|------|---------|------|
| `E0_load_induced_degradation/` | E0 负载诱导服务退化与机制表征 | formal_summary.json |
| `E1_task_scale/` | E1 任务规模增长下的性能与可扩展性 | claim_audit / paired_delta / summary / table_e1_1.csv |
| `E1b_compute_heterogeneity/` | E1 子实验二：异构计算资源鲁棒性 | claim_audit / paired_delta / summary_formal / table_e2_1.csv |
| `E2_component_ablation/` | E2 组件消融与机制分析 | formal_meta.json |
| `E3_trace_enhanced/` | E3 真实 Trace 增强外部有效性评估 | claim_audit / window manifest / paired_delta / summary / table |
| `E4_exact_oracle/` | E4 小规模精确最优参照 | formal_aggregated / formal_manifest / table_e4_exact_1.csv |

## 说明

- 数值全部来自既有正式结果；不重新计算 Claim、不重跑实验；
- **本目录不是全量 raw formal archive**，仅含聚合摘要；
- **smoke / pilot 结果不在此目录**；
- **不建议把 `reference_results/` 作为实验输入数据**——它只用于查阅论文引用数值；
- 完整逐实例结果与阶段内部报告不随本公开仓库分发；
- 复现与范围说明见 [docs/REPRODUCIBILITY.md](../docs/REPRODUCIBILITY.md)。
