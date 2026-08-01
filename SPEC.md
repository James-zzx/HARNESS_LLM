# AI Agent Harness — 设计规约 (SPEC)

## 1. 项目概述

安全、自主、可分发地运行编码型 AI Agent 的 Harness。通过 subprocess 沙箱、治理护栏、HITL 状态机、声明式配置等机制，在受控环境中执行 LLM 产出的编码任务。

**目标用户**: 需要在受控、可审计环境中运行编码 agent 的开发者 / 团队，特别是需要确保 agent 不会执行危险操作、且能根据测试反馈自我修正的场景。

**为什么值得做**: 现有编码 agent 工具（Claude Code、Codex 等）将 LLM 决策与执行捆绑在同一个黑盒中，用户无法控制 agent 的行为边界，也无法在危险操作前获得人工审批。Harness 将 LLM 的"决策"与"执行"解耦，让用户通过声明式规则约束 agent 的权限、行为和工作流。

## 2. 用户故事

| ID | 标题 | 角色 | 故事 | 验收标准 |
|----|------|------|------|---------|
| US-1 | 运行编码任务 | 开发者 | 作为开发者，我想通过一个 YAML 文件定义编码任务（如"修复所有 lint 错误"），然后让 harness 自动驱动 agent 完成，这样我无需手动监控每一步。 | 给定一个 task.yaml，`harness run task.yaml` 启动 agent 并在完成后输出结果。 |
| US-2 | 拦截危险命令 | 开发者 | 作为开发者，我不想让 agent 意外执行危险命令（如 `rm -rf /`），希望 harness 在检测到危险命令时暂停执行并等待我审批。 | 当 agent 尝试执行 `rm -rf /` 时，harness 暂停并显示 HITL 审批提示。 |
| US-3 | 验证代码质量 | 开发者 | 作为开发者，我希望 agent 修改代码后自动运行 `make test`，如果测试失败则让 agent 修正，直到测试通过或达到最大迭代次数。 | 配置 `eval_command: make test` 后，agent 每次修改代码后自动运行测试，失败则重试。 |
| US-4 | 安全配置 API Key | 开发者 | 作为开发者，我不想在配置文件或环境变量中明文存储 API Key，希望 harness 提供安全的录入和存储方式。 | 首次运行 `harness cred set` 时隐藏输入，`harness cred list` 不显示明文。 |
| US-5 | 通过 WebUI 监控任务 | 开发者 | 作为开发者，我希望通过浏览器查看任务执行状态、日志和结果，并能通过 WebUI 审批或拒绝 HITL 暂停请求。 | 启动 harness 后通过浏览器访问 WebUI，可看到任务列表、状态和 HITL 审批按钮。 |
| US-6 | 脱离 LLM 测试 | 开发者 | 作为测试者，我想在不连接真实 LLM 的情况下验证 harness 的核心逻辑（拦截、反馈、循环），确保每次测试结果确定。 | 使用 MockLLM 替换真实 LLM 后，运行 `pytest` 所有测试通过，不依赖网络。 |
| US-7 | 并行运行多个任务 | 开发者 | 作为开发者，我希望同时运行多个独立任务，它们互不干扰，各自有独立的沙箱和日志。 | 同时提交两个任务，它们并行执行，各自的日志和状态独立。 |

## 3. 功能规约

### 模块 1: Task Definition & Execution
- **输入**: YAML/JSON 任务文件
- **接口**: CLI (`harness run task.yaml`), REST API (FastAPI), Open Design WebUI
- **输出**: 任务执行结果
- **关键文件**: `src/harness/cli.py`, `src/harness/api.py`, `src/harness/open_design.py`, `src/harness/task.py`

### 模块 2: Sandbox & Resource Limiting
- **方案**: subprocess 启动 agent 进程，通过 OS 权限限制（Windows: Job Object / Linux: cgroups）
- **限制项**: CPU 时间、内存上限、文件系统访问白名单、网络访问控制
- **关键文件**: `src/harness/sandbox.py`

### 模块 3: Logging & Tracing
- **方案**: 结构化日志 (structlog)，支持 JSON 输出
- **追踪**: 每个请求/任务分配 trace_id，贯穿所有子模块
- **关键文件**: `src/harness/logger.py`

