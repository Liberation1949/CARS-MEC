# -*- coding: utf-8 -*-
"""Exact Oracle（E4-EXACT-1；Small-Scale Exact-Oracle 的 reference solver）。

参考依据：E4_EXACT_ORACLE_CONTRACT_V1（E4-EXACT-0 冻结）、
experiment_docs/III_VII.md IV 章（P0）、CARS_EXECUTABLE_THEORY_CONTRACT_V4、
CARS_ACTIVE_SCHEMA_V4、统一 Evaluator（src/cars/evaluator）。

Oracle 不是论文 baseline，而是 reference solver：
对极小实例返回 P0 在 Omega_phy 上的 lexicographic global optimum（或
CERTIFIED_NUMERICAL_EXACT），并附 exactness certificate。

本模块不修改任何公共模型/Evaluator/CARS；不读取 CARS 输出。

模块入口为 `cars.exact_oracle.oracle.solve_exact`（惰性导入；避免包初始化循环）。
"""
