# Changelog 更新日志

## 1.0.4 — E1.3 Baseline Budget Sensitivity Reproducibility 复现补齐

- Added the E1.3 baseline budget-sensitivity reproduction entry: scenario construction → pilot → formal → aggregation → figure → reference summary; / 新增 E1.3 基线预算敏感性复现入口：场景重建 → pilot → formal → 聚合 → 出图 → 参考摘要；
- New: `configs/e1_3_budget/`, `scripts/reproduce/e1_3_budget/`, `tests/e1_3_budget/`, `reference_results/E1_3_budget_sensitivity/`; / 新增上述目录；
- Formal run requires the explicit `--authorize-formal-seeds` opt-in flag (local guard against accidental runs, not an access control); / formal 运行需显式 `--authorize-formal-seeds` opt-in 标志（本地防误运行，非访问控制）；
- No algorithm, evaluator, schema, or formal-config changes. / 无算法、Evaluator、Schema 或正式配置改动。

## 1.0.3 — Positive Method Description 正面描述方法

- Rewrote method-scope wording to describe what CARS is (AADA → RCLA) instead of negating components readers never heard of; / 将方法范围表述改为正面描述（AADA → RCLA），不再否定读者未知的组件。

## 1.0.2 — Reader-Friendly Documentation Wording 面向读者的措辞外化

- Externalized insider terminology in README and docs for outside readers (no logic change); / 外化 README 与文档中的内部术语，面向外部读者（无逻辑改动）。

## 1.0.1 — Bilingual Documentation & Comment Cleanup 双语文档与注释整理

- All public documentation (README, docs/, CHANGELOG, CITATION template, data/reference_results/reproduce READMEs) made bilingual (Chinese + English); / 全部公开文档（README、docs/、CHANGELOG、CITATION 模板、data/reference_results/reproduce README）改为中英双语；
- Reworded a few comments to a more natural style (no logic change); / 少量注释措辞改为更自然的风格（无逻辑改动）；
- Logical behavior, algorithms, evaluator, schemas, and formal configs unchanged. / 逻辑行为、算法、Evaluator、Schema 与正式配置均未改动。

## 1.0.0 — Initial Paper Release 论文首发版

- CARS implementation with AADA (Allocation-Aware Dynamic Assignment) and RCLA (Reliability-Constrained Lagrangian Allocation); / CARS 实现，含 AADA（分配感知动态指派）与 RCLA（可靠性约束拉格朗日分配）；
- Six comparison methods: BPSO-RATA-LA, JTORA-adapted, NFA-adapted (independent reimplementations), reliability_only, local_only, FOA; / 六个对比方法：BPSO-RATA-LA、JTORA-adapted、NFA-adapted（独立重实现）、reliability_only、local_only、FOA；
- Active Schema V4; / Active Schema V4；
- Small-Scale Exact Oracle evaluation support; / Small-Scale Exact Oracle 评估支持工具；
- Reproducibility scripts (`scripts/reproduce/`); / 复现脚本（`scripts/reproduce/`）；
- Lightweight machine-readable reference results (`reference_results/`); / 轻量机器可读参考结果（`reference_results/`）；
- Quick Start (`scripts/quick_start.py`). / 快速开始（`scripts/quick_start.py`）。
