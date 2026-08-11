# -*- coding: utf-8 -*-
"""bpso_rata_la 方法包（注册入口）。

注册：method_id "bpso_rata_la" -> factory(config) -> BpsoRataLaMethod（生产版）。
"""

from __future__ import annotations

from cars.methods.bpso_rata_la.method import BpsoRataLaMethod
from cars.methods.registry import get_registry


def _factory(config: dict) -> BpsoRataLaMethod:
    return BpsoRataLaMethod(config)


get_registry().register("bpso_rata_la", _factory)

__all__ = ["BpsoRataLaMethod", "ReferenceBpsoRataLa", "METHOD_ID"]

from cars.methods.bpso_rata_la.reference import ReferenceBpsoRataLa  # noqa: E402
from cars.methods.bpso_rata_la.method import METHOD_ID  # noqa: E402
