# -*- coding: utf-8 -*-
"""CARS 方法包（CARS = AADA → RCLA；no Repair layer）。

提供 build_method(config) 工厂，供 MethodRunner worker 的 fallback 动态导入
解析（不注册到全局 MethodRegistry 单例——R3 冻结测试要求全局 Registry 恰好
六项且不含 cars/ruad/cala/repair；R4 合同 §8 registry_integration）。

模块（V4）：
- config.py：方法配置校验（AADA/RCLA 字段；拒绝 CALA/Repair/旧 RUAD 参数）
- pipeline.py：正式 CARS Pipeline（AADA → RCLA）
- method.py：CarsMethod（MethodProtocol）

"""

from __future__ import annotations

from typing import Dict

from cars.methods.cars.config import METHOD_ID  # noqa: F401
from cars.methods.cars.method import CarsMethod  # noqa: F401

__all__ = ["METHOD_ID", "CarsMethod", "build_method"]


def build_method(config: Dict) -> CarsMethod:
    """方法工厂（worker fallback 动态导入入口；R4 合同 §8）。"""
    return CarsMethod(config)
