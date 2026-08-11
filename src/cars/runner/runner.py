# -*- coding: utf-8 -*-
"""MethodRunner（子进程隔离 + 超时清理；统一 Evaluator 的唯一调用者）。

职责（R3 §3.1 / R5 §3.2-3.4）：
- Method 只生成 X/A/F 与方法诊断；Runner 是统一 Evaluator 的唯一调用者；
- 七种方法（cars + 六 Baseline）均通过同一 MethodRunner.run() 调用
  （R5：统一执行边界；无方法专属执行分支）；
- 公共决策前状态（R5 §3.1）：Runner 在每次调用前通过 build_predecision_state
  统一构造（Scenario + DerivedState，确定性，T0 决策前字段）；
- runtime 语义（R5 §3.4）：state_construction_runtime_ms / method_runtime_ms
  （= worker 内 Method.solve 时间）/ evaluation_runtime_ms / total_wall_time_ms /
  runtime_censored；TIMEOUT 时 method_runtime_ms 记录 timeout 预算；
- 统一决策归一化（R5 §3.3/adaptation）：六 Baseline 返回的 decision
  schema_version 归一化为当前正式 V2（仅元数据，不改数学）；
- timeout 使用独立子进程；子进程执行时通过 import cars.methods 发现六 Baseline
  注册；CARS 经统一方法解析的最小动态导入（R5 adaptation）；
- 单次失败不会使主进程挂起；timeout 后清理进程树。

失败计分（Contract Part 9.1/9.4）：
- method_status=TIMEOUT/METHOD_ERROR -> 不调用 Evaluator（无决策可评价），
  记录全部任务 z_i=0 的失败计分（task_failure_accounting）；
- SUCCESS/BUDGET_EXHAUSTED/NO_IMPROVEMENT -> 有决策，调用统一 Evaluator 正常评价。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from typing import Dict, Optional

from cars.results.canonical_result import build_canonical_result
from cars.runner.predecision_state import build_predecision_state

# 允许正常评价的方法状态（返回决策）
_NORMAL_STATUSES = ("SUCCESS", "BUDGET_EXHAUSTED", "NO_IMPROVEMENT")


def _config_hash(cfg: Dict) -> str:
    raw = json.dumps(cfg, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """终止进程树（Windows: taskkill /T /F；POSIX: killpg）。"""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
            )
        else:
            os.killpg(os.getpgid(proc.pid), 9)  # SIGKILL
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _soft_deadline_seconds(hard_timeout_seconds: float) -> float:
    """soft_deadline = hard_deadline - max(1s, 0.1*hard_timeout)（提示词 §五）。"""
    return float(hard_timeout_seconds) - max(1.0, 0.1 * float(hard_timeout_seconds))


class MethodRunner:
    """最小通用方法运行器（R3-NFA 冻结）。"""

    def __init__(self, python_executable: Optional[str] = None, project_root: Optional[str] = None):
        self.python = python_executable or sys.executable
        if project_root is None:
            project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
        self.project_root = project_root
        self.src_dir = os.path.join(project_root, "src")

    # ------------------------------------------------------------------
    # 子进程 worker
    # ------------------------------------------------------------------

    def _spawn_worker(
        self,
        *,
        method_id: str,
        scenario_cfg_path: str,
        method_config: Dict,
        method_seed: int,
        out_path: str,
    ) -> subprocess.Popen:
        """启动 worker 子进程（python -m cars.runner.worker）。"""
        env = dict(os.environ)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            self.src_dir + (os.pathsep + existing if existing else "")
        )
        cmd = [
            self.python,
            "-m",
            "cars.runner.worker",
            "--method",
            method_id,
            "--scenario-cfg",
            os.path.abspath(scenario_cfg_path),
            "--config-json",
            os.path.abspath(method_config["_runner_config_path"]),
            "--seed",
            str(method_seed),
            "--out",
            os.path.abspath(out_path),
        ]
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        proc = subprocess.Popen(
            cmd,
            cwd=self.project_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
            start_new_session=(os.name != "nt"),
        )
        return proc

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        method_id: str,
        scenario_cfg_path: str,
        method_config: Dict,
        method_seed: int,
        hard_timeout_seconds: float,
        work_dir: Optional[str] = None,
        python_version: Optional[str] = None,
    ) -> Dict:
        """运行方法并返回 RunRecord（含统一 Evaluator 输出 / 失败计分）。"""
        start = time.monotonic()
        if python_version is None:
            python_version = "%d.%d.%d" % sys.version_info[:3]
        config_hash = _config_hash(method_config)
        # R5：公共决策前状态统一构造（Scenario + DerivedState；确定性；计时）。
        # state_construction_runtime_ms 覆盖公共状态构造（R5 §3.4）。
        t_state = time.monotonic()
        state = build_predecision_state(scenario_cfg_path)
        scenario = state.scenario
        derived = state.derived
        state_construction_ms = (time.monotonic() - t_state) * 1000.0

        tmp = tempfile.mkdtemp(prefix="cars_r3_nfa_", dir=work_dir)
        config_path = os.path.join(tmp, "method_config.json")
        out_path = os.path.join(tmp, "worker_result.json")
        worker_cfg = dict(method_config)
        worker_cfg["_runner_config_path"] = config_path
        with open(config_path, "w", encoding="utf-8") as fh:
            json.dump(method_config, fh, ensure_ascii=False)

        proc = self._spawn_worker(
            method_id=method_id,
            scenario_cfg_path=scenario_cfg_path,
            method_config=worker_cfg,
            method_seed=method_seed,
            out_path=out_path,
        )

        proc_pid = proc.pid
        timed_out = False
        try:
            proc.communicate(timeout=float(hard_timeout_seconds))
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_tree(proc)
            try:
                proc.communicate(timeout=5)
            except Exception:
                pass

        # 读取 worker 结果
        proposal = None
        if proc.returncode is not None and proc.returncode == 0 and os.path.exists(out_path):
            try:
                with open(out_path, "r", encoding="utf-8") as fh:
                    proposal = json.load(fh)
            except Exception:
                proposal = None

        elapsed = time.monotonic() - start

        if proposal is not None and proposal.get("decision") is not None and proposal.get("method_status") in _NORMAL_STATUSES:
            return self._record_success(
                scenario=scenario,
                derived=derived,
                config_hash=config_hash,
                method_seed=method_seed,
                method_id=method_id,
                method_status=proposal["method_status"],
                timed_out=bool(proposal.get("timed_out", False)),
                decision=proposal["decision"],
                method_diagnostics=proposal.get("diagnostics", {}),
                runtime_seconds=float(proposal.get("runtime_seconds", 0.0)),
                total_elapsed=elapsed,
                python_version=python_version,
                spawn_pid=proc_pid,
                state_construction_ms=state_construction_ms,
            )

        # 失败路径：TIMEOUT / METHOD_ERROR / worker 未返回
        if timed_out or (proposal is not None and proposal.get("method_status") == "TIMEOUT"):
            method_status = "TIMEOUT"
            timed_out_flag = True
        else:
            method_status = "METHOD_ERROR"
            timed_out_flag = False
        return self._record_failure(
            scenario=scenario,
            config_hash=config_hash,
            method_seed=method_seed,
            method_id=method_id,
            method_status=method_status,
            timed_out=timed_out_flag,
            method_diagnostics=(proposal or {}).get("diagnostics", {}),
            runtime_seconds=float((proposal or {}).get("runtime_seconds", 0.0)),
            total_elapsed=elapsed,
            python_version=python_version,
            spawn_pid=proc_pid,
            state_construction_ms=state_construction_ms,
            timeout_budget_ms=float(hard_timeout_seconds) * 1000.0,
        )

    # ------------------------------------------------------------------
    # 成功记录（统一 Evaluator）
    # ------------------------------------------------------------------

    def _record_success(
        self,
        *,
        scenario,
        derived,
        config_hash,
        method_seed,
        method_id,
        method_status,
        timed_out,
        decision,
        method_diagnostics,
        runtime_seconds,
        total_elapsed,
        python_version,
        spawn_pid,
        state_construction_ms,
    ) -> Dict:
        # R5：统一决策归一化（六 Baseline V1 -> 当前正式 V2；仅元数据，不改数学）
        from cars.methods.adaptation import normalize_decision

        decision = normalize_decision(decision)
        # R5：External Evaluator 为正式指标唯一计算者；计时 evaluation_runtime_ms
        t_eval = time.monotonic()
        outcome = evaluator_call(scenario, decision, derived)
        evaluation_ms = (time.monotonic() - t_eval) * 1000.0
        record = build_canonical_result(
            scenario=scenario,
            config_hash=config_hash,
            seed=method_seed,
            method_id=method_id,
            method_status=method_status,
            timed_out=timed_out,
            decision=decision,
            evaluator_status=outcome["evaluator_status"].value,
            evaluator_output=outcome["evaluator_output"],
            diagnostics=outcome["diagnostics"],
            runtime_seconds=runtime_seconds,
            python_version=python_version,
        )
        record["method_diagnostics"] = method_diagnostics
        record["total_elapsed_seconds"] = total_elapsed
        record["spawn_pid"] = spawn_pid
        record["cleanup_completed"] = True
        # R5 统一运行时语义（R5 §3.4；diagnostics/记录字段，不进入 canonical hash）
        record["state_construction_runtime_ms"] = float(state_construction_ms)
        record["method_runtime_ms"] = float(runtime_seconds) * 1000.0
        record["evaluation_runtime_ms"] = float(evaluation_ms)
        record["total_wall_time_ms"] = float(total_elapsed) * 1000.0
        record["runtime_censored"] = bool(timed_out)
        return record

    # ------------------------------------------------------------------
    # 失败记录（Contract Part 9.1/9.4：全部任务 z_i=0，保留方法失败原因）
    # ------------------------------------------------------------------

    def _record_failure(
        self,
        *,
        scenario,
        config_hash,
        method_seed,
        method_id,
        method_status,
        timed_out,
        method_diagnostics,
        runtime_seconds,
        total_elapsed,
        python_version,
        spawn_pid,
        state_construction_ms,
        timeout_budget_ms,
    ) -> Dict:
        accounting = {
            "all_tasks_failed": True,
            "reason": "method_status=%s; 无合法决策，全部任务 z_i=0（Contract Part 9.1/9.4）" % method_status,
            "per_task": [
                {"task_id": t["task_id"], "success": 0} for t in scenario["tasks"]
            ],
        }
        record = build_canonical_result(
            scenario=scenario,
            config_hash=config_hash,
            seed=method_seed,
            method_id=method_id,
            method_status=method_status,
            timed_out=timed_out,
            decision=None,
            evaluator_status=None,
            evaluator_output=None,
            diagnostics={"method": method_diagnostics, "task_failure_accounting": accounting},
            runtime_seconds=runtime_seconds,
            python_version=python_version,
        )
        record["method_diagnostics"] = method_diagnostics
        record["total_elapsed_seconds"] = total_elapsed
        record["spawn_pid"] = spawn_pid
        record["cleanup_completed"] = True
        # R5 统一运行时语义（R5 §3.4）
        # - TIMEOUT：method_runtime_ms 记录 timeout 预算（不伪造精确完成时间）；
        # - METHOD_ERROR：记录方法实际报告时间（若为 0 则无精确时间）。
        record["state_construction_runtime_ms"] = float(state_construction_ms)
        if timed_out:
            record["method_runtime_ms"] = float(timeout_budget_ms)
        else:
            record["method_runtime_ms"] = float(runtime_seconds) * 1000.0
        record["evaluation_runtime_ms"] = 0.0  # 非 SUCCESS 不调用 External Evaluator
        record["total_wall_time_ms"] = float(total_elapsed) * 1000.0
        record["runtime_censored"] = bool(timed_out)
        return record


def evaluator_call(scenario, decision, derived):
    """统一 Evaluator 调用（Runner 是唯一调用者）。"""
    from cars.evaluator import evaluator as ev

    return ev.evaluate(scenario, decision, derived)
