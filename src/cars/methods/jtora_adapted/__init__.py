# -*- coding: utf-8 -*-
"""jtora_adapted 方法包（注册入口）。

注册：method_id "jtora_adapted" -> factory(config) -> JtoraAdaptedMethod（生产版）。
"""

from __future__ import annotations

from cars.methods.jtora_adapted.method import JtoraAdaptedMethod
from cars.methods.registry import get_registry


def _factory(config: dict) -> JtoraAdaptedMethod:
    return JtoraAdaptedMethod(config)


get_registry().register("jtora_adapted", _factory)

__all__ = ["JtoraAdaptedMethod", "ReferenceJtoraAdapted", "METHOD_ID"]

from cars.methods.jtora_adapted.reference import ReferenceJtoraAdapted  # noqa: E402
from cars.methods.jtora_adapted.method import METHOD_ID  # noqa: E402
