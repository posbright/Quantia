---
name: restart-and-deploy
description: "Use after editing Quantia backend Python (quantia/web/**, quantia/core/**, quantia/job/**) or frontend (quantia/fontWeb/src/**) to restart the long-running Tornado web service, sync template changes, and copy the Vite dist into quantia/web/static for production. Use when changes appear to take no effect in the browser or when frontend strategy templates show stale code."
---

# Quantia 重启与部署流程

## 何时使用
- 修改了任何后端 Python 模块（`quantia/web/`、`quantia/core/`、`quantia/job/`、`quantia/lib/`）。
- 修改了内置策略模板源码（`quantia/core/strategy/*.py` 或与 `sync_strategy_templates_to_db` 关联的文件）。
- 修改了前端 Vue 代码（`quantia/fontWeb/src/**`）并要部署到 Tornado 静态目录。
- 浏览器看到的策略代码 / 接口行为没有反映本次改动。

## 背景（为什么必须做）
- `web_service.py` 是常驻 Tornado 进程，Python 模块导入后会被缓存——不重启永远跑旧代码。
- 内置策略源码到 DB 的同步发生在 Web 启动时与 `POST /quantia/api/strategy/sync_templates`；不重启或不调用该接口，前端编辑/回测页继续显示旧代码。
- Vite `npm run build` 只生成 `quantia/fontWeb/dist/`；Tornado 实际从 [quantia/web/static](../../../quantia/web/static) 提供静态文件——必须人工拷贝。

## 操作流程

### A. 仅后端 Python 改动
1. 本地：在仓库根目录运行
   ```powershell
   q:\tools\Quantia\quantia\bin\run_web.bat
   ```
   先 `Ctrl+C` 终止旧进程再启动新的；服务地址 http://localhost:9988。
2. 远程（生产）：
   ```bash
   /root/Quantia/quantia/bin/restart_web.sh
   ```
3. 如果改动了内置策略模板代码，重启后再调用一次同步接口确认生效：
   ```bash
   curl -X POST http://localhost:9988/quantia/api/strategy/sync_templates
   ```

### B. 仅前端改动（要部署给 Tornado）
1. 在 [quantia/fontWeb](../../../quantia/fontWeb) 目录：
   ```powershell
   npm run build
   ```
2. 把构建产物拷贝到 Tornado 静态目录（PowerShell）：
   ```powershell
   Copy-Item -Recurse -Force `
     q:\tools\Quantia\quantia\fontWeb\dist\* `
     q:\tools\Quantia\quantia\web\static\
   ```
   Linux：
   ```bash
   cp -r quantia/fontWeb/dist/* quantia/web/static/
   ```
3. 浏览器强刷（Ctrl+F5）验证。

### C. 前后端都改了
按 A → B 顺序执行。前端开发期可只跑 `npm run dev`（Vite 5173 端口）配合后端 9988，无需每次拷贝 dist。

## 自检清单
- [ ] 旧 Tornado 进程已被终止（`Get-Process python | Where-Object MainWindowTitle -like "*web_service*"` / `ps aux | grep web_service`）
- [ ] 新进程启动日志里看到 "Starting Tornado on :9988"
- [ ] 改了模板时，`/quantia/api/strategy/sync_templates` 返回 `{"status":"ok"}`
- [ ] 前端改动：`quantia/web/static/index.html` 时间戳更新

## 常见踩坑
- **改了代码但浏览器一切如旧** → 99% 是没重启 web_service 或没拷贝 dist。
- **同步接口报模板冲突** → 那条模板的 `user_modified=1` 且与官方 hash 不同；这是设计内的保护，不要绕过——按需手动在 DB 里 reset `user_modified=0` 或在前端重新保存。
- **dev 模式调通的页面，build 后白屏** → 检查 `vite.config.ts` 里的 `base` 路径是否与 Tornado 静态挂载点一致。
