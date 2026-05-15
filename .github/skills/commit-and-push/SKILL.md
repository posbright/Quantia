---
description: 用于 Quantia 仓库每完成一项用户请求后，主动询问用户是否提交并推送变更，规范 commit message 与避免危险操作。AGENTS.md 已强制此流程，本 SKILL 提供询问模板、commit type 选择指南、安全检查清单与常见反模式。无变更 / 纯讨论 / 用户明确说"先不提交"时跳过。
---

# Commit & push workflow

> 自动触发条件：完成一项用户可见的代码改动（含构建产物、测试、文档），并通过自检（lint / test / build）。

## 步骤

### 1. 收集上下文

并行运行（可走 execution_subagent）：

```powershell
git status --short
git diff --stat HEAD
git log --oneline -3
git branch --show-current
```

把结果摘要展示给用户，让其确认范围。

### 2. 用 vscode_askQuestions 询问

至少两个问题，**不要自行决定**：

| header | question | options（参考） |
| --- | --- | --- |
| `commit_action` | 现在要提交哪些改动？ | 全部一起提交（推荐） / 只提交后端（不含 dist） / 拆成多个语义化 commit / 先不提交 |
| `push_action` | 提交完是否 push 到 origin/<分支>？ | 是，立即 push / 否，先在本地 commit |

如改动横跨多模块（比如后端 + 前端 + 文档），可加第三问"是否拆 commit"。

### 3. 生成 commit message

格式（中文）：

```
<type>: <一行概要 ≤ 50 字>

<空行>
<分组列出变更，每组 1-3 行>

前端:
- ...
后端:
- ...
测试:
- ...
文档:
- ...
构建:
- ...
```

**type 速查**：

| type | 适用 |
| --- | --- |
| `fix` | 修 bug、修 404、修崩溃 |
| `feat` | 新功能、新接口、新页面 |
| `refactor` | 不改行为的重构 |
| `chore` | 配置 / agent 自定义 / 依赖升级 |
| `docs` | 仅文档 |
| `test` | 仅测试 |
| `perf` | 性能优化 |
| `build` | 构建 / dist 产物（一般合进 fix/feat） |

PowerShell 多行 message 用多次 `-m`：

```powershell
git commit -m "fix: xxx" -m "" -m "前端:" -m "- ..." -m "后端:" -m "- ..."
```

### 4. push（如用户同意）

```powershell
git push origin <branch>
```

报告结果格式：`<old>..<new> <branch> -> <branch>`。

## 安全红线（绝不做）

- `git push --force` / `--force-with-lease`
- `git commit --no-verify`（绕过 hook）
- `git reset --hard <已 push 的 commit>`
- `git branch -D` 已 push 的分支
- `git rebase -i` 已 push 的提交
- `git filter-branch` / 重写历史
- 删除 `.env` / `cache/` / 数据库文件

任何上述操作必须先用 `vscode_askQuestions` 显式确认。

## 跳过条件

下列情况**不要追问提交**，直接结束：

- `git status --short` 无任何变化
- 用户的请求是纯查询 / 解释 / 调研（无代码改动）
- 改动只发生在 `cache/` / `quantia/log/` / `quantia/.venv*` / `__pycache__/`
- 用户在本对话里已经说过"先不要提交" / "我自己提交"
- 单文件笔误回滚等微小修正且用户立即指出要继续改

## dist 产物处理

Quantia 仓库**追踪** `quantia/fontWeb/dist/` 与 `quantia/web/static/`（构建产物随源码一起提交）。

- 改了前端源码 → 同步构建并把 dist 一起 commit，否则生产 :9988 看不到改动
- 只改后端 → dist 应保持不变，若 status 显示 dist 变化属于历史污染，单独询问是否清理
- 大量 dist 文件会让 commit 看着很吓人，但属于正常现象，无需拆分

## 反模式（请避免）

| 反模式 | 正确做法 |
| --- | --- |
| 改完直接 `git add . && git commit && git push`，不询问 | 先 askQuestions |
| commit message 写英文 / "update" / "fix bug" 这种空话 | 中文 + 具体修了什么 |
| 把 5 个不相干修复塞进 1 个 commit 还不分组列出 | 用分组段落或拆 commit |
| dist 与源码分两个 commit | 一起提交，避免线上构建版与源码不一致 |
| 用户说"先不提交"还反复追问 | 本对话剩余回合不再问 |
| 推送前没 pull / 远端有更新硬 push | 先 `git pull --rebase`，冲突让用户决定 |

## 模板：完整一次询问 → 提交 → 推送

```
1. [并行] git status --short / git log --oneline -3
2. 摘要展示给用户
3. vscode_askQuestions：commit_action + push_action
4. 根据答案：
   a. git add -A（或按用户选择 add 子集）
   b. git commit -m "..." -m "" -m "前端:" ...
   c. git log --oneline -1
   d. (可选) git push origin <branch>
5. 报告 commit 哈希 + push 结果
```
