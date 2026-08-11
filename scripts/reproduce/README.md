# reproduce/ — 正式实验复现脚本

本目录按实验组织复现脚本（run / aggregate / integrity / figure）。使用前先 `python -m pip install -e .`。

| 目录 | 实验 | 说明 |
|------|------|------|
| `e0_v2/` | E0 负载诱导服务退化与机制表征 | `run_e0_v2_pilot.py` / `run_e0_v2_2_formal.py` |
| `e1_v2/` | E1 任务规模增长下的性能与可扩展性 | `run_e1_v2_0_calibration.py` / `run_e1_v2_1_formal.py` |
| `e2_v2/` | E1 子实验二：异构计算资源下的服务鲁棒性 | `run_e2_v2_0_calibration.py` / `run_e2_v2_1_formal.py` |
| `e3_v2/` | E2 组件消融与机制分析 | `run_e3_v2_1_pilot.py` / `run_e3_v2_2_formal.py` |
| `e4_v2/` | E3 Trace 增强外部有效性评估（需外部数据） | `run_e4_v2_1_pilot.py` / `run_e4_v2_2_formal.py`；数据见 docs/DATA.md |
| `e4_exact/` | E4 小规模精确最优参照（Exact Oracle） | `run_e4_exact_1_validation.py` / `run_e4_exact_2_pilot.py` / `run_e4_exact_3_formal.py` |

通用说明：

- 正式运行脚本带 `--authorize-formal-seeds` 守卫，仅显式授权后才访问 formal-test seed 分区；
- `make_*_figure.py` 生成论文图表（需要 matplotlib）；
- `check_*_integrity.py` 对正式结果做完整性校验；
- 完整复现说明见 [docs/REPRODUCIBILITY.md](../../docs/REPRODUCIBILITY.md)。
