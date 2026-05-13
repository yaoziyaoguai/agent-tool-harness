# CLIAgentAdapter Specification

> **定位**: Optional convenience runner——不是 Core 必需路径。
> **状态**: Implementation complete — Slice 1+2+3+4 done (2026-05-13).
> **父文档**: [REAL_AGENT_INTEGRATION_SDD.md](REAL_AGENT_INTEGRATION_SDD.md)
>
> **重要：** CLIAgentAdapter 是辅助接入方式。**主要接入路径是 TraceImportAdapter**——
> 用户用自己的脚本/CI/外部 runner 运行 Agent，产出 trace/log，通过
> TraceImportAdapter 导入。详见 [EXTERNAL_RUNNER_WORKFLOW.md](EXTERNAL_RUNNER_WORKFLOW.md)。

---

## 1. Purpose

`CLIAgentAdapter` 负责通过本地 CLI 命令运行用户 Agent，收集 trace 输出，并委托 `TraceImportAdapter` 将 trace 解析为 `ExecutionTrace`。

**这是 optional convenience**——适合用户没有外部 runner、想快速验证的场景。不要求所有用户使用。

**负责**:
- 从 `ScenarioSpec` 生成 input file
- 执行用户配置的 CLI 命令（subprocess）
- 收集 exit code / stdout / stderr / trace file
- 委托 `TraceImportAdapter` 解析 trace

**不负责**:
- 不自己解析复杂 trace
- 不读取用户私密项目数据（除非显式 allowlist）
- 不猜测命令行为
- 不用 `shell=True`（除非显式 opt-in）
- 不自动重试
- 不把 secrets 写入 report
- 不作为主要接入路径

### 1.1 When to use CLIAgentAdapter

- 用户没有现成的外部 runner/CI pipeline
- Agent 是简单 CLI 命令，可以 subprocess 调用
- 不需要复杂的环境配置（env、secrets、网络）
- 快速验证——想快速看到 CoreEvaluation → Report 闭环

### 1.2 When NOT to use CLIAgentAdapter

- Agent 需要复杂运行环境（GPU 集群、容器编排、分布式）
- Agent 的 provider/key/network 需要精细控制
- 已有 CI/CD pipeline 或外部调度系统
- trace 已经存在（直接文件），不需要重新运行
- Agent 运行时间长、资源消耗大
- 需要在受控生产环境中运行

**推荐替代方案：** 用自己的脚本/CI 运行 Agent，保存 trace/log，通过
TraceImportAdapter 导入。详见 [EXTERNAL_RUNNER_WORKFLOW.md](EXTERNAL_RUNNER_WORKFLOW.md)。

---

## 2. Contract

### 2.1 Input

```python
@dataclass
class CLIAgentConfig:
    """CLI Agent 运行配置。"""

    # 命令模板：{scenario_file} 和 {trace_file} 为占位符
    command: str
    # 如: "python run_agent.py --input {scenario_file} --trace-out {trace_file}"

    # 工作目录（用户 Agent 项目的根目录）
    working_dir: str | None = None

    # 执行超时（秒）
    timeout_seconds: float = 300.0

    # trace 输出格式
    trace_format: str = "native"  # "native" | "simple_mapping"

    # simple_mapping 时的字段映射配置（仅 trace_format="simple_mapping" 时使用）
    trace_mapping: dict | None = None

    # trace 文件路径模板
    trace_file_template: str = "{trace_file}"

    # 环境变量策略
    env_policy: str = "minimal"  # "minimal" | "allowlist" | "inherit"

    # 环境变量 allowlist（仅 env_policy="allowlist" 时使用）
    env_allowlist: list[str] | None = None

    # 是否允许 shell=True
    allow_shell: bool = False

    # stdout/stderr 截断长度（字符数），null 表示不截断
    max_stdout_chars: int | None = 10000
    max_stderr_chars: int | None = 10000
```

### 2.2 Output

```python
@dataclass
class CLIAgentResult:
    """CLI Agent 运行结果。"""

    # 进程信息
    exit_code: int
    command: str
    working_dir: str

    # 输出摘要
    stdout_summary: str
    stderr_summary: str

    # trace 解析结果
    execution_trace: ExecutionTrace | None  # None if trace import failed

    # 错误信息（如有）
    errors: list[str]

    # 耗时
    elapsed_seconds: float
```

---

## 3. Configuration Example

```yaml
# user project: my-agent/agent2harness.yaml
agent:
  type: cli
  command: "python run_agent.py --input {scenario_file} --trace-out {trace_file}"
  working_dir: "./my-agent"
  timeout_seconds: 120
  trace_format: native
  trace_file_template: "{trace_file}"
  env_policy: minimal
```

