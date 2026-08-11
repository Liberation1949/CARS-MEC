# reproduce/ — 正式实验复现脚本 Formal Experiment Reproduction Scripts

本目录按实验组织复现脚本（run / aggregate / integrity / figure）。使用前先 `python -m pip install -e .`。

This directory organizes reproduction scripts by experiment (run / aggregate / integrity / figure). Run `python -m pip install -e .` first.

| 目录 Directory | 实验 Experiment | 说明 Notes |
|------|------|------|
| `e0_v2/` | E0 负载诱导服务退化与机制表征 / load-induced degradation & mechanism | `run_e0_v2_pilot.py` / `run_e0_v2_2_formal.py` |
| `e1_v2/` | E1 任务规模增长下的性能与可扩展性 / performance & scalability under task-scale growth | `run_e1_v2_0_calibration.py` / `run_e1_v2_1_formal.py` |
| `e2_v2/` | E1 子实验二：异构计算资源下的服务鲁棒性 / service robustness under heterogeneous compute | `run_e2_v2_0_calibration.py` / `run_e2_v2_1_formal.py` |
| `e3_v2/` | E2 组件消融与机制分析 / component ablation & mechanism | `run_e3_v2_1_pilot.py` / `run_e3_v2_2_formal.py` |
| `e4_v2/` | E3 Trace 增强外部有效性评估（需外部数据）/ Trace-enhanced external validity (external data needed) | `run_e4_v2_1_pilot.py` / `run_e4_v2_2_formal.py`；数据见 docs/DATA.md / data in docs/DATA.md |
| `e4_exact/` | E4 小规模精确最优参照（Exact Oracle）/ small-scale exact-optimal reference | `run_e4_exact_1_validation.py` / `run_e4_exact_2_pilot.py` / `run_e4_exact_3_formal.py` |

通用说明 General notes:

- 正式运行脚本带 `--authorize-formal-seeds` 守卫，仅显式授权后才访问 formal-test seed 分区； / formal run scripts carry the `--authorize-formal-seeds` guard; the formal-test seed partition is accessed only after explicit authorization;
- `make_*_figure.py` 生成论文图表（需要 matplotlib）； / `make_*_figure.py` produces paper figures (requires matplotlib);
- `check_*_integrity.py` 对正式结果做完整性校验； / `check_*_integrity.py` performs integrity checks on formal results;
- 完整复现说明见 [docs/REPRODUCIBILITY.md](../../docs/REPRODUCIBILITY.md)。 / full reproduction notes are in [docs/REPRODUCIBILITY.md](../../docs/REPRODUCIBILITY.md).
