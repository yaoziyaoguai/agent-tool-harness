# Engineering Review Checklist（工程审查清单）

> 本文档是 agent-tool-harness 的 Code Review / PR Review 通用检查清单。
> 面向 reviewer（含人类和 Coding Agent），覆盖代码变更、测试、文档、安全、架构 5 个维度。
>
> 每个模块有独立的 Review Checklist（见 `docs/modules/` 下各 `*_DESIGN.md` 第 §Review Checklist 段），本文档是跨模块的通用项。

---

## 一、Code Review 通用项

### 1.1 正确性

- [ ] 变更是否解决了声明的 root cause（不是 symptom patch）
- [ ] 新增代码的 error path 是否得到处理（不 silent-swallow）
- [ ] 是否存在 `except Exception: pass` 或等效的吞异常模式
- [ ] 字符串比较 / 集合运算 / 字典查找是否考虑了 None / 空串 / 边界值

### 1.2 可读性

- [ ] 函数名、变量名是否揭示意图（不出现 `data` / `info` / `handler` / `process` / `temp` 等泛化名）
- [ ] 函数是否单职责（不超过 50 行）
- [ ] 文件是否聚焦（不超过 800 行）
- [ ] 是否有超过 4 层的缩进嵌套
- [ ] 新增注释是否解释了 WHY 而非 WHAT

### 1.3 简洁性

- [ ] 是否存在可以删除的死代码 / 注释掉的代码
- [ ] 是否存在仅被一个调用方使用的 premature abstraction（3 个相似行 > 1 个过度抽象的 helper）
- [ ] 是否引入了不必要的配置选项（"以后可能会用到"不是理由）
- [ ] 是否引入了不必要的依赖

---

## 二、测试审查

### 2.1 测试纪律

- [ ] 新增非平凡行为是否有对应测试
- [ ] 测试是否覆盖了 good path 和 bad path
- [ ] 测试断言是否足够严格（不是 `assert True` / `assert result is not None` 这种放水断言）
- [ ] 是否存在 `xfail` 但没有写 `strict=True` 和转正条件
- [ ] run good/bad 双路径是否都跑过，且 good 全 PASS、bad 全 FAIL
- [ ] 是否修改了已有测试来"适应"实现变更（而不是反过来）

### 2.2 safe-by-default 测试

- [ ] 新增模块/CLI 是否默认不联网（可通过 socket 禁用的 contract test 证明）
- [ ] 新增模块/CLI 是否默认不读取真实 API key
- [ ] 任何涉及 `api_key` / `Authorization` / `Bearer` 的代码路径是否有 secret 泄漏测试

---

## 三、文档审查

### 3.1 文档一致性

- [ ] `README.md` 中的 CLI 命令片段是否能实际执行
- [ ] `docs/` 中的文件路径引用是否仍然有效
- [ ] `docs/ARTIFACTS.md` artifact schema 是否与源码一致
- [ ] `docs/INDEX.md` 角色路由是否仍覆盖所有 canonical 文档
- [ ] 新增接口/模块是否在对应设计文档中记录

### 3.2 文档措辞

- [ ] 是否使用了"advisory-only"措辞（涉及 LLM judge / cost 估算时）
- [ ] 是否声明了 deterministic heuristic 的边界（当变更涉及非 LLM 判断时）
- [ ] `signal_quality` 披露是否与变更影响的范围一致

---

## 四、安全审查

### 4.1 密钥与凭证

- [ ] 是否有硬编码的 `sk-` / `api_key` / `Bearer` / Authorization header 字面值
- [ ] 新增 env var 是否加到 `.env.example`（仅占位符）
- [ ] `.env` 是否在 `.gitignore` 中
- [ ] 异常 message / traceback / log 是否可能包含 raw key、token 或 base_url

### 4.2 输入校验

- [ ] CLI 参数是否做了合法性校验（非空、类型、范围）
- [ ] YAML 加载是否使用了 `yaml.safe_load`（而非 `yaml.load`）
- [ ] 用户提供的路径是否做了目录穿越检查
- [ ] 工具函数参数是否在 executor 边界做了 schema 校验

### 4.3 artifact 安全

- [ ] 任何 artifact（JSON/JSONL/Markdown）是否不会包含真实 key / token / Authorization header
- [ ] `judge_results.json` 是否不会包含 raw API response body
- [ ] `report.md` 是否不会包含 raw SDK traceback

---

## 五、架构审查

### 5.1 模块边界

