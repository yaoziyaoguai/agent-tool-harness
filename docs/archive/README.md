# archive/

此目录为空。

已删除的文档（历史层、内部试用、push preflight 等）可通过 git history 找回：

```bash
git log --diff-filter=D --summary -- 'docs/*.md' | head -50
git show <commit>^:docs/<path>
```

删除原因：项目定位从"多文档体系"精简为"Headless CLI Agent Tool Harness Prototype"，
删除了 46+ 份与当前实现状态不匹配的历史文档。详见 ROADMAP.md 的"文档瘦身"阶段。
