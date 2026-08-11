# -*- coding: utf-8 -*-
"""最小方法注册表（R3-NFA 冻结；仅注册 nfa_adapted）。

MethodRegistry：method_id -> factory(config) -> MethodProtocol 实例。
当前白名单仅 nfa_adapted（AGENTS.md §10：其他 Baseline 留后续子阶段）。
"""

from __future__ import annotations

from typing import Callable, Dict, List

MethodFactory = Callable[[dict], object]


class MethodRegistry:
    """方法注册表（进程内单例语义由模块级 get_registry() 提供）。"""

    def __init__(self) -> None:
        self._factories: Dict[str, MethodFactory] = {}

    def register(self, method_id: str, factory: MethodFactory) -> None:
        if not isinstance(method_id, str) or not method_id:
            raise ValueError("method_id must be a non-empty string")
        if method_id in self._factories:
            raise ValueError("method %r already registered" % (method_id,))
        self._factories[method_id] = factory

    def has(self, method_id: str) -> bool:
        return method_id in self._factories

    def get(self, method_id: str, config: dict) -> object:
        if method_id not in self._factories:
            raise KeyError("method %r not registered" % (method_id,))
        return self._factories[method_id](config)

    def available(self) -> List[str]:
        return sorted(self._factories.keys())


_registry = MethodRegistry()


def get_registry() -> MethodRegistry:
    """返回模块级单例注册表。"""
    return _registry
