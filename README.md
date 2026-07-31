# AI Agent Harness

安全、自主、可分发地运行编码型 AI Agent 的 Harness。它将 LLM 的「决策」与「执行」解耦，通过 subprocess 沙箱、治理护栏（Guardrail）、HITL 人工审批状态机、声明式配置与 OS 钥匙串凭据存储，在受控、可审计的环境中执行 LLM 产出的编码任务，并在危险操作前获得人工批准。

- **Python**: 3.11+
- **发行包**: `harness-llm`（PyPI）/ 镜像 `harness`（Docker）
- **CLI**: `harness`（`python -m harness`）
- **命令**: `run` / `webui` / `cred` / `config` / `init`
- **接口**: CLI + FastAPI REST API + Open Design WebUI

## 快速开始

### 安装

从 PyPI 安装：

```bash
pip install harness-llm
```

或从源码安装（开发模式）：

```bash
python -m pip install -e .
```

两种方式都会安装 `harness` 命令。如果你的 Python 环境的 Scripts 目录不在 `PATH` 中（例如 Windows Store 版 Python），请使用等价的 `python -m harness` 形式——本 README 统一使用该形式。

验证安装：

```bash
python -m harness --help
```

### 运行一个任务

`examples/task.yaml` 是开箱即用的示例任务，配合 `examples/config.yaml`（`llm.mock: true`，MockLLM 离线确定性执行，不依赖网络）可验证安装与任务流程：

```bash
python -m harness run --config examples/config.yaml examples/task.yaml
```

MockLLM 默认空预设会确定性跑满 `max_iterations` 后以 `status=FAILED` 退出（退出码 1），这是预期行为——它离线走完了「加载任务 → LLM 调用 → 工具/评估循环 → 结果摘要」的完整主循环。配置了真实 LLM 凭据后，直接运行任务文件即可（默认 `llm.mock: false`，调用真实模型）：

```bash
python -m harness run task.yaml
```

### 初始化项目

在当前目录生成一份纯默认值（无注释）的 `harness.yaml`（带注释的可配置示例见 `examples/config.yaml`）：

```bash
python -m harness init
```

### 查看生效配置

查看默认值 + 配置文件 + 环境变量合并后的生效配置（敏感字段自动脱敏为 `***`）：

```bash
python -m harness config show
```

## CLI 使用指南

```
python -m harness [OPTIONS] COMMAND [ARGS]...

Commands:
  config  Inspect the effective harness configuration.
  cred    Manage credentials stored securely in the OS keyring.
  init    Create a default harness.yaml in the current directory.
  run     Run a task definition (YAML) through the harness.
  webui   Start the Open Design daemon and print its web UI URL.
```

### `run` — 运行任务

```bash
python -m harness run <task.yaml> [--config PATH] [--verbose] [--timeout SECONDS]
```

- `task.yaml` — YAML/JSON 任务定义文件（见「任务定义」）。
- `--config` — 指定 harness 配置文件路径。
- `--verbose` — 启用 DEBUG 日志。
- `--timeout` — 覆盖任务超时（秒）。

任务完成后输出结果摘要；状态非 `COMPLETED` 时退出码为 1：

```
status=COMPLETED iterations=3 state=COMPLETED
```

任务通过真实的沙箱与 HITL 执行（`build_runtime` 接线）：`sandbox.blocked_commands` 命中的命令被拒绝执行，`hitl.dangerous_commands` 命中的命令触发人工审批并暂停任务，`run_shell` 受 `sandbox.timeout` 限制、超时会被强制终止。

### `cred` — 凭据管理

```bash
python -m harness cred set <service> <key>       # 存储（隐藏输入，不落终端/Shell 历史）
python -m harness cred get <service> <key>       # 读取（程序内部使用）
python -m harness cred delete <service> <key>    # 删除
python -m harness cred list <service>            # 列出 Key 名（不显示明文）
```

`set` 使用 `getpass` 隐藏回显；`list` 只输出 Key 名称，不泄露凭据值。示例：

```bash
python -m harness cred set harness openai
```

配置中通过 `credential_ref: harness/openai`（格式 `service/key`）引用，而非直接写 Key 值。

### `config` — 查看配置

```bash
python -m harness config show [--config PATH]
```

### `init` — 生成默认配置

```bash
python -m harness init
```

生成纯默认值（无注释）的 `harness.yaml`；带注释的可配置示例见 [examples/config.yaml](examples/config.yaml)。若当前目录已存在 `harness.yaml` 会报错，避免覆盖。

