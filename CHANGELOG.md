# Changelog 更新日志

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
