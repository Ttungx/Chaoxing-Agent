# ChaoxingAgent

<p align="center">
  <a href="https://github.com/Ttungx/Chaoxing-Agent"><img src="https://img.shields.io/github/stars/Ttungx/Chaoxing-Agent?style=flat-square&logo=github" alt="Stars"></a>
  <a href="https://github.com/Ttungx/Chaoxing-Agent/blob/main/LICENSE"><img src="https://img.shields.io/github/license/Ttungx/Chaoxing-Agent?style=flat-square" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.10+-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/tauri-2-FFC107?style=flat-square&logo=tauri&logoColor=white" alt="Tauri 2">
  <img src="https://img.shields.io/badge/platform-Windows-0078D4?style=flat-square&logo=windows&logoColor=white" alt="Windows">
</p>

学习通本地自动化答题工具 — Python 内核（截图 / 视觉 / 点击 / 状态机）+ Tauri 2 桌面壳 + React 前端。

本项目非常适用于文科类水课考试，尤其考试只限定学习通手机 App 的场景；当然如果配置的模型比较优秀，也适用于工科、理科类考试。具体的作答效果取决于所配置模型的能力上限。

## 📑 目录

[ChaoxingAgent](#chaoxingagent)

[📑 目录](#-目录)

[它是什么 / 它不是什么](#它是什么--它不是什么)

[实现方案](#实现方案)

[安全机制（为什么没有"作弊"风险）](#安全机制为什么没有作弊风险)

[两种运行方式](#两种运行方式)

[功能](#功能)

[环境要求](#环境要求)

[快速开始](#快速开始)

[配置说明](#配置说明)

[模型服务](#模型服务)

[CLI 命令](#cli-命令)

[架构 / 运维](#架构--运维)

[免责声明](#免责声明)

## 它是什么 / 它不是什么

ChaoxingAgent 是一个**本地化、纯视觉驱动**的答题辅助工具。它不接入任何学习平台 API、不查询题库、不爬取答案、不代理 HTTP 请求到考试服务器。它只做一件事：

> **截取一个外部投屏窗口（手机画面）的局部区域，调用用户自带的 LLM 视觉模型解析题目，再调用用户自带的 LLM 文本模型作答，然后通过 Windows 系统级鼠标事件点击屏幕上的选项和"下一题"按钮。**

整个工具的所有数据流、模型调用、点击操作都发生在**用户自己的 Windows 机器**上。用户自己提供 vision / solver 模型的 API key，工具不存储、不转发、不缓存任何题目内容到外部服务器（除用户配置的模型 API 端点本身外）。

其核心运行原理是借助手机投屏软件（如 vivo 手机投屏、scrcpy 等）将手机画面投射到电脑屏幕，再通过纯视觉方案截取并识别屏幕内容、模拟鼠标点击来操控手机，整个过程不触及学习通 App 的任何内部接口，从而最大程度规避被检测的风险。

## 实现方案

工具的原理非常简单，可以概括为"看屏幕 → 思考 → 点屏幕"三步循环：

1. **看屏幕**：定时截取一个外部投屏窗口（用户预先框选的手机画面区域）
2. **思考**：把截图发给用户自带的视觉模型，识别题干和选项；再发给用户自带的文本模型，让它选答案
3. **点屏幕**：用 Windows 系统级鼠标事件（`SendInput`）在屏幕上点对应的选项和"下一题"按钮，然后检测画面是否已经翻到下一题，没翻就等、翻了就回到第 1 步

整个循环在用户自己的机器上跑，不接触学习平台后端，不查询题库，不改浏览器，不代理 HTTP。模型 API key 由用户提供，工具不存储、不转发题目内容。

主程序有同步（CLI）和异步（带 Tauri 桌面壳）两个版本，逻辑一样。

## 安全机制（为什么没有"作弊"风险）

工具的定位是**辅助视障 / 行动不便用户、或自动化 QA / 题库练习**，不是绕过学习平台规则。设计上从 5 个层面把"作弊能力"关死：

### 1. 不接触平台后端

工具**不**做这些事：

- 不调用学习平台的任何 API
- 不查询 / 不爬取 / 不缓存题库
- 不修改平台的请求头、Cookie、Session
- 不代理浏览器、不注入 JS、不开 DevTools Protocol
- 不读浏览器 localStorage / cookie / token

它只做一件事：在屏幕上找像素、点像素。**和用手指点屏幕在机制上没有区别**——区别只在于"手指"是 Windows 系统级鼠标事件模拟的硬件点击。

### 2. 不点交卷按钮（硬安全边界）

视觉模型只要识别到"交卷"或"提交"语义，状态机**立即停**。没有任何运行时开关可以关掉这个行为。需要交卷时必须**用户自己点**。

工具只暴露"点选项"和"点下一题"两个点击入口，**没有**"点交卷"或通用点击函数。

### 3. 不模拟浏览器自动化

- 用的是 **Windows 系统级 `SendInput`**，模拟硬件鼠标事件，**不**经过任何浏览器 automation 通道
- 不开 CDP（Chrome DevTools Protocol）
- 不用 Selenium / Playwright / Puppeteer 之类的 WebDriver
- 不修改 `navigator.webdriver` / 不挂自动化标志

学习平台即使检测浏览器自动化 flag 也检测不到这个工具（它根本不走浏览器通道）。反过来，**正因为它不接触平台后端**，平台也没有"自动化"维度可以检测——它就是用户在用自己的鼠标点击。

### 4. 用户完全控制 + 强制人工接管点

工具设计了 6 个暂停触发条件，**任何**一个命中都强制停下来等人接管：

- 模型答得没把握（置信度低）
- 检测到非题目的弹窗
- 视觉模型判断不了页面是什么
- 标定后窗口大小变化过大（防止点击坐标错位）
- 连续错误次数过多
- 跑满总步数上限

每个暂停点都需要用户在前端点"继续 / 重试 / 跳过 / 停止"。**没有任何"全自动无人值守"模式。**

### 5. 数据留在本机

- 所有 trace（截图 + 题目 + 答案 + 置信度）只写本地目录（已被 `.gitignore` 排除）
- API key 放在本地 `.env`（已被 `.gitignore` 排除，模板在 `.env.example`）
- 真实配置文件（config、model services）都被 `.gitignore` 排除
- 工具本身不联网（除用户配置的模型 API 端点外），不向后台上报任何使用统计
- 开源：所有代码可审计

## 两种运行方式

### A. 桌面壳（Tauri 2）— 完整体验

```bash
# 一次性：装 Python 依赖
uv venv && uv pip install -r requirements.txt

# 初始化本地配置
uv run python main.py --init-config

# 起桌面壳（自动 beforeDevCommand 拉 vite dev server）
cd src-tauri && cargo tauri dev
```

### B. 纯 Python（无 UI，调试快）

```bash
uv venv && uv pip install -r requirements.txt
uv run python main.py --init-config
uv run python main.py
```

## 功能

- 手动框选手机画面区域（标定向导）
- 视觉模型解析题目结构（题干 / 选项 / 按钮位置）
- 文本模型作答
- 自动点击选项和下一题
- 遇到交卷按钮自动停止
- 完整 trace 日志（每步截图 + JSON）
- Tauri 2 桌面壳：原生窗口 + 配置 / 监控 / 日志 / 历史 / 标定 5 个 tab

## 环境要求

- Windows 10+（用 `pywin32` 操控窗口和点击）
- Python 3.10+
- [uv](https://github.com/astral-sh/uv)
- Rust toolchain（仅 Tauri 壳需要；见 `src-tauri/Cargo.toml::rust-version`）
- Node.js ≥ 18（仅前端 build 需要）

## 快速开始

```bash
# 1. 进入项目目录
cd ChaoxingAgent

# 2. 创建虚拟环境并安装依赖
uv venv
uv pip install -r requirements.txt

# 3. 初始化本地配置（首次运行会自动从 *.example 复制生成）
uv run python main.py --init-config   # 强制从 example 覆盖 config.json / model_services.json
uv run python main.py --init-env      # 重新生成 config/.env

# 4. 配置手机投屏目标（config/config.json）
#    打开 config/config.json，在 "target" 部分填入手机投屏软件的进程名或 PID：
#      - process_name: 投屏软件的进程名（如 "vivoScreen"、"scrcpy" 等，可在 Windows 任务管理器中查看）
#      - pid: 投屏软件的进程 PID（更精确，可选；不填则自动按进程名查找）
#    二者至少填一个，程序启动时会自动绑定该进程的顶层窗口。
#    常见的手机投屏/远程操控软件包括：vivo 手机投屏、scrcpy、Vysor、AirDroid 等。
#
# 5. 配置模型服务（config/model_services.json + config/.env）
#    a) 编辑 config/model_services.json，为 vision（视觉模型）和 solver（文本模型）分别设置：
#       - base_url: 模型 API 地址（任何 OpenAI 兼容端点均可）
#       - model_id: 模型名称
#       - api_key_env: API key 对应的环境变量名（默认 VISION_API_KEY / SOLVER_API_KEY）
#    b) 编辑 config/.env，填入对应的 API key：
#       VISION_API_KEY=你的视觉模型API密钥
#       SOLVER_API_KEY=你的文本模型API密钥
#    注意：config/.env 中的变量名必须与 model_services.json 中 api_key_env 字段的值保持一致。
#
# 6a. 仅跑 Python（不开 UI）
uv run python main.py

# 6b. 跑 Tauri 桌面壳（需要先有 Rust + Node）
cd src-tauri && cargo tauri dev
```

## 配置说明

- 所有可调模板都以 `*.example` 形式入库，真实配置由 `.gitignore` 排除
- 模板字段含义放在 `config/*.example.md` 中
- `config/.env` **仅**承载模型服务相关项：
  - `VISION_API_KEY` / `SOLVER_API_KEY`（由 `model_services.json` 的 `api_key_env` 指向）
  - 可选覆盖：`CHAOXING_VISION_<FIELD>` / `CHAOXING_SOLVER_<FIELD>`，FIELD 可为 `BASE_URL` / `MODEL_ID` / `API_KEY_ENV` / `API_TYPE`
- 其它运行时参数（`config.json`）**不**通过 `.env` 覆盖

## 模型服务

视觉和文本模型各使用一个 OpenAI 兼容 provider（任何 `/v1/chat/completions` 端点都可用：OpenAI、Azure、自建网关、自部署 LLM...）。

```json
{
  "vision": { "api_type": "openai", "base_url": "...", "api_key_env": "VISION_API_KEY", "model_id": "..." },
  "solver": { "api_type": "openai", "base_url": "...", "api_key_env": "SOLVER_API_KEY", "model_id": "..." }
}
```

完整字段说明见 `config/config.json.example.md` 和 `config/model_services.json.example`。

> 免费小米MIMO模型（6月29日前有效）：
>
> key：tp-ckv5kg8nm399yc3gc7oecvu0uu34hqwyetvxcr6pzkycjbzq
>
> Base_url：
> https://token-plan-cn.xiaomimimo.com/anthropic
> https://token-plan-cn.xiaomimimo.com/v1

## CLI 命令

| 命令 | 作用 |
|------|------|
| `uv run python main.py` | 启动 Python 主程序（首次会自动复制本地配置） |
| `uv run python main.py --init-config` | 强制从 example 覆盖 `config.json` / `model_services.json`（不会覆盖已有 `config/.env`） |
| `uv run python main.py --init-env` | 重新生成 `config/.env.example` |
| `uv run python -m chaoxing_agent --rpc` | 启动 RPC 子进程（被 Tauri 壳调用） |
| `cd src-tauri && cargo tauri dev` | Tauri 桌面壳开发模式（自动跑 vite dev） |
| `cd src-tauri && cargo tauri build` | Tauri release 构建（自动跑 vite build + bundle） |

## 架构 / 运维

- 整体设计 + NDJSON 协议：见 `docs/architecture.md`
- 故障排查 / 冒烟测试：见 `docs/runbook.md`
- 外部集成（写新 host 接入 RPC）：见 `docs/integration-guide.md`

## 免责声明

本工具仅用于授权场景下的自测、题库练习、自动化 QA 或内部测试。

**严禁**用于：

- 真实考试、认证考核
- 绕过学习平台规则或反作弊系统
- 任何未授权的自动化操作

使用本工具产生的一切后果由使用者自行承担。

> 工具本身**不携带**绕过反作弊的能力（详见上文"安全机制"），但"用户拿着普通工具做违规事"不在工具设计能管的范围。**是否合规取决于使用场景**，不由工具决定。

## TODO

- [x] CLI功能实现

- [ ] 发布 Release
- [ ] 项目趋于稳定后整理好代码库和文档