### `webui` — 启动 Open Design 面板

```bash
python -m harness webui [--config PATH]
```

读取配置：`open_design.enabled: true` 时启动 `od` 守护进程并打印 Web UI 地址，`Ctrl+C` 停止并回收守护进程；未启用时提示设置 `open_design.enabled: true` 并以退出码 0 返回。详见「Open Design WebUI（可选）」。

## 配置说明

配置文件为 YAML（也支持 JSON），包含 6 个 section：

| Section | 关键字段 | 默认值 | 说明 |
|---------|---------|--------|------|
| `llm` | `mock` / `model` / `base_url` / `credential_ref` / `timeout` / `max_retries` | `mock: false`, `model: gpt-4o`, `timeout: 120`, `max_retries: 3` | LLM 端点与模型；`mock: true` 使用 MockLLM（离线，不访问凭据存储）；`credential_ref` 引用凭据 `service/key` |
| `sandbox` | `enabled` / `timeout` / `max_memory_mb` / `allowed_dirs` / `blocked_dirs` / `blocked_commands` / `network` | `enabled: true`, `allowed_dirs: ["."]`, `network: deny`, `blocked_commands: ["rm -rf /", "shutdown", "format", "dd if="]` | 子进程沙箱：文件系统白名单、命令黑名单、网络 `allow/deny`、资源限制 |
| `hitl` | `enabled` / `dangerous_commands` / `approval_timeout` | `enabled: true`, `approval_timeout: 300` | 危险命令规则引擎与 HITL 审批超时；`dangerous_commands` 默认并集 `["rm -rf", "shutdown", "format", "dd if=", "git push --force", "DROP TABLE"]` |
| `logging` | `level` / `format` / `file_path` | `level: INFO`, `format: console` | 结构化日志；`format: json` 输出 JSON，`file_path` 开启 JSON 日志文件 |
| `open_design` | `enabled` / `port` / `data_dir` / `daemon_url` | `enabled: false`, `port: 3000`, `data_dir: .open_design` | Open Design WebUI 集成 |
| `credential` | `service` / `backend` | `service: harness`, `backend: keyring` | 凭据存储后端：`keyring`（OS 钥匙串）或 `env`（环境变量）。`env` 从 `HARNESS_<SERVICE>_<KEY>` 读取（如 `llm/api_key` → `HARNESS_LLM_API_KEY`），值在进程环境中明文可见 |

完整可注释示例见 [examples/config.yaml](examples/config.yaml)。

### 环境变量覆盖

环境变量使用 `HARNESS_<SECTION>_<FIELD>` 命名，可覆盖文件配置：

```bash
export HARNESS_LLM_MOCK=true              # 使用 MockLLM
export HARNESS_LLM_CREDENTIAL_REF=harness/openai
export HARNESS_HITL_APPROVAL_TIMEOUT=120
export HARNESS_SANDBOX_NETWORK=allow
```

### 合并优先级

```
默认值 < 配置文件 < 环境变量(HARNESS_*) < CLI 参数（如 --timeout）
```

### 任务定义（Task）

任务文件为 YAML/JSON，字段如下（[examples/task.yaml](examples/task.yaml)）：

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | 是 | 任务 ID |
| `prompt` | 是 | 任务提示词 |
| `eval_command` | 否 | 评估命令（如 `python -m pytest`），缺省则不评估 |
| `max_iterations` | 否 | 最大迭代次数（默认 10） |
| `timeout` | 否 | 单任务超时秒数（默认 120） |

## 架构说明

```
┌──────────────────────────────────────────────────────────┐
│    CLI (click) / REST API (FastAPI) / Open Design WebUI    │
└──────────────┬───────────────────────────┬────────────────┘
               │                           │
┌──────────────▼──────────┐   ┌────────────▼──────────────┐
│  Declarative Config      │   │  Open Design Daemon (od)  │
│  Credential Store        │   │  · WebUI / REST API       │
│  (OS Keyring)            │   │  · OD_DATA_DIR 隔离        │
└──────────────┬───────────┘   └────────────┬───────────────┘
               │                            │
               │          HTTP / subprocess │
┌──────────────▼────────────────────────────▼──────────────┐
│                Orchestrator（状态机主循环）                 │
│  LLM_CALL → HITL_CHECK → TOOL_EXEC → EVAL → 循环/完成      │
│  ┌────────┐  ┌────────┐  ┌─────────┐  ┌──────────┐       │
│  │ToolExec│  │Guardrail│  │Memory   │  │Evaluator │       │
│  └────────┘  └────────┘  └─────────┘  └──────────┘       │
│  ┌────────────────────────────────────────────────┐      │
│  │        LLM Adapter（OpenAIClient / MockLLM）    │      │
│  └────────────────────────────────────────────────┘      │
└───────────────────────────────────────────────────────────┘
               │
┌──────────────▼───────────────────────────────────────────┐
│              Sandbox（subprocess 沙箱/资源限制）           │
└──────────────────────────────────────────────────────────┘
```

