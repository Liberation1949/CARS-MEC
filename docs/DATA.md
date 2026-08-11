# Data Availability 数据可用性

## 1. 本仓库不随附第三方原始数据 No third-party raw data bundled

本公开仓库**不分发任何第三方原始/处理 Trace 数据**。`data/` 目录在本仓库中仅包含说明文件（本文件），不包含数据文件。

This public repository **does not distribute any third-party raw/processed Trace data**. The `data/` directory in this repository contains only documentation (this file), no data files.

CARS 论文实验使用了以下外部 Trace（来源与官方获取方式需由论文作者提供并经官方核验；**本仓库不提供未经核验的下载 URL**）：

The CARS paper experiments used the following external traces (sources and official access procedures must be provided and verified by the paper authors; **this repository provides no unverified download URLs**):

| 数据集 Dataset | 在论文实验中的角色 Role in paper experiments |
|--------|-------------------|
| Microsoft Azure Functions Trace 2019 | 工作负载动态结构驱动 / drives workload-dynamics structure |
| NEP Edge Workloads Traces | 后台 CPU 压力驱动（其 workload 字段全 0，真实信号为 cpu_pressure）/ drives background CPU pressure (its workload field is all zeros; the real signal is cpu_pressure) |
| Shanghai Telecom Mobile Internet Access Trace | 时间维度工作负载动态驱动 / drives temporal workload dynamics |

## 2. 数据在论文中的证据地位 Evidence Status in the Paper

Trace 增强实验属于 **trace-enhanced / semi-synthetic 证据**：Trace 只提供外生动态结构，场景在共享物理模型上由确定性生成器构造（容量缩放等映射在论文实验设置中说明）。本实验**不构成**真实 MEC 生产部署或真实系统验证。

Trace-enhanced experiments constitute **trace-enhanced / semi-synthetic evidence**: traces only provide exogenous dynamic structure, and scenarios are constructed by deterministic generators on the shared physical model (mappings such as capacity scaling are described in the paper's experimental setup). These experiments do **not** constitute real MEC production deployment or real-system validation.

## 3. 期望数据目录结构 Expected Data Directory Layout

复现 Trace 增强实验时，用户需自行从原始提供方取得数据，并按如下结构放置（可用环境变量 `CARS_DATA_ROOT` 指向数据根目录；配置中的 `${CARS_DATA_ROOT}` 占位符表示该根目录）：

To reproduce Trace-enhanced experiments, users must obtain the data themselves from the original providers and place it as follows (the environment variable `CARS_DATA_ROOT` may point to the data root; the `${CARS_DATA_ROOT}` placeholder in configs refers to that root):

```text
<CARS_DATA_ROOT>/
├── Microsoft Azure Functions Trace 2019/
├── NEP EdgeWorkloadsTraces/
└── Shanghai Telecom Mobile Internet Access Trace/
```

- processed Trace（预处理产物）当前**不随源码分发**； / processed traces (preprocessing artifacts) are currently **not distributed with the source**;
- 预处理/字段映射规则见 `configs/e4_v2/e4_v2_trace_field_mapping.yaml` 与 `e4_v2_trace_input_manifest.yaml`（manifest 中记录各数据集文件清单与字段语义状态）。 / preprocessing/field-mapping rules are in `configs/e4_v2/e4_v2_trace_field_mapping.yaml` and `e4_v2_trace_input_manifest.yaml` (the manifest records each dataset's file inventory and field-semantics status).

## 4. 数据使用边界 Data Usage Boundaries

- 未经数据集提供方许可，不得将原始数据再分发； / raw data must not be redistributed without the dataset provider's permission;
- 复现结果仅作为 trace-enhanced / semi-synthetic 证据，不得表述为真实系统验证； / reproduced results are trace-enhanced / semi-synthetic evidence only and must not be described as real-system validation;
- 正式实验的 formal-test 数据划分规则冻结于各实验协议中（`configs/e4_v2/`、`configs/e3_v2/` 等），复现时必须遵守训练/校准/正式测试分区互斥。 / formal-test data-split rules are frozen in the experiment protocols (`configs/e4_v2/`, `configs/e3_v2/`, etc.); the training/calibration/formal-test partition exclusivity must be respected when reproducing.

## 5. 无 Trace 数据的复现范围 Reproduction Scope without Trace Data

不依赖外部 Trace 的正式实验（E0 负载扩展、E1 任务规模与异构资源、E2 组件消融、E4 Exact-Oracle 参照）不要求外部数据，可完整复现；依赖 Trace 的实验（Trace 增强外部有效性评估）需要按上文获取数据。

Formal experiments that do not depend on external traces (E0 load scaling, E1 task scale and heterogeneity, E2 component ablation, E4 Exact-Oracle reference) require no external data and can be fully reproduced; Trace-dependent experiments (Trace-enhanced external-validity evaluation) require obtaining the data as described above.
