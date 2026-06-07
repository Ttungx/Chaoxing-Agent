# CLAUDE.md — 项目级规则与指引

## 仓库操作规则

- **未经用户明确指示，不要执行 `git commit`、`git push`、`git merge`、`git branch -d/-D` 等写历史/远程的操作。**
- **问题未解决前不要提交**：在用户明确确认"已解决/可以提交"前，不要把任何与当前正在调试/修复的问题相关的代码改动或临时修补加入提交。
- 允许的操作：读取文件、编辑文件、运行验证命令（`uv run ...`、`compileall` 等）、`git status`/`diff`/`log` 等只读查询。
- 在用户明确指示提交时，再创建提交；提交信息应基于本次会话产生的具体改动。
- 提交前必须先运行 fresh 验证（`superpowers:verification-before-completion` 纪律）并展示 evidence，再宣称完成。
- 写历史类操作完成后，必须用 `git log --oneline -N` 显式展示结果给用户确认。

## 工作流

- 使用中文与用户沟通。
- 涉及多步实现时优先使用 `superpowers` 工作流（brainstorming → writing-plans → subagent-driven-development / executing-plans）。
- 实现完成后做最终验证（导入、schema、syntax、关键行为断言）并贴出 evidence。
- 落地代码时遵循 `superpowers:test-driven-development` 的纪律（最小验证先行），但允许对纯配置文件跳过 TDD。

## 进程拓扑（Tauri 2 壳 + Python 内核）

- Tauri 2 desktop shell 在 `src-tauri/`，Web 前端在 `web/`，Python 内核在 `chaoxing_agent/`。
- Tauri 通过 `uv run python -m chaoxing_agent --rpc` 启子进程；stdin/stdout 跑 NDJSON RPC。
- Python `__main__.py` 是**唯一**子进程入口（缺它就启动失败，`No module named chaoxing_agent.__main__`）。启动顺序：`emit("ready")` → `RpcServer.serve()`，**先发 request 会被忽略**。
- Tauri 命令只有 3 个：`start_python` / `stop_python` / `rpc_call`（`src-tauri/src/lib.rs::invoke_handler`）。其他 IPC 全部走 `rpc_call` + 14 个 Python handler。
- 详细架构 / 故障排查 / 集成协议见 `docs/architecture.md` / `docs/runbook.md` / `docs/integration-guide.md`。

## 配置职责边界

- `config/config.json`：运行时参数（target、viewport、timing、thresholds、page_change、runtime）。
- `config/model_services.json`：模型服务配置。当前主路径为 v2 单 provider 结构（`vision` / `solver` 各一个 provider）；兼容多 provider registry 时使用 `selected.<role>_model`。
- `config/.env`（被 `.gitignore` 排除；模板见 `config/.env.example`）：**仅**承载模型服务相关覆盖 —
  - 模型 API key（由 `model_services.json` 的 `api_key_env` 指向）
  - `CHAOXING_VISION_<FIELD>` / `CHAOXING_SOLVER_<FIELD>` 覆盖 provider 字段，其中 `<FIELD>` ∈ `{BASE_URL, MODEL_ID, API_KEY_ENV, API_TYPE}`
- 不要把 `config.json` 的可调字段（target/viewport/timing/...）也搬到 `.env`。

## 关键性能/安全约束（Agent 进入本项目时必须知道）

- **不要给 vision provider 传 `enable_thinking:true` / `reasoning_effort`**: 当前 v2 视觉端点（`mimo-v2.5`）一旦开启思考，单次调用 30~40s；`vision.extra_body` 应关闭思考，单次 ~7s。
- **vision `max_tokens` 不要 < 3000**: 低于 3000 会 finish=length 空回；真实返回约 720 字符。
- **solver 必须开 `use_response_format=true` 且 `max_tokens >= 2000`**: 关闭 JSON mode 或低 max_tokens 会 finish=length 空回。配 `reasoning_effort=low` 启用低深度思考。
- **点击屏幕坐标前必须 `mapper.refresh()`**: `click_options` / `click_next_button` 已自动 refresh；如果未来增加新的点击入口，必须遵守。
- **视觉 box 必须落在截图内**: `state_machine._box_in_image` 越界即暂停；不要把这个保护删掉。
- **不要让 `main.py` 等接口出现提交按钮的运行时开关**（`stop_on_submit` 已废弃）: 那是硬安全边界。完整机制（不点交卷 / 系统级 `SendInput` / 强制人工接管点 / 数据本机）见 `README.md` 的"安全机制"段。

## Tauri 2 / Rust 侧踩坑（高频踩过）

- **Tauri 2 `EventId` 是 `pub type EventId = u32`**（`tauri-2.11.2/src/event/mod.rs:19`），**无 `Drop` 实现**。`let _ = app.listen(...)` **不会**取消订阅，listener 一直存活到 AppHandle 销毁。要主动取消订阅必须绑变量再 `unlisten`。
- **`tauri.conf.json::bundle.icon` Windows 必须含 `.ico`**：当前 `icons/icon.ico` 是 766 字节占位，正式发布前要换。
- **`beforeBuildCommand` 用 `npm --prefix ../web run build`**（cwd-robust 形式），不要用裸 `npm run build`（依赖 cwd 是 web/）。
- **Python `rpc_call` 错误契约**：Python `RpcMessage::Error` 走 `Result::Err(String)`，**不** smuggle 成 `Result::Ok({"error": {...}})`。前端必须检查 invoke 的 rejected 状态。这条对应项目自己的 `model_switch 拒绝假成功` 规则（commit 7ef0273）。

## 临时/可清理物

- `test.py`（工作区根）是手动基准脚本，不应入库，已加进 `.gitignore`。
- `.ui-preview/` 是 Vite 预览缓存，已加进 `.gitignore`。
- `design-system/` 是设计稿资源（不入库），已加进 `.gitignore`；如需保留供前端参考请告知。