- **模块**（`src/harness/`）：`cli.py`/`main.py`（CLI）、`api.py`（FastAPI）、`config.py`（配置）、`credential_store.py`（凭据）、`orchestrator.py`（主循环）、`task.py`（任务解析）、`sandbox.py`（沙箱）、`hitl.py`（治理 + HITL 状态机）、`tool_executor.py`（工具执行）、`memory.py`（记忆/上下文）、`evaluator.py`（评估）、`logger.py`（日志/追踪）、`llm_adapter.py` + `mock_llm.py`（LLM 适配）、`open_design.py`（WebUI 集成）。

### 状态机

**编排状态机**：`INIT → TASK_LOADED → LLM_CALL → HITL_CHECK → TOOL_EXEC → EVAL → COMPLETED / FAILED / PAUSED`（到达 `max_iterations` 或超时进入 `FAILED`）。

**HITL 状态机**：`RUNNING → PAUSED → APPROVED / REJECTED / TIMEOUT → RUNNING`，默认 `approval_timeout=300s` 自动拒绝。

### 三层治理护栏

1. **沙箱层（Sandbox）**：文件系统白名单 `allowed_dirs`、命令黑名单 `blocked_commands`、网络 `allow/deny`、子进程超时与内存限制。
2. **规则引擎层（Guardrail）**：`dangerous_commands` 子串规则 + 可配置正则规则，对工具调用（如 `run_shell`）做确定性检测。
3. **HITL 状态机层**：危险命令触发 `PAUSED`，经 CLI 阻塞输入（`y/n/t`）或 REST/WebUI 外部决策批准/拒绝/超时，拒绝时构造反馈消息回灌给 LLM 要求换方案。

以上三层已通过 `build_runtime(config)` 接入生产执行路径：`harness run` 与 REST API 的任务均构造真实的 `Sandbox` + `HITLGate` 执行（不再是 library-only 组件），沙箱拒绝的命令不会被执行，HITL 拒绝会暂停任务并把反馈回灌给 LLM。所有护栏逻辑为确定性代码，可用 MockLLM 离线单测验证（如 `GuardrailEngine().check("rm -rf /") → True`）。

### LLM 适配与离线测试

`LLMClient` 抽象接口定义 `chat(messages) → Response`；`OpenAIClient` 走真实 OpenAI 兼容 `/chat/completions` 端点；`MockLLM(preset_responses)` 循环返回预设响应，无网络依赖。`LLMFactory` 依据 `llm.mock` 选择实现；`build_llm(config)` 在非 mock 模式通过凭据存储（后端见 `credential.backend`）解析 `credential_ref` 注入 API key。测试基座 `BaseHarnessTest` 提供 `mock_llm` fixture（config / orchestrator 等由具体测试自行装配）。

### 日志与追踪

基于 structlog 的结构化日志：每条日志带 `trace_id`（贯穿同一任务的所有子模块）与 `phase`；支持 `console`/`json` 两种格式；`key`/`secret`/`token`/`password` 字段自动脱敏为 `***`。

## 凭据安全配置说明

- **存储**：凭据通过 `keyring` 库存入 OS 原生钥匙串（Windows Credential Manager / macOS Keychain / Linux Secret Service），不落盘明文。
- **`env` 后端**：`credential.backend: env` 时，凭据从环境变量 `HARNESS_<SERVICE>_<KEY>` 读取（`credential_ref: llm/api_key` → `HARNESS_LLM_API_KEY`），用 `.env` 文件 + `set -a` 或容器 `-e` 注入；环境变量为明文且对同机进程可见（`/proc/*/environ`），仅在钥匙串不可用（如容器）时使用。
- **Mock 模式**：`llm.mock: true` 完全不访问凭据存储（不触碰钥匙串/环境变量），离线安全运行。
- **录入**：`harness cred set <service> <key>` 使用 `getpass` 隐藏输入，避免进入 Shell 历史与终端日志。
- **引用**：配置中仅写 `credential_ref: <service>/<key>`，绝不硬编码 Key 值；`harness config show` 与日志都会将敏感字段脱敏。
- **列出**：`harness cred list <service>` 只显示 Key 名称，不显示明文。
- **Git 安全**：`.env` 已被 `.gitignore` 排除；请勿将任何真实凭据提交到仓库。
- **环境变量备选（注意风险）**：也支持 `HARNESS_LLM_CREDENTIAL_REF` 等 `HARNESS_*` 变量，但进程环境可能被同机其他进程读取（如 `/proc/*/environ`），因此优先使用钥匙串，仅在容器等钥匙串不可用的场景使用环境变量并知晓风险。