### 模块 4: Result Evaluation & Scoring
- **方案**: 执行 `make test` 或自定义命令，抓取 stdout/stderr
- **输出**: 确定性数据结构 `{passed: bool, output: str, error: str}`
- **关键文件**: `src/harness/evaluator.py`

### 模块 5: Action/Tool Executor
- **方案**: LLM 输出意图（如 `write_file`, `run_shell`, `read_file`）→ 确定性函数调用
- **安全**: 所有工具经过 sandbox 权限校验
- **关键文件**: `src/harness/tool_executor.py`

### 模块 6: Main Loop / Orchestrator
- **方案**: 状态机驱动的主循环
- **状态**: `INIT → TASK_LOADED → LLM_CALL → TOOL_EXEC → EVAL → HITL_CHECK → COMPLETED/FAILED/PAUSED`
- **关键文件**: `src/harness/orchestrator.py`

### 模块 7: Governance & HITL State Machine
- **危险命令检测**: 预定义规则（`rm -rf`, `git push --force`, `DROP TABLE` 等）
- **状态机**: `RUNNING → PAUSED (HITL) → APPROVED / REJECTED / TIMEOUT → RUNNING`
- **接口**: CLI 输入 / WebUI 按钮
- **超时**: 默认 300s 后自动拒绝
- **关键文件**: `src/harness/hitl.py`

### 模块 8: Context & Memory Management
- **会话内记忆**: 维护消息历史列表
- **上下文窗口管理**: 按 token 数裁剪，保留最近 N 条消息
- **关键文件**: `src/harness/memory.py`

### 模块 9: Declarative Configuration
- **格式**: YAML/JSON
- **内容**: 沙箱限制参数、HITL 规则、LLM 端点、超时、日志级别等
- **禁止**: API Key 不在此模块中硬编码，仅引用凭据存储中的 key
- **关键文件**: `src/harness/config.py`

### 模块 10: Credential Secure Storage
- **方案**: 调用 OS 钥匙串（Windows: Credential Manager / macOS: Keychain / Linux: secret-tool）
- **功能**: 首次启动隐藏输入引导、CLI 查看/清除（不回显明文）
- **关键文件**: `src/harness/credential_store.py`

### 模块 11: Distribution & CI/CD
- **Dockerfile**: 多阶段构建，最小运行镜像
- **PyInstaller**: 可选单文件分发
- **CI**: GitHub Actions，含 unit-test job（必须 pass）
- **关键文件**: `Dockerfile`, `.github/workflows/ci.yml`

### 模块 12: Mock-LLM & Test Base
- **LLM Adapter**: 抽象接口 `LLMClient`，含 `chat(messages) → response`
- **MockLLM**: 预置响应列表，循环返回，无网络依赖
- **测试基座**: `BaseHarnessTest` 提供 mock_llm, config, orchestrator 等 fixture
- **关键文件**: `src/harness/llm_adapter.py`, `src/harness/mock_llm.py`, `src/tests/base.py`