用户 `.env` 配置（可选，仅当 Agent 需要额外环境变量）：
```bash
# my-agent/.env（gitignored）
MY_AGENT_API_KEY=sk-...
MY_AGENT_ENDPOINT=https://...
```

---

## 4. Execution Flow

```
1. CLI 调用: harness run --agent-type cli --agent-config ./my-agent/agent2harness.yaml

2. Harness 加载 CLIAgentConfig
   - 读取 agent2harness.yaml
   - 验证 command template 含 {scenario_file}
   - 验证 working_dir 存在

3. Harness 生成 scenario input file
   - ScenarioSpec → JSON
   - 写入临时目录: /tmp/agent2harness-XXXXX/scenario_input.json

4. Harness 执行 CLI 命令
   - 替换 {scenario_file} → /tmp/.../scenario_input.json
   - 替换 {trace_file} → /tmp/.../trace_output.json
   - subprocess.run(command, cwd=working_dir, timeout=..., env=...)
   - 捕获 stdout/stderr → 截断 → stdout_summary / stderr_summary

5. Harness 检查结果
   - exit code != 0 → 记录 warning，不中断
   - trace file 不存在 → error
   - trace file 存在 → 交给 TraceImportAdapter

6. TraceImportAdapter.import_trace(trace_file)
   → ExecutionTrace

7. ExecutionTrace → Evidence → CoreEvaluation → EvaluationResult → Report
   (完全复用已有能力)
```

---

## 5. Security Boundary

### 5.1 Environment variables

| Policy | Behavior |
|--------|----------|
| `minimal` (default) | 只传递 `PATH` + `HOME` + `TMPDIR`。不传递任何项目 env。 |
| `allowlist` | 仅传递 `env_allowlist` 中列出的变量。 |
| `inherit` | 传递当前全部 `os.environ`。**需用户显式 opt-in**。 |

### 5.2 Shell

- 默认 `allow_shell=False` → 使用 `subprocess.run(command.split(), ...)`
- `allow_shell=True` 时使用 `subprocess.run(command, shell=True, ...)`
- 文档明确警告 `shell=True` 的风险（command injection）

### 5.3 Timeout

- `timeout_seconds` 必须设置且 > 0
- 超时后进程被 SIGTERM → SIGKILL
- 超时记录为 CLIAgentResult error

### 5.4 Output truncation

- stdout/stderr 按 `max_stdout_chars` / `max_stderr_chars` 截断
- 截断标记: `...(truncated, total N chars)`
- 防止超大输出撑爆 report

### 5.5 Secrets

- 不把 secrets 写入 report / artifact
- 不读取 `.env` 除非用户显式配置 `env_policy: allowlist`
- stdout/stderr 不自动扫描 secret（后续可加 auditor hook）

---

## 6. Relationship to TraceImportAdapter

```
CLIAgentAdapter
    │
    │  subprocess.run(command)
    │  产出 trace file
    │
    ▼
TraceImportAdapter.import_trace(trace_file)
    │
    ▼
ExecutionTrace
```

CLIAgentAdapter **不自己解析 trace**。原因：
- 单一职责：CLI 负责进程编排，TraceImport 负责 trace 解析
- 可组合：用户可以单独用 TraceImportAdapter 导入手动跑出的 trace
- 可测试：两个模块独立测试，集成测试验证组合

---

## 7. Test Plan

| # | Test | Category |
|---|------|----------|
| 1 | fake CLI 命令输出合法 native trace → ExecutionTrace | integration |
| 2 | fake CLI 命令输出 simple mapping trace → ExecutionTrace | integration |
| 3 | CLI 命令 return non-zero exit → 记录 warning，trace 仍解析 | error |
| 4 | CLI 命令超时 → CLIAgentResult error | error |
| 5 | trace 文件缺失 → CLIAgentResult error | error |
| 6 | stdout/stderr 截断 | output |
| 7 | env_policy=minimal 不传递额外 env var | security |
| 8 | env_policy=allowlist 仅传递 allowlisted env var | security |
| 9 | 默认 no shell=True — subprocess 使用 list 形式 | security |
| 10 | allow_shell=True 时使用 shell=True | config |
| 11 | TraceImportAdapter 集成：CLI 产出 → TraceImportAdapter 解析 | integration |
| 12 | 不读取 .env | security |
| 13 | 不调用外部 API | security |
| 14 | 不 import os.environ | forbidden dep |
| 15 | ScenarioSpec → input file roundtrip（从 input file 可重建 ScenarioSpec） | data |

所有测试零网络依赖。fake CLI 命令使用 `echo` / `cat` / 写文件的 Python 脚本。
