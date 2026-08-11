# -*- coding: utf-8 -*-
"""nfa_adapted 方法包（注册入口）。

注册：method_id "nfa_adapted" -> factory(config) -> NfaAdaptedMethod（生产版）。
仅注册 nfa_adapted（AGENTS.md §10 白名单；其他方法留后续子阶段）。
"""

from __future__ import annotations

from cars.methods.nfa_adapted.optimized import NfaAdaptedMethod
from cars.methods.registry import get_registry


def _factory(config: dict) -> NfaAdaptedMethod:
    return NfaAdaptedMethod(config)


get_registry().register("nfa_adapted", _factory)

__all__ = ["NfaAdaptedMethod", "ReferenceNfaAdapted", "METHOD_ID"]

from cars.methods.nfa_adapted.reference import ReferenceNfaAdapted  # noqa: E402
from cars.methods.nfa_adapted.optimized import METHOD_ID  # noqa: E402