### 模块 13: Open Design Integration (WebUI/Design Layer)
- **方案**: 集成 Open Design (https://github.com/nexu-io/open-design) 作为 WebUI 和设计层
- **架构**:
  - Harness 启动 `od` daemon 作为托管的子进程（`--headless --no-open`）
  - 通过 HTTP API（`http://127.0.0.1:7456`）与 daemon 通信
  - 通过 `OD_DATA_DIR` 环境变量隔离数据目录
- **集成功能**:
  - **任务界面**: Open Design 的 WebUI 显示 Harness 的任务状态、日志、评估结果
  - **HITL 审批面板**: Open Design 插件接收 HITL 暂停事件，提供批准/拒绝按钮
  - **Artifact 预览**: 使用 Open Design 的 iframe 沙箱预览 agent 生成的 HTML 产物
  - **设计系统**: 通过 `DESIGN.md` 定义 Harness 自身的品牌和 UI 风格
- **所选设计系统与 skill**: 使用 Open Design 内置的 `minimal` 设计系统（基础排版、配色、组件），skill 为 `harness-dashboard`（自定义 skill，用于任务监控和 HITL 审批）
- **集成方式**: 三种路径并存
  - **HTTP API 客户端**（主要）: `OpenDesignClient` 封装对 daemon REST API 的调用
  - **CLI 子进程包装器**（备用）: 通过 `od` 命令行执行操作
  - **MCP stdio 客户端**（可选）: 通过 MCP 协议与 daemon 的 stdio 服务器通信
- **关键文件**: `src/harness/open_design.py`, `src/tests/test_open_design.py`

## 4. 非功能性需求

### 4.1 性能
- **任务启动延迟**: 从 CLI 输入到 agent 首次 LLM 调用 ≤ 3s
- **并发任务**: 支持至少 3 个任务并行执行
- **日志吞吐**: 每秒至少处理 1000 条日志条目，不影响主循环性能

### 4.2 安全（含凭据威胁模型）
- **凭据威胁模型**:
  - **威胁 T1 - 硬编码泄露**: 开发者意外将 API Key 硬编码到源码中 → 对策: 代码审查 + CI 扫描（git-secrets）
  - **威胁 T2 - 日志泄露**: 凭据被写入日志文件 → 对策: logger 对所有 `key`、`secret`、`token` 字段自动脱敏
  - **威胁 T3 - Shell history 泄露**: 通过命令行参数传入 Key → 对策: 禁止命令行参数传入 Key，仅通过钥匙串或隐藏输入
  - **威胁 T4 - 进程环境泄露**: 其他进程读取 `/proc/*/environ` → 对策: 推荐使用钥匙串而非环境变量，使用环境变量时在 README 中提示风险
  - **威胁 T5 - Git 历史泄露**: Key 被提交到仓库 → 对策: `.gitignore` 排除 `.env` 文件，CI 中检测凭据泄露
- **沙箱安全**: subprocess 限制文件系统白名单、命令黑名单、网络访问控制
- **HITL 超时**: 默认 300s 后自动拒绝，防止挂起任务

### 4.3 可用性
- **CLI 优先**: 所有功能可通过 CLI 完成，WebUI 为辅助
- **错误消息**: 所有错误场景输出中文可读的错误提示和建议修复步骤
- **配置文件**: 提供 `harness init` 生成默认配置，注释说明每个字段

### 4.4 可观测性
- **结构化日志**: JSON 格式，可被 log aggregator 消费
- **分布式追踪**: 每个任务分配唯一 trace_id，贯穿所有子模块日志
- **健康检查**: REST API 提供 `/health` 端点

## 5. 系统架构

```
┌─────────────────────────────────────────────────────────┐
│         CLI / REST API (FastAPI) / Open Design WebUI     │  ← 模块 1
└──────────────┬──────────────────────────┬───────────────┘
               │                          │
┌──────────────▼──────────┐  ┌────────────▼──────────────┐
│  Declarative Config     │  │  Open Design Daemon (od)  │  ← 模块 13
│  Credential Store       │  │  · WebUI (Next.js)        │
│  (OS Keychain)          │  │  · REST API (Express)     │
└──────────────┬──────────┘  │  · MCP stdio server       │
               │             │  · Design system registry  │
               │             │  · Artifact preview/export  │
               │             └────────────────────────────┘
               │                          │
               │              HTTP / subprocess
               │                          │
┌──────────────▼──────────────────────────▼──────────────┐
│              Main Loop / Orchestrator                   │  ← 模块 6
│  ┌──────────┐ ┌──────────┐ ┌──────────────────────┐   │
│  │Task Exec │ │Tool Exec │ │Governance & HITL     │   │  ← 模块 5, 7
│  └──────────┘ └──────────┘ └──────────────────────┘   │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────────┐   │
│  │Memory    │ │Evaluator │ │Logging & Tracing     │   │  ← 模块 8, 4, 3
│  └──────────┘ └──────────┘ └──────────────────────┘   │
│  ┌────────────────────────────────────────────────┐   │
│  │         LLM Adapter (Mock/Real)                │   │  ← 模块 12
│  └────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────┐
│              Sandbox (subprocess)                        │  ← 模块 2
└─────────────────────────────────────────────────────────┘
```

**数据流**:
1. 用户通过 CLI/API/WebUI 提交任务（YAML/JSON）
2. Orchestrator 解析任务 → 加载配置 → 初始化 Memory
3. 主循环：LLM 调用 → 解析意图 → 工具执行（经 Sandbox + HITL 检查）→ 结果回灌
4. 任务完成后调用 Evaluator（`make test`）→ 结果回灌给 LLM 进行修正
5. 所有阶段日志通过 Logger 写入（带 trace_id）
6. 状态变更推送到 Open Design WebUI

**外部依赖**:
- LLM 供应商 API（OpenAI / Anthropic 等，通过凭据存储中的 Key）
- OS 钥匙串服务（Windows Credential Manager / macOS Keychain / Linux Secret Service）
- Open Design 可执行文件（`od`，需用户安装）

## 6. 数据模型

### 6.1 Task（任务定义）
```
Task {
  id: str                          # UUID
  prompt: str                      # 任务提示词
  eval_command: str | None         # 评估命令（如 "make test"）
  max_iterations: int              # 最大迭代次数（默认 10）
  timeout: int                     # 单次 LLM 调用超时（秒，默认 120）  
  sandbox: SandboxConfig           # 沙箱配置
  created_at: datetime
  status: TaskStatus               # pending / running / paused / completed / failed
}
```

### 6.2 Message（对话消息）
```
Message {
  role: str                        # "system" | "user" | "assistant" | "tool"
  content: str                     # 消息内容
  tool_calls: list[ToolCall] | None  # assistant 消息中的工具调用
  tool_result: ToolResult | None     # tool 消息中的执行结果
  timestamp: datetime
}
```

### 6.3 ToolCall（工具调用）
```
ToolCall {
  id: str                          # 调用 ID
  tool_name: str                   # 工具名（write_file / run_shell 等）
  parameters: dict                 # 参数
}
```

### 6.4 ToolResult（工具执行结果）
```
ToolResult {
  success: bool
  output: str                      # stdout
  error: str                       # stderr（如有）
  exit_code: int
}
```

### 6.5 EvaluationResult（评估结果）
```
EvaluationResult {
  passed: bool                     # 测试是否通过
  output: str                      # 完整输出
  error: str                       # 错误信息
  exit_code: int
}
```

### 6.6 HarnessConfig（配置）
```
HarnessConfig {
  llm: LLMConfig                   # LLM 端点、模型、Key 引用
  sandbox: SandboxConfig           # 沙箱限制参数
  hitl: HITLConfig                 # 危险命令规则、超时
  logging: LoggingConfig           # 日志级别、输出路径
  open_design: OpenDesignConfig    # OD daemon 配置
  credential: CredentialConfig     # 凭据服务配置
}
```

### 6.7 实体关系
```
HarnessConfig 1──1 CredentialStore
HarnessConfig 1──* Task
Task 1──1 ConversationMemory
Task 1──* Message
Message 0──* ToolCall
ToolCall 1──1 ToolResult
Task 1──0..1 EvaluationResult
```

## 7. 凭据与分发设计

### 7.1 凭据存储方案
- **存储后端**: OS 钥匙串（Windows Credential Manager / macOS Keychain / Linux Secret Service），通过 `keyring` 库统一接口
- **录入流程**:
  1. 首次运行 `harness cred set` 时，提示用户输入 API Key
  2. 输入时隐藏回显（`getpass`）
  3. 确认后存储到 OS 钥匙串
- **管理命令**:
  - `harness cred set <service> <key>` — 存储（隐藏输入）
  - `harness cred get <service> <key>` — 获取（仅程序内部使用）
  - `harness cred delete <service> <key>` — 删除
  - `harness cred list <service>` — 列出 Key 名称（不显示明文）
- **配置引用**: 配置文件中通过 `credential_ref: "service/key"` 引用，不直接包含 Key 值
- **环境变量备选**: 支持 `HARNESS_API_KEY` 环境变量，但需在 README 提示明文风险

### 7.2 分发方案
- **容器分发（首选）**: Dockerfile 多阶段构建，基于 `python:3.11-slim`
  - `docker build -t harness .`
  - `docker run -v /path/to/config:/config harness run /config/task.yaml`
  - Key 通过 `-e HARNESS_API_KEY=...` 或挂载钥匙串 socket
- **PyPI 分发（备选）**: `pip install harness-llm`
- **目标平台**: Linux (amd64), macOS (arm64 + amd64), Windows (amd64)
- **限制**: 需目标机器安装 Python 3.11+；钥匙串依赖各平台原生服务

## 8. 技术选型与理由

| 项 | 选择 | 理由 |
|---|------|------|
| 语言 | Python 3.11+ | AI 生态最成熟，LLM SDK 支持最好，pytest 生态完善 |
| CLI | click | 成熟稳定，支持命令嵌套、自动帮助文档 |
| API | FastAPI + uvicorn | 异步性能好，自动 OpenAPI 文档，适合 REST + WebSocket |
| WebUI | Open Design Daemon | 满足课程强制要求，提供设计系统、artifact 预览等能力 |
| 配置 | PyYAML + json | 广泛使用，用户熟悉度高 |
| 日志 | structlog | 结构化日志，支持 JSON 输出，适合可观测性 |
| 测试 | pytest + pytest-cov | 最广泛使用的 Python 测试框架 |
| 钥匙串 | keyring | 跨平台统一接口，支持 Windows/macOS/Linux |
| 打包 | hatchling | 现代 Python 打包工具，pep621 标准 |
| CI | GitHub Actions | 与 GitHub 仓库深度集成，免费 |
| 设计/UI 引擎 | Open Design | 课程要求，开源、本地优先、支持 MCP 集成 |

## 9. 验收标准

| 模块 | 验收标准 |
|------|---------|
| 模块 1: Task | 给定 YAML 任务文件，CLI 命令 `harness run` 启动任务并在完成后输出 JSON 结果 |
| 模块 2: Sandbox | 白名单外文件写入被拒绝；黑名单命令被拦截；超时后进程被终止 |
| 模块 3: Logger | 每条日志包含 trace_id，输出 JSON 格式，敏感字段自动脱敏 |
| 模块 4: Evaluator | `make test` 输出被正确解析为 `{passed, output, error}`，失败时可回灌给主循环 |
| 模块 5: Tool Executor | `write_file`、`read_file`、`run_shell` 等工具正确执行并返回结构化结果 |
| 模块 6: Orchestrator | 给定 MockLLM 预设响应，状态机按预期路径转换（写文件 → 评估 → 修正 → 完成） |
| 模块 7: HITL | 危险命令被拦截；HITL 暂停后审批/拒绝/超时均正确；拒绝后 LLM 收到反馈 |
| 模块 8: Memory | 消息可添加、读取、按 token 裁剪；跨轮对话上下文正确传递 |
| 模块 9: Config | 默认值 → 文件 → 环境变量 → CLI 覆盖正确；无效配置报错清晰 |
| 模块 10: Credential | Key 存储后可用程序读取；list 不显示明文；delete 后无法读取 |
| 模块 11: CI/CD | `docker build` 成功；`pytest` 在 CI 中通过 |
| 模块 12: MockLLM | MockLLM 按预设顺序返回响应；替换真实 LLM 后所有测试仍通过 |
| 模块 13: Open Design | `od` daemon 可被启动/停止；WebUI 可访问并显示任务状态 |

## 10. 风险与未决问题

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| R1: OS 钥匙串不可用（如容器环境） | 凭据无法安全存储 | 中 | 降级到加密文件 + 主密码；容器中推荐环境变量 + 文档提示风险 |
| R2: subprocess 沙箱在 Windows 上限制不完整 | 沙箱绕过 | 中 | 优先实现 Linux 沙箱，Windows 提供基础进程隔离 |
| R3: LLM 返回格式不稳定（JSON 解析失败） | 主循环卡死 | 高 | 解析失败时重试 + 格式要求注入系统提示 |
| R4: 用户未安装 Open Design | WebUI 不可用 | 中 | CLI 和 API 作为主要交互方式，WebUI 为可选增强 |
| R5: 长时间运行任务导致内存泄漏 | 进程崩溃 | 低 | 设置最大迭代次数和超时；定期清理 Memory |
| R6: MockLLM 与真实 LLM 行为差异大 | 测试覆盖不足 | 低 | 在 SPEC 中明确 MockLLM 的边界，补充集成测试 |

## 11. 领域与机制设计

### 11.1 Coding 领域的四类机制

**（1）动作 / 工具**

| 工具 | 输入 | 输出 | 安全检查 |
|------|------|------|---------|
| `read_file(path)` | 文件路径 | 文件内容 | 路径在白名单内 |
| `write_file(path, content)` | 路径 + 内容 | 写入结果 | 路径在白名单内 |
| `edit_file(path, old, new)` | 路径 + 替换内容 | 编辑结果 | 路径在白名单内 |
| `run_shell(command)` | shell 命令 | stdout/stderr/exit_code | 命令不在黑名单 + HITL 检查 |
| `list_dir(path)` | 目录路径 | 文件列表 | 路径在白名单内 |

**实现方式**: 确定性代码（`Tool` 基类 + `ToolRegistry` + `ToolExecutor`），不依赖 LLM 判断。

**（2）客观反馈信号**

| 信号 | 来源 | 格式 | 用途 |
|------|------|------|------|
| 测试通过/失败 | `make test` 的 exit_code | `{passed: bool, output: str}` | 驱动 agent 自我修正 |
| 编译错误 | 编译器 stderr | `{error: str}` | 失败分类 + 重试 |
| lint 错误 | linter 输出 | `{errors: list}` | 质量门禁 |

**实现方式**: `Evaluator` 执行命令 → 解析输出 → 结构化为确定性数据 → 回灌给主循环。**不是提示词**——移除 LLM 后，评估逻辑仍然可独立测试。

**（3）危险动作**

| 危险动作 | 检测方式 | 响应 |
|---------|---------|------|
| `rm -rf /`, `rm -rf /*` | 正则匹配命令 | HITL 暂停 |
| `git push --force` | 正则匹配命令 | HITL 暂停 |
| `DROP TABLE`, `DROP DATABASE` | 正则匹配命令 | HITL 暂停 |
| `format C:`, `del /F /S` | 正则匹配命令 | HITL 暂停 |
| 白名单外文件写入 | Sandbox 路径检查 | 直接拒绝 |
| 网络访问（如禁用时） | Sandbox 网络检查 | 直接拒绝 |

**实现方式**: `Guardrail` 类（`check(action) → GuardrailResult`）——确定性代码，**不是提示词**。测试时传入 `Action(command="rm -rf /")`，断言拦截，每次结果确定。

**（4）记忆**

| 记忆类型 | 内容 | 存储方式 | 提供方式 |
|---------|------|---------|---------|
| 会话内记忆 | 本轮对话历史 | 内存列表 | 全量（按 token 裁剪） |
| 任务上下文 | 任务 prompt、评估结果 | 结构化字段 | 每次 LLM 调用注入 |
| 工具执行历史 | 上轮工具调用与结果 | 内存列表 | 每次 LLM 调用注入 |

**实现方式**: `ConversationMemory` 类管理消息列表，`get_context_window(max_tokens)` 按 token 数裁剪。可注入 mock 测试。

### 11.2 重点维度：治理护栏（Governance）

**为什么选择治理作为重点维度**: 治理（护栏 / 沙箱 / HITL 状态机）天然由代码构成，最符合"移除 LLM 后仍可用单测验证"的硬性要求。治理逻辑的每次执行结果都是确定性的，可以精确测试每一个边界条件。

**深入实现**:
- **多层护栏架构**:
  1. **沙箱层**（Sandbox）: 文件系统白名单、命令黑名单、网络控制、资源限制
  2. **规则引擎层**（Guardrail）: 可配置的危险命令规则（支持正则、精确匹配）
  3. **HITL 状态机层**（HITLStateMachine）: 暂停 ↔ 审批/拒绝/超时 → 结果回灌
- **确定性测试**:
  - `Guardrail.check(Action("rm -rf /"))` → `{intercepted: true, reason: "dangerous_command"}`
  - `Guardrail.check(Action("ls -la"))` → `{intercepted: false}`
  - `HITLStateMachine.pause(task_id)` → `PAUSED`
  - `HITLStateMachine.approve(task_id)` → `RUNNING`
  - `HITLStateMachine.reject(task_id)` → `RUNNING` + 反馈消息注入
  - 以上所有测试使用 MockLLM，无需真实 LLM，无需网络

### 11.3 机制实现与可测试性映射

| 机制 | 代码文件 | 测试文件 | 移除 LLM 后可测？ |
|------|---------|---------|-----------------|
| 工具执行 | `tool_executor.py` | `test_tool_executor.py` | ✅ 直接传入工具调用 |
| 治理拦截 | `hitl.py` | `test_hitl.py` | ✅ 直接传入危险命令 |
| 反馈回灌 | `evaluator.py` | `test_evaluator.py` | ✅ mock subprocess 输出 |
| 记忆读写 | `memory.py` | `test_memory.py` | ✅ 直接添加/读取消息 |
| 主循环状态机 | `orchestrator.py` | `test_orchestrator.py` | ✅ MockLLM 预设响应 |
| 配置加载 | `config.py` | `test_config.py` | ✅ 直接加载配置文件 |

## 12. 实现顺序

### Phase 1 — 基础设施（模块 3, 9, 10, 12）
```
1. 项目骨架 (pyproject.toml, 目录结构)
2. 模块 9: 声明式配置系统
3. 模块 10: 凭据安全存储
4. 模块 12: LLM Adapter + MockLLM
5. 模块 3: 日志与追踪
```
- **可测试**: 是，完全脱离 LLM

### Phase 2 — 核心执行（模块 5, 6, 8）
```
6. 模块 5: Action/Tool Executor
7. 模块 8: Context & Memory
8. 模块 6: Main Loop / Orchestrator
```
- **可测试**: 通过 MockLLM 验证确定性行为

### Phase 3 — 安全与治理（模块 2, 7）
```
9. 模块 2: Sandbox & Resource Limiting
10. 模块 7: Governance & HITL State Machine
```
- **可测试**: HITL 可通过 mock 用户输入测试

### Phase 4 — 评估与任务（模块 1, 4, 13）
```
11. 模块 4: Result Evaluation (make test)
12. 模块 1: Task Definition + CLI + API + Open Design WebUI
13. 模块 13: Open Design Integration (WebUI/Design Layer)
```
- **可测试**: 评估器可 mock subprocess 输出

### Phase 5 — 分发（模块 11）
```
14. Dockerfile
15. GitHub Actions CI
16. README 完善
```

## 13. 文件结构

```
harness_LLM/
├── src/
│   ├── harness/
│   │   ├── __init__.py
│   │   ├── __main__.py          # python -m harness 入口
│   │   ├── main.py              # CLI 入口点
│   │   ├── cli.py               # CLI 命令实现
│   │   ├── api.py               # FastAPI REST API
│   │   ├── open_design.py       # Open Design 集成层 (daemon 管理 + HTTP 客户端)
│   │   ├── config.py            # 配置系统
│   │   ├── credential_store.py  # 凭据存储
│   │   ├── orchestrator.py      # 主循环/编排器
│   │   ├── task.py              # 任务定义与解析
│   │   ├── sandbox.py           # 沙箱/资源限制
│   │   ├── logger.py            # 日志与追踪
│   │   ├── evaluator.py         # 结果评估 (make test)
│   │   ├── tool_executor.py     # 工具/动作执行器
│   │   ├── hitl.py              # 治理护栏与 HITL
│   │   ├── memory.py            # 上下文与记忆管理
│   │   ├── llm_adapter.py       # LLM 客户端接口
│   │   └── mock_llm.py          # Mock LLM 实现
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py          # pytest fixtures
│       ├── base.py              # 测试基座
│       ├── test_config.py
│       ├── test_credential_store.py
│       ├── test_llm_adapter.py
│       ├── test_mock_llm.py
│       ├── test_logger.py
│       ├── test_tool_executor.py
│       ├── test_memory.py
│       ├── test_orchestrator.py
│       ├── test_sandbox.py
│       ├── test_hitl.py
│       ├── test_evaluator.py
│       ├── test_task.py
│       └── test_open_design.py
├── examples/
│   └── task.yaml                # 示例任务文件
├── Dockerfile
├── pyproject.toml
├── .github/
│   └── workflows/
│       └── ci.yml
├── SPEC.md
├── PLAN.md
├── SPEC_PROCESS.md
├── AGENT_LOG.md
└── README.md
```

## 14. 测试策略

| 层级 | 工具 | 目标 |
|------|------|------|
| Unit Test | pytest | 每个模块的独立行为，MockLLM 替代真实 LLM |
| Integration | pytest | 模块间协作（如 Orchestrator → ToolExecutor → Sandbox） |
| E2E | pytest + subprocess | 完整任务执行流程，使用 MockLLM |

**关键原则**: 所有模块 5-8 的测试必须通过 MockLLM 验证，不依赖真实网络/LLM。

**机制演示**（见 §A.6）:
1. **治理护栏**: 传入 `Action("rm -rf /")` → `GuardrailResult(intercepted=True)` — 确定性测试
2. **反馈闭环**: MockLLM → "写文件" → Evaluator(mock "make test" 失败) → 回灌 → MockLLM 收到错误 → "修正" → Evaluator(mock "make test" 通过) → 完成
3. **重点维度（治理）**: HITL 暂停 → 拒绝 → 反馈回灌 → LLM 换方案 → 验证后续动作不是原危险命令