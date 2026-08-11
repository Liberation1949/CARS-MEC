# -*- coding: utf-8 -*-
"""Runner worker 子进程入口（python -m cars.runner.worker）。

流程：加载场景配置 -> 公共决策前状态（R5：Scenario + DerivedState 统一构造）
-> 统一方法解析（R5 adaptation 白名单 + Registry + 最小动态导入）
-> MethodContext（含软截止期）-> 方法运行 -> 写 MethodProposal JSON。

子进程通过 import cars.methods 触发六 Baseline 注册（注册发现）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time


def _ensure_paths() -> None:
    """确保 src 在 sys.path（PYTHONPATH 已由 Runner 注入，此处双保险）。"""
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src = os.path.join(os.path.dirname(here), "src")
    for p in (src,):
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)


def _soft_deadline_seconds(hard_timeout_seconds: float) -> float:
    return float(hard_timeout_seconds) - max(1.0, 0.1 * float(hard_timeout_seconds))


def main(argv=None) -> int:
    _ensure_paths()
    parser = argparse.ArgumentParser(description="CARS method runner worker")
    parser.add_argument("--method", required=True)
    parser.add_argument("--scenario-cfg", required=True)
    parser.add_argument("--config-json", required=True)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    result = None
    try:
        from cars.methods import registry  # noqa: F401  触发注册
        from cars.methods.adaptation import resolve_method
        from cars.methods.protocol import MethodContext
        from cars.runner.predecision_state import build_predecision_state

        with open(args.config_json, "r", encoding="utf-8") as fh:
            method_config = json.load(fh)

        # R5：统一公共决策前状态（Scenario + DerivedState，确定性构造）
        state = build_predecision_state(args.scenario_cfg)
        scenario = state.scenario
        derived = state.derived
        registry_obj = registry.get_registry()
        method = resolve_method(registry_obj, args.method, method_config)

        hard_timeout = float(method_config.get("hard_timeout_seconds", 10.0))
        ctx = MethodContext(
            scenario=scenario,
            derived=derived,
            config=method_config,
            method_seed=args.seed,
            soft_deadline_seconds=_soft_deadline_seconds(hard_timeout),
            hard_timeout_seconds=hard_timeout,
        )
        proposal = method.run(ctx)
        result = proposal.to_dict()
    except Exception as exc:  # noqa: BLE001 - worker 必须捕获并向主进程报告
        result = {
            "decision": None,
            "method_status": "METHOD_ERROR",
            "timed_out": False,
            "runtime_seconds": 0.0,
            "diagnostics": {"worker_error": "%s: %s" % (type(exc).__name__, str(exc))},
        }

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
