# SDD: Transcript Confusion + Context Efficiency Analysis V3.5

> **Implementation Status: Planned** — 可独立于 v3.3/v3.4。

## TLDR

v3.5 新增 3 个组件：TranscriptPatternAnalyzer（6 种 confusion pattern）、ContextEfficiencyAnalyzer（5 种 inefficiency pattern）、分析 report 段。所有分析 deterministic。产出 RuleFinding。不修改已有对象。

---

## 1. TranscriptPatternAnalyzer

### 1.1 接口

```python
class TranscriptPatternAnalyzer:
    def analyze(self, trace: ExecutionTrace) -> list[RuleFinding]:
        """识别 6 种 confusion pattern，产生 RuleFinding。"""
```

### 1.2 6 种 pattern 的检测伪代码

```python
def _detect_repeated_retry(self, trace: ExecutionTrace) -> list[RuleFinding]:
    findings = []
    for i in range(len(trace.tool_calls) - 2):
        a, b, c = trace.tool_calls[i], trace.tool_calls[i+1], trace.tool_calls[i+2]
        if a.tool_name == b.tool_name == c.tool_name:
            if _args_equal(a.arguments, b.arguments) and _args_equal(b.arguments, c.arguments):
                findings.append(RuleFinding(
                    rule_type="transcript.repeated_tool_retry_loop",
                    category="transcript",
                    severity="high",
                    rule_passed=False,
                    message=f"'{a.tool_name}' called {3}+ times with same args (steps {i+1}-{i+3})",
                    evidence_ref=f"tool_calls[{i}:{i+3}]",
                ))
    return findings
```

---

## 2. ContextEfficiencyAnalyzer

### 2.1 接口

```python
class ContextEfficiencyAnalyzer:
    def analyze(self, trace: ExecutionTrace) -> list[RuleFinding]:
        """识别 5 种 context inefficiency pattern，产生 RuleFinding。"""
```

### 2.2 Median baseline 计算

```python
def _get_median_size(self, trace: ExecutionTrace, tool_name: str) -> float:
    sizes = []
    for r in trace.tool_results:
        if r.tool_name == tool_name:
            sizes.append(len(json.dumps(r.output)))
    if len(sizes) < 2:
        return -1.0  # insufficient data
    return sorted(sizes)[len(sizes) // 2]
```

---

## 3. 报告集成

### Markdown

```markdown
## Transcript Analysis

### Agent Confusion Patterns
| Severity | Pattern | Detail | Steps |
|----------|---------|--------|-------|
| high | repeated_tool_retry_loop | "search" called 5x with same args | 3-7 |
| medium | tool_switching_confusion | "search" ↔ "read" (3 cycles) | 2-7 |

### Context Efficiency
| Severity | Pattern | Detail | Tool |
|----------|---------|--------|------|
| high | response_bloat | 45KB output (median: 2KB) | "list_documents" |
| medium | missing_pagination | 200 items returned without pagination | "list_documents" |
```

---

## 4. 测试策略

| 测试文件 | 测试数 | 覆盖 |
|---------|--------|------|
| `tests/test_transcript_pattern_analyzer.py` | ~15 | 6 种 pattern × 各 2-3 scenario |
| `tests/test_context_efficiency_analyzer.py` | ~12 | 5 种 pattern × 各 2-3 scenario |
| `tests/test_transcript_context_report.py` | ~3 | Markdown/JSON |

**总计：≥ 30 个新增单测。**
