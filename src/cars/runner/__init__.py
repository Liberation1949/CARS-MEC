# -*- coding: utf-8 -*-
"""CARS Runner 包（R3-NFA 最小通用 Runner）。

MethodRunner：统一 Evaluator 的唯一调用者；方法在独立子进程中执行（timeout 隔离）；
子进程超时后清理进程树；单次失败不挂起主进程；method seed 与 scenario seed 分离。
"""

from __future__ import annotations

from cars.runner.runner import MethodRunner  # noqa: F401
