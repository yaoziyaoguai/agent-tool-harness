"""CLIAgentAdapter — 通过本地 CLI 命令运行用户 Agent 并收集 trace。

架构边界
--------
- CLIAgentAdapter 是**运行层**，不是解析层。它负责 subprocess 编排和文件管理，
  trace 解析必须委托给 ``TraceImportAdapter``（Slice 3 集成）。
- **为什么不能自己解析 trace**：分离进程编排和 trace 解析后，两个模块可独立测试、
  可组合使用。TraceImportAdapter 已有完整的两模式实现（native + simple mapping），
  CLIAgentAdapter 不应重复实现解析逻辑。
- **为什么 command 必须是 list[str]**：默认 shell=False 的安全边界。list 形式
  杜绝 shell injection 和空格拆分歧义，程序名和参数明确分离。
- **为什么本切片只 prepare 不 subprocess.run**：按切片分离风险——先固化 command
  校验和 input file 准备的正确性，再在 Slice 2 叠加进程执行。
- **为什么 trace file 后续必须交给 TraceImportAdapter**：单一职责。
  CLIAgentAdapter 只保证"trace 文件能被生成到正确位置"，不保证"trace 内容正确"。
  解析和校验由 TraceImportAdapter 完成。
- **为什么不能读取完整宿主环境**：CLI Agent 是用户提供的任意程序，默认不能继承
  Agent2Harness 进程的完整环境（含 API key、数据库密码等）。env 策略在 Slice 2
  由 minimal/allowlist/inherit 三档控制。
- **为什么 ReviewDecision 不能由 adapter 生成**：ReviewDecision 必须由人工
  Reviewer 显式创建。CLIAgentAdapter 是运行层，不具备评测语义。

Slice 分层
----------
- Slice 1（done）：CLIAgentAdapterConfig / 命令校验 / input file 准备 / prepare_run
- Slice 2（done）：subprocess 执行 / timeout / env 策略 / stdout stderr 截断 / run()
- Slice 3（本轮）：TraceImportAdapter 集成 / trace 解析 / evidence 生成
- Slice 4（后续）：assembly 集成 / CLI flag
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_tool_harness.core_contract import Evidence, ExecutionTrace, ScenarioSpec

# TraceImportAdapter 在 Slice 3 中用于解析 trace 文件。
# 导入时机: 模块级导入，因为 Slice 3 的 _import_trace() 是 run() 的核心路径。
from agent_tool_harness.trace_import import SimpleMappingConfig, TraceImportAdapter

# ---------------------------------------------------------------------------
# 错误类型
# ---------------------------------------------------------------------------


class CLIAgentError(Exception):
    """CLIAgentAdapter 配置或准备阶段错误。

    架构边界:
    - **负责**: 携带明确错误信息，让用户能定位配置问题。
    - **不负责**: 不携带 secrets / API key / 用户私密数据。
    """

    ...


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class CLIAgentAdapterConfig:
    """CLI Agent 运行配置。

    架构边界:
    - **负责**: 声明 CLI 命令模板、运行环境、安全策略、输出约束。
    - **不负责**: 不执行命令、不读取 .env、不解析 trace。
    - command 必须是 list[str]，占位符 {input_path} / {trace_output_path}
      必须存在。
    - 字段如 timeout_seconds / env_policy / max_*_chars 已预留，本轮不消费（Slice 2）。

    与 CLI_AGENT_ADAPTER_SPEC.md §2.1 的对应:
    - spec 中 command 为 str 形式；本实现中强制 list[str] 以默认 shell=False。
    - spec 中占位符 {scenario_file}/{trace_file} → 此处 {input_path}/{trace_output_path}。
    """

    command: list[str]

    # 运行环境
    working_dir: str | None = None
    timeout_seconds: float = 300.0

    # trace 格式（Slice 3 使用，传给 TraceImportAdapter）
    trace_format: str = "native"  # "native" | "simple_mapping"
    trace_mapping: dict[str, Any] | None = None

    # 安全边界（Slice 2 使用）
    env_policy: str = "minimal"  # "minimal" | "allowlist" | "inherit"
    env_allowlist: list[str] | None = None
    allow_shell: bool = False

    # 输出截断（Slice 2 使用）
    max_stdout_chars: int | None = 10000
    max_stderr_chars: int | None = 10000

    REQUIRED_PLACEHOLDERS = ("{input_path}", "{trace_output_path}")

    def __post_init__(self) -> None:
        # 1. command 必须是 list[str]，不接受 shell string
        if not isinstance(self.command, list):
            raise CLIAgentError(
                f"command must be a list[str], got {type(self.command).__name__}. "
                f"Shell strings are not accepted — use list form for shell=False safety."
            )
        if len(self.command) == 0:
            raise CLIAgentError("command must not be empty")
        for i, arg in enumerate(self.command):
            if not isinstance(arg, str):
                raise CLIAgentError(
                    f"command[{i}] must be a string, got {type(arg).__name__}"
                )

        # 2. 必须占位符检查
        flat = " ".join(self.command)
        missing = [ph for ph in self.REQUIRED_PLACEHOLDERS if ph not in flat]
        if missing:
            raise CLIAgentError(
                f"command must contain placeholders: {', '.join(missing)}"
            )

        # 3. working_dir 校验（如果提供）
        if self.working_dir is not None:
            wd = Path(self.working_dir)
            if not wd.exists():
                raise CLIAgentError(
                    f"working_dir does not exist: {self.working_dir}"
                )
            if not wd.is_dir():
                raise CLIAgentError(
                    f"working_dir is not a directory: {self.working_dir}"
                )

        # 4. timeout_seconds 必须是正数（安全边界：在配置阶段提前拒绝 <=0，
        #    避免等到 subprocess.run 才暴露——后者行为不可审计）。
        #    timeout 是运行真实本地 CLI agent 的硬安全边界：防止失控进程无限挂起。
        #    这不改变正常成功路径——timeout >=1 的合法配置不受影响。
        if self.timeout_seconds <= 0:
            raise CLIAgentError(
                f"timeout_seconds must be > 0, got {self.timeout_seconds}. "
                f"timeout is a hard safety boundary for CLI agent subprocess execution."
            )


# ---------------------------------------------------------------------------
# Prepared run（只 plan，不 execute）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CLIAgentPreparedRun:
    """准备完成的运行计划。

    这是 dry/prepared plan，不是真实运行结果。Slice 2 会用这些信息调 subprocess.run。

    - argv: 占位符已替换的最终命令参数（list[str]，可直接传 subprocess.run）
    - working_dir: 执行目录
    - input_path: scenario input JSON 文件的绝对路径
    - trace_output_path: Agent 应写入的 trace 文件绝对路径
    """

    argv: list[str]
    working_dir: str
    input_path: str
    trace_output_path: str


@dataclass
class CLIAgentResult:
    """CLI Agent 运行结果。

    架构边界:
    - **负责**: 携带一次 CLI Agent 执行的完整信息，供上游 (assembly/report) 消费。
    - **不负责**: 不自己解析 trace——execution_trace 和 evidence 由
      TraceImportAdapter 填入（Slice 3）。
    - elapsed_seconds 记录端到端墙上时间，仅供 advisory，不参与 pass/fail 裁决。
    - execution_trace / evidence 为 None 表示 trace import 未发生或失败。
    """

    exit_code: int
    command: str
    working_dir: str
    stdout_summary: str
    stderr_summary: str
    execution_trace: ExecutionTrace | None
    evidence: Evidence | None
    errors: list[str]
    elapsed_seconds: float


# ---------------------------------------------------------------------------
# CLIAgentAdapter（Slice 1+2: prepare + run）
# ---------------------------------------------------------------------------


class CLIAgentAdapter:
    """CLI Agent 适配器 — 通过 CLI 命令运行用户 Agent。

    架构边界:
    - **负责**: 命令编排、input file 写入、进程管理（Slice 2）。
    - **不负责**: trace 解析——必须委托 TraceImportAdapter（Slice 3）。
    - **为什么不能自己解析 trace**: 单一职责——CLI 负责进程编排，
      TraceImport 负责 trace 解析。两个模块独立测试，可组合使用。

    Slice 1+2+3 实现范围:
    - 命令校验（通过 CLIAgentAdapterConfig.__post_init__）
    - ScenarioSpec → input JSON 文件
    - 受控 trace output path（禁止路径穿越）
    - prepare_run() 生成 CLIAgentPreparedRun 执行计划
    - run() 执行 CLI Agent 命令（subprocess + timeout + env policy + 截断）
    - _import_trace() 委托 TraceImportAdapter 解析 trace（native + simple_mapping）
    """

    def __init__(self, config: CLIAgentAdapterConfig) -> None:
        self._config = config

    @property
    def config(self) -> CLIAgentAdapterConfig:
        return self._config

    # ------------------------------------------------------------------
    # input file
    # ------------------------------------------------------------------

    def write_input_file(
        self, scenario: ScenarioSpec, output_path: Path | str
    ) -> Path:
        """把 ScenarioSpec 写入 input JSON 文件，供用户 Agent 读取。

        输出结构是 ScenarioSpec 的 JSON 序列化——scenario_id / goal /
        available_tools / success_criteria / constraints。
        不包含 EvalSpec 中的 YAML 加载元数据（如 source / complexity）。
        """
        output_path = Path(output_path)
        data: dict[str, Any] = {
            "scenario_id": scenario.scenario_id,
            "goal": scenario.goal,
            "available_tools": list(scenario.available_tools),
            "success_criteria": list(scenario.success_criteria),
            "constraints": dict(scenario.constraints),
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return output_path

    # ------------------------------------------------------------------
    # prepare
    # ------------------------------------------------------------------

    def prepare_run(
        self,
        scenario: ScenarioSpec,
        *,
        output_dir: Path | str,
    ) -> CLIAgentPreparedRun:
        """准备一次 CLI Agent 执行计划。

        不执行 subprocess——只做:
        1. 创建 output_dir
        2. 写 ScenarioSpec → input JSON
        3. 确定受控 trace output path
        4. 替换 command 模板中的占位符 → argv

        Raises:
            CLIAgentError: output_dir 不可写或 trace output path 穿越边界。
        """
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        # input file
        input_path = output_dir / "scenario_input.json"
        self.write_input_file(scenario, input_path)

        # trace output path — 严格在 output_dir 下，不允许 ../ 穿越
        trace_output_path = output_dir / "trace_output.json"
        resolved_trace = trace_output_path.resolve()
        if not str(resolved_trace).startswith(str(output_dir)):
            raise CLIAgentError(
                f"trace_output_path must be under output_dir: "
                f"{trace_output_path} → {resolved_trace}"
            )

        # working_dir — 未配置时默认当前目录
        working_dir = self._config.working_dir or str(Path.cwd())

        # 替换占位符
        argv = [
            arg.replace("{input_path}", str(input_path)).replace(
                "{trace_output_path}", str(trace_output_path)
            )
            for arg in self._config.command
        ]

        return CLIAgentPreparedRun(
            argv=argv,
            working_dir=working_dir,
            input_path=str(input_path),
            trace_output_path=str(trace_output_path),
        )

    # ------------------------------------------------------------------
    # env
    # ------------------------------------------------------------------

    def _build_env(self) -> dict[str, str]:
        """根据 env_policy 构建子进程环境变量。

        - minimal: 仅 PATH / HOME / TMPDIR / TEMP / TMP
        - allowlist: 仅传递 env_allowlist 中列出的变量
        - inherit: 传递全部 os.environ（需显式 opt-in）
        """
        policy = self._config.env_policy

        if policy == "inherit":
            return dict(os.environ)

        if policy == "allowlist":
            allowed = set(self._config.env_allowlist or [])
            return {k: v for k, v in os.environ.items() if k in allowed}

        # minimal
        minimal: dict[str, str] = {}
        for key in ("PATH", "HOME", "TMPDIR", "TEMP", "TMP"):
            if key in os.environ:
                minimal[key] = os.environ[key]
        return minimal

    # ------------------------------------------------------------------
    # output helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _truncate(text: str, max_chars: int | None, label: str) -> str:
        """按 max_chars 截断文本，超出时附加截断标记。max_chars=None 不截断。"""
        if max_chars is None or len(text) <= max_chars:
            return text
        truncated = text[:max_chars]
        return f"{truncated}...(truncated, total {len(text)} chars)"

    @staticmethod
    def _decode_output(raw: str | bytes | None) -> str:
        """将 subprocess 输出统一转为 str。"""
        if raw is None:
            return ""
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return raw

    # ------------------------------------------------------------------
    # trace import（Slice 3: TraceImportAdapter 集成）
    # ------------------------------------------------------------------

    def _import_trace(
        self, trace_path: Path
    ) -> tuple[ExecutionTrace | None, Evidence | None, list[str]]:
        """委托 TraceImportAdapter 解析 trace 文件。

        这是 CLIAgentAdapter 与 TraceImportAdapter 的唯一集成点。
        CLIAgentAdapter **不自己解析 trace**——只根据 ``config.trace_format``
        构造对应的 TraceImportAdapter 并委托解析。TraceImportAdapter 已有
        完整的 native + simple_mapping 两模式实现和校验逻辑，CLIAgentAdapter
        不应重复实现。

        为什么 trace import 失败只产出 errors 而不抛异常:
        - trace import 失败是 advisory 信息，不改变进程执行事实。
        - 调用方通过 ``execution_trace is None`` 判断是否成功。

        Returns:
            (execution_trace, evidence, import_errors)
            import_errors 为空表示导入成功。
        """
        import_errors: list[str] = []

        # 根据 trace_format 构造 TraceImportAdapter
        mode = self._config.trace_format
        mapping: SimpleMappingConfig | None = None
        if mode == "simple_mapping" and self._config.trace_mapping:
            try:
                mapping = SimpleMappingConfig(**self._config.trace_mapping)
            except Exception as e:
                import_errors.append(
                    f"trace import: invalid simple_mapping config: {e}"
                )
                return None, None, import_errors

        try:
            adapter = TraceImportAdapter(mode=mode, mapping=mapping)
            execution_trace = adapter.import_file(trace_path)
            evidence = adapter.to_evidence(execution_trace)
        except Exception as e:
            import_errors.append(f"trace import failed: {e}")
            return None, None, import_errors

        return execution_trace, evidence, import_errors

    # ------------------------------------------------------------------
    # run（Slice 2+3: subprocess 执行 + trace import）
    # ------------------------------------------------------------------

    def run(
        self,
        scenario: ScenarioSpec,
        *,
        output_dir: Path | str,
    ) -> CLIAgentResult:
        """执行 CLI Agent 命令并收集结果。

        完整流程:
        1. prepare_run() → CLIAgentPreparedRun（input file + argv + 路径）
        2. _build_env() → 子进程环境变量
        3. subprocess.run() → exit_code / stdout / stderr
        4. 截断 stdout/stderr → stdout_summary / stderr_summary
        5. 检查 trace 文件是否存在 → errors

        不解析 trace——execution_trace 始终为 None（Slice 3 接入）。
        """
        prepared = self.prepare_run(scenario, output_dir=output_dir)
        errors: list[str] = []

        # 构建环境变量
        env = self._build_env()

        # 确定 shell 参数——allow_shell 时传拼接字符串
        if self._config.allow_shell:
            popen_args: list[str] | str = " ".join(prepared.argv)
        else:
            popen_args = prepared.argv

        # 执行
        t0 = time.monotonic()
        try:
            result = subprocess.run(
                popen_args,
                cwd=prepared.working_dir,
                env=env,
                capture_output=True,
                timeout=self._config.timeout_seconds,
                shell=self._config.allow_shell,
                text=True,
            )
            exit_code = result.returncode
            stdout_raw: str | bytes | None = result.stdout
            stderr_raw: str | bytes | None = result.stderr
        except subprocess.TimeoutExpired as e:
            exit_code = -1
            stdout_raw = e.stdout
            stderr_raw = e.stderr
            errors.append(
                f"command timed out after {self._config.timeout_seconds}s"
            )
        except OSError as e:
            exit_code = -1
            stdout_raw = ""
            stderr_raw = str(e)
            errors.append(f"command execution failed: {e}")

        elapsed = time.monotonic() - t0

        # 解码并截断
        stdout_summary = self._truncate(
            self._decode_output(stdout_raw),
            self._config.max_stdout_chars,
            "stdout",
        )
        stderr_summary = self._truncate(
            self._decode_output(stderr_raw),
            self._config.max_stderr_chars,
            "stderr",
        )

        # 非零 exit code → warning（不阻断 trace 解析）
        is_timeout = any("timed out" in e for e in errors)
        if exit_code != 0 and not is_timeout:
            errors.append(f"command exited with non-zero code: {exit_code}")

        # trace 文件缺失或超时 → 不导入 trace
        # 超时时 trace 文件即使存在也可能不完整，不尝试导入。
        trace_path = Path(prepared.trace_output_path)
        if not trace_path.exists():
            errors.append(
                f"trace output file not found: {prepared.trace_output_path}"
            )

        # Slice 3: trace 存在且非超时 → 委托 TraceImportAdapter 解析
        execution_trace: ExecutionTrace | None = None
        evidence: Evidence | None = None
        if trace_path.exists() and not is_timeout:
            execution_trace, evidence, import_errors = self._import_trace(trace_path)
            errors.extend(import_errors)

        return CLIAgentResult(
            exit_code=exit_code,
            command=" ".join(prepared.argv),
            working_dir=prepared.working_dir,
            stdout_summary=stdout_summary,
            stderr_summary=stderr_summary,
            execution_trace=execution_trace,
            evidence=evidence,
            errors=errors,
            elapsed_seconds=elapsed,
        )
