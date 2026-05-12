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
- Slice 1（本轮）：CLIAgentAdapterConfig / 命令校验 / input file 准备 / prepare_run
- Slice 2（后续）：subprocess 执行 / timeout / env 策略 / stdout stderr 截断
- Slice 3（后续）：TraceImportAdapter 集成 / trace 解析
- Slice 4（后续）：assembly 集成 / CLI flag
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_tool_harness.core_contract import ScenarioSpec

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


# ---------------------------------------------------------------------------
# CLIAgentAdapter（Slice 1: 仅 prepare，不 run）
# ---------------------------------------------------------------------------


class CLIAgentAdapter:
    """CLI Agent 适配器 — 通过 CLI 命令运行用户 Agent。

    架构边界:
    - **负责**: 命令编排、input file 写入、进程管理（Slice 2）。
    - **不负责**: trace 解析——必须委托 TraceImportAdapter（Slice 3）。
    - **为什么不能自己解析 trace**: 单一职责——CLI 负责进程编排，
      TraceImport 负责 trace 解析。两个模块独立测试，可组合使用。

    Slice 1 实现范围:
    - 命令校验（通过 CLIAgentAdapterConfig.__post_init__）
    - ScenarioSpec → input JSON 文件
    - 受控 trace output path（禁止路径穿越）
    - prepare_run() 生成 CLIAgentPreparedRun 执行计划
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
