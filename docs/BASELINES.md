# Baselines

本文档说明公开仓库中六个对比 Baseline 的来源、重实现性质、忠实组件、项目适配、省略部分、参数/搜索预算与公平边界。所有信息基于研究阶段冻结的 adaptation contracts（原始记录于内部报告）与正式代码。

三个强 Baseline 均为**独立重实现**（source-aligned, project-adapted），不是第三方源码的直接复制；三个强 Baseline 的原始论文 PDF（`references/*.pdf`）受版权保护，**不随本公开仓库分发**（仅保留书目引用）。

---

## 1. 强 Baseline：BPSO-RATA-LA

- **Reference**：BPSO-RATA-LA 论文（MU-MEC 卸载与调度；BPSO 搜索卸载决策 + RATA 指派 + LA 资源分配）。
- **Independent reimplementation**：是（`reports/experiments/R3_bpso_rata_la_adaptation_contract.yaml`，`source_aligned_project_adapted`）。
- **Source-faithful components**：
  - 三阶段分解：BPSO 搜索卸载决策 X（Algorithm 3）→ RATA 固定 X 生成指派 A（Algorithm 1）→ LA 固定 (X,A) 生成分配 F（Algorithm 2 / Eq.25）；fitness 只用于选择 X；
  - BPSO 速度方程 Eq.34/37/38、V 型转移函数；
  - RATA 指派：按任务脆弱性指标与服务器脆弱性排序（Theorem 1 方向）；
  - LA 闭式分配：$f^\*_{ij} = F_j \sqrt{\alpha_i f_i^{loc}} / \sum_{k \in \Gamma_j} \sqrt{\alpha_k f_k^{loc}}$。
- **Project adaptations**：
  - 传输速率使用项目共享链路原语（逐链路独立无线信道，无跨链路干扰模型）；内部 fitness 的 $t_i^{off}/E_i^{trans}$ 使用 R2 共享物理原语；
  - 原文 Table II 数值默认（图片不可提取）以测试预算内默认值替代；
  - Algorithm 1 精确指派循环（原文为图片）依据 Theorem 1 排序目标与正文 prose 冻结（`POSSIBLE_INTERPRETATION`）。
- **Omitted**：用户间干扰项、硬件 testbed、JTSP/ILRM 对比、多 MD 竞争带宽的 B/n 归一化。
- **Parameter / search budget**（TEST_ONLY_NOT_FORMAL，非调参）：`population_size_max`、`max_iterations_max`、`particle_evaluation_cap_max`、`reliability_threshold`、`inertia_weight`、`cognitive_coefficient`、`social_coefficient`；正式配置见 `configs/r6/frozen_method_configs/bpso_frozen.yaml`。
- **Fairness boundary**：与全部方法共享 scenario、seed、数据划分、派生数据规则、硬约束（统一 Evaluator C1–C6）、formal-test、timeout policy、failure accounting；不使用 CARS 私有状态；内部目标为原文系统卸载效用（最大化）；最终结果由统一 Evaluator 唯一正式评价。

## 2. 强 Baseline：JTORA-adapted

- **Reference**：JTORA 论文（联合任务卸载与资源分配；TO 卸载 + RA 资源分配分解）。
- **Independent reimplementation**：是（`R3_jtora_adaptation_contract.yaml`，`source_aligned_project_adapted`）。
- **Source-faithful components**：
  - 卸载效用 $J_u$（Eq.10）与系统目标 $J=\sum_u \lambda_u J_u$（Eq.11）方向与结构保留（$\lambda_u$ 冻结为 1）；
  - TO(14) + RA(15) 分解；RA 中 CRA(25) 完整保留（凸性、KKT、闭式 (27)/(41)、开销 (28)/(42)）；
  - TO 启发式 Algorithm 2（best-single 初始化 + remove/exchange 局部改进，(1+δ) 改进因子）；
  - $J_u<0$ 不卸载的原文规则保留。
- **Project adaptations**：
  - 传输模型物化为项目共享时延/能耗原语（固定发射功率；通信量在 CRA 子问题中为常数）；
  - 无 OFDMA 子带维度（逐链路独立带宽）；约束 (30d) 省略；
  - 服务器选择 ground set = 物理有效边；A 由最终执行位置唯一提取；
  - Algorithm 2 迭代上界 `max_outer_iterations` 封顶（原文无显式上界，`IMPLEMENTATION_SPEC_GAP`）。