## 分发说明

### Docker

多阶段构建（`python:3.11-slim`，builder 构建 wheel，runtime 非 root 用户 `appuser` 运行，健康检查）：

```bash
docker build -t harness .
docker run harness --help
docker run -v "$(pwd)/examples:/config" harness run --config /config/config.yaml /config/task.yaml
```

镜像入口为 `python -m harness`（默认 `--help`），与 CLI 用法一致。

### PyPI

```bash
pip install harness-llm
python -m harness --help
```

发行包 `harness-llm`（版本见 `pyproject.toml`，当前 `0.1.0`），提供 `harness` console script 入口。

## 开发指南

### 环境准备

```bash
git clone <repo> && cd harness_LLM
python -m pip install --group dev -e .   # 安装包 + dev 依赖（pytest / pytest-cov / ruff）
```

### 运行测试

```bash
python -m pytest src/tests/                # 全部测试（当前 140 个，全部通过）
python -m pytest --cov=harness src/tests/  # 覆盖率
python -m ruff check src/                  # Lint
```

所有核心逻辑（编排、工具执行、治理、HITL、评估、记忆、配置）均通过 MockLLM 离线验证，**不依赖网络或真实 LLM**，保证测试结果确定性。测试基座见 `src/tests/base.py`（`BaseHarnessTest`）。

### 开发流程

本项目遵循 TDD（先写失败测试 → 变红 → 最少代码变绿 → 重构）与分阶段并行开发（见 [PLAN.md](PLAN.md)）：

- 设计变更先更新 [SPEC.md](SPEC.md)（设计规约），再落 [PLAN.md](PLAN.md)（执行计划）。
- 每阶段在独立 worktree/分支开发，产出可合并的 PR；所有 PR 需通过 CI（unit-test / lint / build）后才合并。
- 过程文档见 [SPEC_PROCESS.md](SPEC_PROCESS.md) 与 [AGENT_LOG.md](AGENT_LOG.md)。

### CI

[.github/workflows/ci.yml](.github/workflows/ci.yml) 在 push / pull_request 时触发三个必须全部通过的 job：

- `unit-test`：`pip install --group dev -e .` → `pytest --cov=harness src/tests/`
- `lint`：`ruff check src/`
- `build`：`docker build -t harness .` → `docker run harness --help`

### REST API（可选）

```bash
python -m uvicorn harness.api:app
```

| 端点 | 说明 |
|------|------|
| `POST /api/tasks` | 提交任务（JSON 任务定义），返回 `task_id`（201） |
| `GET /api/tasks/{id}` | 查询任务状态、迭代数、日志、错误 |
| `GET /api/tasks/{id}/logs` | 获取任务日志 |
| `POST /api/hitl/{task_id}/approve` | 批准 HITL 暂停请求 |
| `POST /api/hitl/{task_id}/reject` | 拒绝 HITL 暂停请求 |

API 任务默认走与 CLI 相同的真实运行时（`build_runtime` + 沙箱 + HITL），凭据通过 `build_llm` 按 `config.credential.backend` 解析；`llm.mock: true` 时离线运行，不触碰凭据存储。每个任务使用独立的 `harness-task-*` 工作目录，互不干扰。

### Open Design WebUI（可选）

配置 `open_design.enabled: true` 后，`OpenDesignClient` 会以子进程启动 `od --headless --no-open` 守护进程，通过 `OD_DATA_DIR` 隔离数据目录，并经 HTTP 与守护进程通信（`health_check`/`list_projects`/`create_artifact` 等）。若 `od` 不在 PATH 中会抛出 `ODNotFoundError`，此时 CLI 与 REST API 仍可正常使用（WebUI 为可选增强）。详见 [SPEC.md](SPEC.md)。
