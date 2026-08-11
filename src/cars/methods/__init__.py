# -*- coding: utf-8 -*-
"""CARS 方法包（R3 方法框架；R3-NFA / R3-REL / R3-LOCAL / R3-BPSO / R3-JTORA / R3-FOA 扩展）。

本包承载：
- MethodProtocol / MethodContext / MethodProposal（protocol.py）
- MethodRegistry（registry.py）
- nfa_adapted/（R3-NFA 注册：强 Baseline）
- reliability_only（R3-REL 注册：弱 Baseline PROJECT_DEFINED_WEAK_BASELINE）
- local_only（R3-LOCAL 注册：弱 Baseline 本地执行边界参考）
- bpso_rata_la/（R3-BPSO 注册：强 Baseline）
- jtora_adapted/（R3-JTORA 注册：强 Baseline）
- foa（R3-FOA 注册：边界诊断，project_defined 全卸载边界）

Method 只生成 X/A/F 与方法诊断；统一 Evaluator 仅由 MethodRunner 调用
（runner 包）。导入本包即触发全部注册。
"""

from __future__ import annotations

from cars.methods import protocol  # noqa: F401
from cars.methods import registry  # noqa: F401
from cars.methods import nfa_adapted  # noqa: F401  (触发注册)
from cars.methods import reliability_only  # noqa: F401  (触发注册)
from cars.methods import local_only  # noqa: F401  (触发注册)
from cars.methods import bpso_rata_la  # noqa: F401  (触发注册)
from cars.methods import jtora_adapted  # noqa: F401  (触发注册)
from cars.methods import foa  # noqa: F401  (触发注册)
from cars.methods import cars  # noqa: F401  (R4：CARS 方法包；不注册全局单例)