- **Omitted**：UPA 功率优化（生产路径 `binary_search_calls=0`，发射功率固定）、子带调度维度、小区间干扰、服务商偏好参数。
- **Parameter / search budget**（TEST_ONLY_NOT_FORMAL）：`max_outer_iterations`（tiny 5 / small 30）、`max_binary_search_iterations`（32/64）、`absolute_tolerance`（1e-8）、`relative_tolerance`（1e-7）、`improvement_factor_delta`、`soft_deadline_margin`、`hard_timeout_seconds`。
- **Fairness boundary**：共享全部执行边界；不读取可靠性阈值/服务器故障率/Q/Z/ρ；不调用统一 Evaluator 作为内部目标；内部目标 = 原文时延-能耗（Eq.10/29）；最终结果由统一 Evaluator 唯一正式评价。

## 3. 强 Baseline：NFA-adapted

- **Reference**：NFA 论文（萤火虫算法 + 复合启发式的任务调度）。
- **Independent reimplementation**：是（`R3_NFA_adaptation_contract.yaml`，`source_aligned_project_adapted`）。
- **Source-faithful components**：
  - 萤火虫位置为 N 维实数元组；距离型映射算子 Algorithm 1（$p=\min(e^{-r^\*_i},0.95)$，Step1 继承 + Step2 均匀插入）；
  - 移动方程 Eq.(14)（β₀, γ, 欧氏距离, 随机化），逐维应用；
  - 亮度方向：解越好亮度越高（原文 $I_i=1/f(\pi_i)$，f=最小化 makespan；项目适配为 P0 字典序元组）；
  - Algorithm 3 控制流（随机选最亮 → 初始评价 → while 代循环双循环 i,j → 移动+重映射+重评价+更新 best-so-far）；
  - Composite heuristic Algorithm 2（LTF → IRM → SSM，while Improved）；参数 β₀=1、γ=2、position_bounds=[-2,2]、p≤0.95。
- **Project adaptations**：
  - FTA 无伪代码（原文仅引用 [5]）→ 以"确定性贪心 QoS 感知列表调度"替代其"任务序列→调度方案"角色；
  - 内部目标由 makespan 标量适配为 MU-MEC 的 P0 字典序元组 (z_count, ΣRⁱᵛᵃˡⁱᵈ, ΣUⁱᵉᶠᶠ)（保持"更亮=更优"身份）；
  - LTF 排序依据：任务本地执行时延 $T_i^{loc}$ 降序（并列按任务编号升序）；
  - 位置移动后逐维 clamp 到 position_bounds。
- **Omitted**：FTA 具体内部算法、原文预算/私有云资源约束、移动随机化参数 α（原文 IV-D 同，仅登记）。
- **Parameter / search budget**（TEST_ONLY_NOT_FORMAL）：`population_size`（tiny 4 / small 8）、`max_generations`（3/10）、`beta_0`（1）、`gamma`（2）、`position_bounds`（[-2,2]）、`objective_evaluation_cap`（128/2048）、`soft_deadline_margin`、`hard_timeout_seconds`。
- **Fairness boundary**：共享全部执行边界；不使用 CARS 私有状态；无隐藏 Gate/Repair；不加额外可行性信息；最终结果由统一 Evaluator 产生。

## 4. 弱 Baseline 与边界诊断

- **reliability_only**：仅依据可靠性导向的保守决策（弱 Baseline）。
- **local_only**：全部任务本地执行（negative control；用于反证环境存在边缘资源异构性）。
- **FOA**：边界诊断方法（非正式对比对象）。

## 5. 公共公平边界（所有方法共享）

所有方法共享：scenario、seed、raw-data split、derived-data rules、硬约束（统一 Evaluator C1–C6）、formal-test、timeout policy、hardware budget、failure accounting。禁止只调优 CARS、给 CARS 单独预处理或额外可行性信息、隐藏 timeout/异常/不可行结果、使用不同 formal-test 或资源预算。
