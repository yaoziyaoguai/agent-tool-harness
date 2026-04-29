# Maintainer Rehearsal Log — realistic_offline_tool_trial

> **本文件只记录 maintainer 自己的 rehearsal**。
>
> - **maintainer rehearsal only**
> - **not real internal team feedback**
> - **does NOT count toward the 3-feedback v3.0 gate**
>
> 真实内部同事反馈仍然只能写到
> `docs/INTERNAL_TRIAL_FEEDBACK_SUMMARY.md`。

## 第 1 次 rehearsal

- **试用者**：maintainer (claude-opus-4.7 cli session)
- **工具类型**：3 个 deterministic offline 函数（KB search / failure
  classifier / config snippet validator）
- **是否单工具**：否（3 个工具 + 2 条 multi-step eval；故意覆盖 multi-step
  以验证 chain，不是给真实第一次内部试用的人推荐难度）
- **是否依赖 secret/network/database**：否（全部 fake / 硬编码）
- **bootstrap 是否成功**：✅ `bootstrap --source examples/realistic_offline_tool_trial --out /tmp/ath-realistic --force` 一次过，生成
  `tools.generated.yaml` / `evals.generated.yaml` / `fixtures/` /
  `REVIEW_CHECKLIST.md` / `validation_summary.json` 5 件套
- **review TODO 花了多久**：N/A（reviewed 配置作为 fixture 一次写好；
  真实第一次内部同事预计 30–60 分钟填完一个工具的 TODO）
- **strict-reviewed 是否通过**：✅ `validate-generated --strict-reviewed`
  对 `tools.reviewed.yaml` + `evals.reviewed.yaml` 直接 pass
- **deterministic run 是否产出 report/artifacts**：✅ `run --mock-path good`
  产出 10 件套 artifact + report.md，2 条 eval 全 pass
- **哪个 artifact 最有用**：`report.md`（一目了然 signal_quality 警示 +
  pass/fail 数）；其次是 `tool_calls.jsonl`（验证 mock 真的按 required_tools
  顺序调了 3 个工具）
- **哪个字段最难懂**：reviewer 第一次接触会被 `expected_tool_behavior`
  vs `judge.rules` 的关系绕一下：前者控制 mock replay 调什么、后者控制
  judge 怎么判；`README.md` §7 步路径里**没**直接讲这层关系，留给后续
  patch
- **是否真的需要 v3.0 能力**：❌ 完全不需要；本 rehearsal 没有任何一步
  暴露"deterministic offline 不够用"的瓶颈
- **deterministic/offline 为什么够用**：因为本 sample 的 3 个工具本身就
  是可 deterministic 的；如果换成"真的查内部 KB"，那不是 v2.x 设计目标，
  是 v3.0

## maintainer 自我提醒

- ❌ 不要把 maintainer rehearsal 写进 `INTERNAL_TRIAL_FEEDBACK_SUMMARY.md`；
- ❌ 不要拿 maintainer rehearsal 凑 3 份反馈来论证 v3.0 该启动；
- ✅ 真实内部同事反馈出现后，本文件仅作为 baseline 对照。