- [ ] 变更是否跨越了已声明的模块边界（见 `docs/architecture/MODULE_BOUNDARIES.md`）
- [ ] 新增依赖方向是否符合依赖规则（不允许循环依赖、不允许反向依赖）
- [ ] 是否存在"绕过 audit 直接 run"的路径
- [ ] 是否存在"绕过 recorder 直接写 artifact"的路径

### 5.2 接口稳定性

- [ ] 是否修改了稳定接口（见 `docs/architecture/TECHNICAL_ARCHITECTURE.md` § 接口稳定性分级）
- [ ] 如果修改了稳定接口，是否 bump 了对应的 schema_version
- [ ] 新增接口是否标记了稳定性级别

### 5.3 backward-compat

- [ ] artifact 变更是否遵循"只增不删"承诺
- [ ] 新增 artifact 字段是否有默认值 / None 安全检查
- [ ] CLI 子命令的 flag 变更是否向后兼容

---

## 六、特定变更类型检查

### 6.1 新增 eval

- [ ] `user_prompt` 是否来自真实用户问题（不含工具名）
- [ ] `expected_tool_behavior.required_tools` 是否引用了 `tools.yaml` 中存在的工具
- [ ] `judge.rules` 是否足够区分 good/bad path（不只靠 `must_call_tool`）
- [ ] `runnable` 是否与 `initial_context` / `expected_root_cause` 的完整性一致
- [ ] 是否有对应的 bad fixture

### 6.2 新增 judge 规则

- [ ] 规则是否 deterministic（不依赖 LLM 语义判断）
- [ ] 规则失败 message 是否可行动
- [ ] 是否有对应的 bad path 测试
- [ ] `RuleJudge._check` 中新增的 if/elif 分支是否放在 `_check` 方法中

### 6.3 新增 provider

- [ ] provider 是否 deterministic + offline（CI 可跑）
- [ ] provider 在缺配置时是否给可行动错误而非静默 PASS
- [ ] 异常路径是否走脱敏模板
- [ ] 新增 error_code 是否加入 `_safe_message()` 映射

### 6.4 新增 CLI 子命令

- [ ] 是否有 `tests/test_docs_cli_snippets.py` 中对应的 snippet 测试
- [ ] 是否有 `tests/test_docs_index.py` 中对应的文档入口检查
- [ ] stdout 是否打印了实际产物路径（`wrote <path>`）
- [ ] 是否在 `README.md` CLI 用法段有文档说明

### 6.5 新增依赖

- [ ] 是否可以通过标准库实现（优先标准库）
- [ ] 依赖是否已经在 `pyproject.toml` 中声明
- [ ] 依赖的 license 是否与项目兼容
- [ ] 依赖是否引入新的安全攻击面

---

## 七、Review 流程

1. **自检**：变更者先跑完本 checklist 的所有适用项
2. **自动化检查**：`pytest -q` 全绿 + `ruff check` 零新增 warning
3. **独立 Review**：至少一个非变更者的 reviewer（含 Coding Agent）过一遍代码
4. **文档 Review**：如果变更涉及架构/接口/新增模块，对应设计文档必须同步更新
5. **good/bad 双路径**：必须两条都跑过且结果正确（good 全 PASS、bad 全 FAIL）

---

## 八、常见反模式（禁止项）

| 反模式 | 为什么禁止 |
|--------|-----------|
| `except Exception: pass` | 吞异常，bug 永远发现不了 |
| 只跑 `--mock-path good` 不跑 bad | judge 可能退化为同义复读 |
| 把 `review_status` 从 `candidate` 批量改成 `accepted` 跳过人工 review | 候选都不是正式 eval |
| 让 dry_run provider 的 PASS/FAIL 覆盖 deterministic baseline | deterministic 才是 ground truth |
| recording 缺失就静默返回 PASS | 吞异常假成功，RecordingJudgeProvider 会抛 MissingRecordingError |
| 在 report 中写死判定而不引用 raw artifact 路径 | report 是派生视图，复盘必须回 raw artifacts |
| 把 `llm_cost.json` 的 `estimated_cost_usd` 当真实账单 | advisory-only |
| 在异常 message 中 echo raw API key / base_url / response body | 安全泄漏 |
| `assert result is not None` | 太弱，几乎等同于没断言 |
| 修改测试来"适应"实现变更 | 测试的保护价值被清零 |

---

> 各模块的专项 Review Checklist 见 `docs/modules/` 下对应 `*_DESIGN.md` 第 §Review Checklist 段。
> 本文档与 `docs/review/STALE_DOCS_AUDIT.md` 同为 review 目录下的核心文档。
