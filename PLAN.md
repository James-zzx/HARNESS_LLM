# AI Agent Harness — 执行计划 (PLAN)

## 约定

- **任务编号**: `P{phase}-{seq}`，如 `P1-01`
- **依赖**: 前置任务编号列表，空表示无依赖
- **并行**: 同一层级的任务可并行执行（不同 worktree）
- **复杂度**: S/M/L/XL
- **产出**: 每个任务产出可合并的 PR
- **TDD 流程**: 先写失败测试 → 得到红色结果 → 编写最少代码使其变绿 → 重构

---

## Phase 1: 基础设施 (基础层)

> 所有后续模块依赖此层，需优先完成并保证质量。

### P1-01: 项目骨架初始化
- **依赖**: 无
- **并行**: —
- **复杂度**: S
- **涉及文件**: `pyproject.toml`, `src/harness/__init__.py`, `src/harness/__main__.py`, `src/tests/__init__.py`, `src/tests/conftest.py`
- **内容**:
  - [ ] 创建 `pyproject.toml` (hatchling 构建, 依赖: click, fastapi, uvicorn, pyyaml, structlog, keyring, httpx)
  - [ ] 创建 `src/harness/` 包结构，含 `__init__.py` 和 `__main__.py`
  - [ ] 创建 `src/tests/` 包结构，含 `__init__.py` 和 `conftest.py` 基础 fixture
  - [ ] 验证: `pip install -e .` 可安装，`python -m harness` 输出帮助信息
- **验证步骤**:
  - [ ] `pip install -e .` 成功无报错
  - [ ] `python -m harness --help` 输出非空帮助信息
  - [ ] `pytest src/tests/` 无测试但至少运行不报错

### P1-02: 配置系统 (Config)
- **依赖**: P1-01
- **并行**: P1-03, P1-04, P1-05
- **复杂度**: M
- **涉及文件**: `src/harness/config.py`, `src/tests/test_config.py`, `examples/config.yaml`
- **内容**:
  - [ ] 定义 `HarnessConfig` dataclass (所有可配置项)
  - [ ] 实现 `load_config(path: str) -> HarnessConfig` 从 YAML/JSON 加载
  - [ ] 实现配置合并: 默认值 → 文件配置 → 环境变量 → CLI 覆盖
  - [ ] 实现配置校验 (schema validation)
  - [ ] 示例配置文件 `examples/config.yaml`
- **TDD 先写测试**:
  - [ ] `test_load_default_config`: 无文件时返回默认配置
  - [ ] `test_load_yaml_config`: 加载 YAML 文件并验证字段
  - [ ] `test_config_merge`: 环境变量覆盖文件配置
  - [ ] `test_config_validation`: 无效配置抛出 `ConfigError`
- **验证步骤**:
  - [ ] `pytest src/tests/test_config.py` 全部通过
  - [ ] 手动运行 `harness config show` 输出默认配置

### P1-03: 凭据安全存储 (Credential Store)
- **依赖**: P1-01
- **并行**: P1-02, P1-04, P1-05
- **复杂度**: M
- **涉及文件**: `src/harness/credential_store.py`, `src/tests/test_credential_store.py`
- **内容**:
  - [ ] 实现 `CredentialStore` 类 (封装 keyring)
  - [ ] `set_key(service, key, value)` — 存储
  - [ ] `get_key(service, key) -> str` — 读取
  - [ ] `delete_key(service, key)` — 删除
  - [ ] `list_keys(service) -> list` — 列出 (不显示明文)
  - [ ] 首次启动隐藏输入引导 (`getpass`)
  - [ ] CLI 命令: `harness cred set/get/delete/list`
- **TDD 先写测试**:
  - [ ] `test_set_and_get`: 存储后可通过相同 key 读取
  - [ ] `test_delete`: 删除后 get 返回 None
  - [ ] `test_list_hides_plaintext`: list 输出不包含明文值
  - [ ] `test_key_not_found`: 不存在的 key 返回 None
- **验证步骤**:
  - [ ] `pytest src/tests/test_credential_store.py` 全部通过
  - [ ] 手动运行 `harness cred set test-service test-key` 隐藏输入正常
  - [ ] `harness cred list test-service` 不显示明文

### P1-04: LLM Adapter + MockLLM
- **依赖**: P1-01
- **并行**: P1-02, P1-03, P1-05
- **复杂度**: M
- **涉及文件**: `src/harness/llm_adapter.py`, `src/harness/mock_llm.py`, `src/tests/test_llm_adapter.py`, `src/tests/test_mock_llm.py`, `src/tests/base.py`
- **内容**:
  - [ ] 定义 `LLMClient` 抽象基类，`chat(messages: list[Message]) -> Response` 接口
  - [ ] 定义 `Message` / `Response` dataclass
  - [ ] 实现 `OpenAIClient` (真实 LLM 调用，httpx)
  - [ ] 实现 `MockLLM(preset_responses: list[str])` (循环返回预设响应)
  - [ ] 实现 `LLMFactory` 根据配置创建对应实例
  - [ ] 实现 `BaseHarnessTest` 测试基座 (提供 mock_llm fixture)
- **TDD 先写测试**:
  - [ ] `test_mock_llm_returns_preset`: MockLLM 返回预设响应列表
  - [ ] `test_mock_llm_cycles`: 超出预设数量时循环回到第一个
  - [ ] `test_llm_factory_creates_mock`: 配置 `llm.mock=true` 时创建 MockLLM
  - [ ] `test_llm_factory_creates_openai`: 配置 `llm.mock=false` 时创建 OpenAIClient
- **验证步骤**:
  - [ ] `pytest src/tests/test_llm_adapter.py src/tests/test_mock_llm.py` 全部通过
  - [ ] MockLLM 确定性: 相同预设输入，100 次调用返回相同结果

### P1-05: 日志与追踪系统 (Logger)
- **依赖**: P1-01
- **并行**: P1-02, P1-03, P1-04
- **复杂度**: S
- **涉及文件**: `src/harness/logger.py`, `src/tests/test_logger.py`
- **内容**:
  - [ ] 配置 structlog (控制台 + JSON 文件输出)
  - [ ] 实现 `get_logger(name) -> Logger` 工厂
  - [ ] 实现 `TraceContext` 上下文管理器 (trace_id 贯穿)
  - [ ] 自动添加 trace_id, module, phase 到每条日志
  - [ ] 日志级别: DEBUG / INFO / WARNING / ERROR
  - [ ] 敏感字段自动脱敏 (key, secret, token, password)
- **TDD 先写测试**:
  - [ ] `test_logger_creates_entry`: logger.info 输出包含预期字段
  - [ ] `test_trace_context_adds_trace_id`: 上下文内日志包含 trace_id
  - [ ] `test_trace_context_nesting`: 嵌套上下文 trace_id 不同
  - [ ] `test_sensitive_field_redaction`: 日志中 key 字段被替换为 `***`
- **验证步骤**:
  - [ ] `pytest src/tests/test_logger.py` 全部通过
  - [ ] 手动检查 JSON 日志文件内容格式正确

---

## Phase 2: 核心执行层

> 依赖 Phase 1 完成。此层通过 MockLLM 可完全脱离 LLM 测试。

### P2-01: Action/Tool Executor
- **依赖**: P1-01, P1-05
- **并行**: P2-02
- **复杂度**: M
- **涉及文件**: `src/harness/tool_executor.py`, `src/tests/test_tool_executor.py`
- **内容**:
  - [ ] 定义 `Tool` 基类 (`name`, `description`, `execute(params) -> Result`)
  - [ ] 实现内置工具:
    - [ ] `read_file(path)` — 读取文件
    - [ ] `write_file(path, content)` — 写入文件
    - [ ] `edit_file(path, old_string, new_string)` — 编辑文件
    - [ ] `run_shell(command)` — 执行 shell 命令
    - [ ] `list_dir(path)` — 列出目录
  - [ ] 实现 `ToolRegistry` (注册/查找工具)
  - [ ] 实现 `ToolExecutor` (解析 LLM 意图 → 调用对应工具)
  - [ ] 安全校验: 每个工具执行前检查 sandbox 权限
  - [ ] 结果格式化: 统一返回 `ToolResult {success, output, error}`
- **TDD 先写测试**:
  - [ ] `test_write_and_read_file`: 写入文件后读取内容一致
  - [ ] `test_edit_file`: 替换字符串后文件内容正确
  - [ ] `test_run_shell_echo`: 执行 echo 命令返回预期输出
  - [ ] `test_run_shell_failure`: 执行不存在命令返回非零 exit_code
  - [ ] `test_tool_registry_lookup`: 注册后可通过名称查找
  - [ ] `test_tool_executor_parse_intent`: 解析 JSON 意图并调用正确工具
- **验证步骤**:
  - [ ] `pytest src/tests/test_tool_executor.py` 全部通过
  - [ ] 手动测试: 创建临时目录，执行 write → read → edit → list 序列

### P2-02: Context & Memory Manager
- **依赖**: P1-01, P1-05
- **并行**: P2-01
- **复杂度**: M
- **涉及文件**: `src/harness/memory.py`, `src/tests/test_memory.py`
- **内容**:
  - [ ] 定义 `Message` dataclass (role, content, tool_calls, timestamp)
  - [ ] 实现 `ConversationMemory` 类
  - [ ] `add_message(msg)` — 添加消息
  - [ ] `get_history() -> list[Message]` — 获取完整历史
  - [ ] `get_context_window(max_tokens) -> list[Message]` — 按 token 裁剪
  - [ ] `clear()` — 清空会话
  - [ ] token 估算: 简单字符计数 (4 chars ≈ 1 token)
  - [ ] 策略: 保留系统提示 + 最近 N 轮对话
- **TDD 先写测试**:
  - [ ] `test_add_and_get_history`: 添加消息后历史包含该消息
  - [ ] `test_context_window_truncation`: 超过 max_tokens 时裁剪
  - [ ] `test_context_window_keeps_system_prompt`: 裁剪后系统提示保留
  - [ ] `test_clear`: 清空后历史为空
- **验证步骤**:
  - [ ] `pytest src/tests/test_memory.py` 全部通过
  - [ ] 模拟 20 轮对话后验证裁剪行为

### P2-03: Main Loop / Orchestrator
- **依赖**: P2-01, P2-02, P1-02, P1-04
- **并行**: —
- **复杂度**: XL
- **涉及文件**: `src/harness/orchestrator.py`, `src/tests/test_orchestrator.py`
- **内容**:
  - [ ] 定义状态机状态: `INIT → TASK_LOADED → LLM_CALL → TOOL_EXEC → EVAL → HITL_CHECK → 循环/结束`
  - [ ] 实现 `Orchestrator` 类
  - [ ] `run(task_config)` — 主入口
  - [ ] 状态转换: 每个状态有明确的进入/退出条件
  - [ ] 与 LLM 交互: 调用 `LLMClient.chat()`
  - [ ] 与 ToolExecutor 交互: 解析 LLM 响应 → 执行工具 → 结果回灌
  - [ ] 与 Memory 交互: 每次 LLM 调用前注入上下文
  - [ ] 与 Evaluator 交互: 任务完成后调用评估
  - [ ] 与 HITL 交互: 遇到危险命令时暂停
  - [ ] 错误处理: 超时、重试、崩溃恢复
- **TDD 先写测试**:
  - [ ] `test_orchestrator_completes_task`: MockLLM 预设"写文件"路径 → 状态机到达 COMPLETED
  - [ ] `test_orchestrator_max_iterations`: MockLLM 始终返回同一动作 → 达到 max_iterations 后 FAILED
  - [ ] `test_orchestrator_tool_error`: 工具执行失败 → 错误回灌给 LLM → LLM 换方案
  - [ ] `test_orchestrator_hitl_pause`: MockLLM 返回危险命令 → 状态机进入 PAUSED
  - [ ] `test_orchestrator_full_cycle`: 写文件 → 评估失败 → 修正 → 评估通过 → COMPLETED
- **验证步骤**:
  - [ ] `pytest src/tests/test_orchestrator.py` 全部通过
  - [ ] 所有测试使用 MockLLM，不依赖网络

---

## Phase 3: 安全与治理层

> 依赖 Phase 2 完成。

### P3-01: Sandbox & Resource Limiting
- **依赖**: P2-01
- **并行**: P3-02
- **复杂度**: L
- **涉及文件**: `src/harness/sandbox.py`, `src/tests/test_sandbox.py`
- **内容**:
  - [ ] 定义 `Sandbox` 类
  - [ ] 子进程管理: `Popen` 封装, 超时强制终止
  - [ ] CPU 限制: 进程优先级, 最大运行时间
  - [ ] 内存限制: 监控 RSS, 超限终止
  - [ ] 文件系统限制: 白名单目录, 禁止访问系统目录
  - [ ] 网络限制: 可选禁用/白名单
  - [ ] 命令黑名单: 禁止 `rm -rf /`, `shutdown` 等
  - [ ] 沙箱上下文管理器: `with Sandbox(config) as sb:`
  - [ ] 集成到 ToolExecutor: 每个工具执行前检查沙箱权限
- **TDD 先写测试**:
  - [ ] `test_sandbox_allows_whitelist_path`: 白名单内文件可读写
  - [ ] `test_sandbox_blocks_blacklist_path`: 白名单外文件操作被拒绝
  - [ ] `test_sandbox_blocks_dangerous_command`: `rm -rf /` 被拦截
  - [ ] `test_sandbox_timeout`: 超时后进程被终止
  - [ ] `test_sandbox_context_manager`: with 块退出后进程清理
- **验证步骤**:
  - [ ] `pytest src/tests/test_sandbox.py` 全部通过
  - [ ] 手动测试: 配置白名单后尝试写入系统目录应被拒绝

### P3-02: Governance & HITL State Machine
- **依赖**: P2-03
- **并行**: P3-01
- **复杂度**: L
- **涉及文件**: `src/harness/hitl.py`, `src/tests/test_hitl.py`
- **内容**:
  - [ ] 定义危险命令规则引擎:
    - [ ] 静态规则: `rm -rf`, `git push --force`, `DROP TABLE`, `format C:` 等
    - [ ] 正则匹配: 可配置规则列表
  - [ ] 实现 `HITLStateMachine`:
    - `RUNNING` → `PAUSED` (危险命令触发)
    - `PAUSED` → `APPROVED` / `REJECTED` / `TIMEOUT`
  - [ ] HITL 接口:
    - CLI: 阻塞等待用户输入 `y/n/t`
    - WebUI: 轮询状态 → 按钮点击 (通过 P4-05)
    - 超时: 默认 300s 自动拒绝
  - [ ] 回灌机制: 拒绝时构造错误消息 → 要求 LLM 换方案
  - [ ] 集成到 Orchestrator: 工具执行前调用 HITL 检查
- **TDD 先写测试**:
  - [ ] `test_guardrail_detects_dangerous_command`: `rm -rf /` 被识别为危险
  - [ ] `test_guardrail_allows_safe_command`: `ls -la` 通过检查
  - [ ] `test_hitl_state_transitions`: PAUSED → APPROVED → RUNNING
  - [ ] `test_hitl_timeout`: 超时后自动 REJECTED
  - [ ] `test_hitl_rejection_feedback`: 拒绝后反馈消息包含原危险命令信息
  - [ ] `test_guardrail_regex_pattern`: 自定义正则规则匹配
- **验证步骤**:
  - [ ] `pytest src/tests/test_hitl.py` 全部通过
  - [ ] 所有测试不依赖真实 LLM — 直接传入 Action 对象

---

## Phase 4: 评估与任务层

> 依赖 Phase 2 完成。

### P4-01: Result Evaluator
- **依赖**: P2-01
- **并行**: P4-02
- **复杂度**: M
- **涉及文件**: `src/harness/evaluator.py`, `src/tests/test_evaluator.py`
- **内容**:
  - [ ] 定义 `EvaluationResult` dataclass: `{passed, output, error, exit_code}`
  - [ ] 实现 `Evaluator` 类
  - [ ] 默认评估器: 运行 `make test` 或自定义命令
  - [ ] 输出解析: 抓取 stdout/stderr, 提取红/绿状态
  - [ ] 可扩展: 支持自定义评估脚本
  - [ ] 结果回灌: 将评估结果格式化为结构化数据 → 喂给主循环
- **TDD 先写测试**:
  - [ ] `test_evaluator_passed`: mock subprocess 返回 exit_code=0 → passed=True
  - [ ] `test_evaluator_failed`: mock subprocess 返回 exit_code=1 → passed=False
  - [ ] `test_evaluator_captures_output`: mock subprocess 输出被正确捕获
  - [ ] `test_evaluator_custom_command`: 自定义 eval_command 被正确执行
- **验证步骤**:
  - [ ] `pytest src/tests/test_evaluator.py` 全部通过
  - [ ] 手动测试: 在含 `make test` 的目录中运行 evaluator 验证

### P4-02: Task Definition & Parser
- **依赖**: P1-01, P1-02
- **并行**: P4-01
- **复杂度**: M
- **涉及文件**: `src/harness/task.py`, `src/tests/test_task.py`, `examples/task.yaml`
- **内容**:
  - [ ] 定义 `Task` dataclass: `{id, prompt, eval_command, max_iterations, timeout}`
  - [ ] 实现 `TaskParser`:
    - `load_yaml(path) -> Task`
    - `load_json(path) -> Task`
    - `from_dict(dict) -> Task`
  - [ ] 任务校验: 必要字段, 类型检查
  - [ ] 示例任务: `examples/task.yaml`
- **TDD 先写测试**:
  - [ ] `test_parse_yaml_task`: 解析 YAML 文件返回 Task 对象
  - [ ] `test_parse_json_task`: 解析 JSON 文件返回 Task 对象
  - [ ] `test_task_validation_missing_field`: 缺少必要字段抛出 `TaskError`
  - [ ] `test_task_validation_type_error`: 字段类型错误抛出 `TaskError`
- **验证步骤**:
  - [ ] `pytest src/tests/test_task.py` 全部通过
  - [ ] 手动测试: `harness run examples/task.yaml` 解析正确

### P4-03: CLI Entry Point
- **依赖**: P4-02, P1-03, P1-02
- **并行**: P4-04, P4-05
- **复杂度**: M
- **涉及文件**: `src/harness/cli.py`, `src/harness/main.py`, `src/tests/test_cli.py`
- **内容**:
  - [ ] CLI 命令树:
    - `harness run <task.yaml>` — 执行任务
    - `harness cred set/get/delete/list` — 凭据管理
    - `harness config show` — 查看当前配置
    - `harness init` — 初始化项目 (生成默认配置)
  - [ ] 参数解析: 支持 `--config`, `--verbose`, `--timeout` 等
  - [ ] 错误处理: 友好的错误提示
- **TDD 先写测试**:
  - [ ] `test_cli_run`: 执行 `harness run examples/task.yaml` 返回 0
  - [ ] `test_cli_config_show`: 执行 `harness config show` 输出配置
  - [ ] `test_cli_cred_set`: 执行 `harness cred set` 提示输入
  - [ ] `test_cli_missing_file`: 不存在的 task.yaml 返回非 0
- **验证步骤**:
  - [ ] `pytest src/tests/test_cli.py` 全部通过
  - [ ] 手动运行所有 CLI 命令验证交互

### P4-04: REST API
- **依赖**: P4-02, P1-03, P1-02
- **并行**: P4-03, P4-05
- **复杂度**: M
- **涉及文件**: `src/harness/api.py`, `src/tests/test_api.py`
- **内容**:
  - [ ] FastAPI 应用
  - [ ] 端点:
    - `POST /api/tasks` — 提交任务
    - `GET /api/tasks/{id}` — 查询任务状态
    - `GET /api/tasks/{id}/logs` — 获取任务日志
    - `POST /api/hitl/{task_id}/approve` — 批准
    - `POST /api/hitl/{task_id}/reject` — 拒绝
  - [ ] 后台任务执行 (BackgroundTasks)
  - [ ] 错误处理: 统一异常处理器
- **TDD 先写测试**:
  - [ ] `test_api_create_task`: POST /api/tasks 返回 201 + task_id
  - [ ] `test_api_get_task_status`: GET /api/tasks/{id} 返回状态
  - [ ] `test_api_hitl_approve`: POST /api/hitl/{id}/approve 返回 200
  - [ ] `test_api_task_not_found`: 不存在的 task_id 返回 404
- **验证步骤**:
  - [ ] `pytest src/tests/test_api.py` 全部通过
  - [ ] 手动启动 `harness serve` 后用 curl 测试各端点

### P4-05: Open Design Integration (WebUI/Design Layer)
- **依赖**: P4-04
- **并行**: P4-03, P4-04
- **复杂度**: L
- **涉及文件**: `src/harness/open_design.py`, `src/tests/test_open_design.py`
- **内容**:
  - [ ] 实现 `OpenDesignClient` 类:
    - `start_daemon()` — 启动 `od` 子进程（`--headless --no-open`）
    - `stop_daemon()` — 优雅停止 daemon
    - `health_check() -> bool` — 健康检查 (`GET /api/health`)
    - `list_projects() -> list` — 列出项目 (`GET /api/projects`)
    - `create_artifact(project_id, type, content)` — 创建 artifact
  - [ ] Daemon 生命周期管理:
    - 自动检测 `od` 是否在 PATH 中
    - 通过 `OD_DATA_DIR` 环境变量隔离数据目录
    - 启动/停止/重启/健康监控
    - 日志重定向到 Harness 的日志系统
  - [ ] HITL WebUI 桥接:
    - 通过 Open Design 插件显示 HITL 暂停事件
    - 将批准/拒绝结果回灌给 Orchestrator
  - [ ] 任务状态推送:
    - 通过 WebSocket 或轮询将 Harness 任务状态推送到 Open Design WebUI
  - [ ] 配置:
    - `config.yaml` 中增加 `open_design.enabled`, `open_design.port`, `open_design.data_dir`
- **TDD 先写测试**:
  - [ ] `test_od_client_health_check`: mock HTTP 200 → health_check() 返回 True
  - [ ] `test_od_client_health_failure`: mock HTTP 500 → health_check() 返回 False
  - [ ] `test_od_daemon_start_stop`: mock subprocess → start/stop 调用正确
  - [ ] `test_od_daemon_not_found`: `od` 不在 PATH → 抛出 `ODNotFoundError`
  - [ ] `test_od_create_artifact`: mock POST /api/projects/{id}/artifacts → 返回 artifact_id
- **验证步骤**:
  - [ ] `pytest src/tests/test_open_design.py` 全部通过
  - [ ] 无需真实安装 Open Design — 所有测试 mock 外部依赖

---

## Phase 5: 分发与 CI/CD

> 依赖所有 Phase 完成。

### P5-01: Dockerfile
- **依赖**: 所有 Phase
- **并行**: P5-02
- **复杂度**: S
- **涉及文件**: `Dockerfile`, `.dockerignore`
- **内容**:
  - [ ] 多阶段构建 (builder → runtime)
  - [ ] 基于 python:3.11-slim
  - [ ] 安装依赖 → 复制代码 → 设置入口
  - [ ] 健康检查
  - [ ] 非 root 用户运行
- **验证步骤**:
  - [ ] `docker build -t harness .` 成功
  - [ ] `docker run harness --help` 输出帮助信息
  - [ ] 镜像大小 ≤ 500MB

### P5-02: GitHub Actions CI
- **依赖**: 所有 Phase
- **并行**: P5-01
- **复杂度**: S
- **涉及文件**: `.github/workflows/ci.yml`
- **内容**:
  - [ ] trigger: push, pull_request
  - [ ] jobs:
    - `unit-test`: `pip install -e .[dev] → pytest --cov`
    - `lint`: `ruff check`
    - `build`: `docker build` (如选容器分发)
  - [ ] 必须所有 job pass 才合入
- **验证步骤**:
  - [ ] 推送到 GitHub 后 CI 自动触发
  - [ ] 所有 job 显示绿色 pass 状态
  - [ ] `unit-test` job 名称必须包含该词

### P5-03: README & 文档完善
- **依赖**: P5-01, P5-02
- **并行**: —
- **复杂度**: S
- **涉及文件**: `README.md`
- **内容**:
  - [ ] 项目简介
  - [ ] 快速开始
  - [ ] CLI 使用指南
  - [ ] 配置说明
  - [ ] 架构说明
  - [ ] 凭据安全配置说明
  - [ ] 分发说明 (Docker / PyPI)
  - [ ] 开发指南
- **验证步骤**:
  - [ ] 按 README 从零开始安装运行一遍
  - [ ] 所有链接可访问

---

## 依赖关系图

```
Phase 1 (基础层)
├── P1-01 项目骨架 ──────────────────────────────────┐
├── P1-02 配置系统  ← P1-01                          │
├── P1-03 凭据存储  ← P1-01                          │
├── P1-04 LLM适配   ← P1-01                          │
└── P1-05 日志系统  ← P1-01                          │
                                                     │
Phase 2 (核心执行层)                                 │
├── P2-01 工具执行器 ← P1-01, P1-05                  │
├── P2-02 记忆管理   ← P1-01, P1-05                  │
└── P2-03 主循环     ← P2-01, P2-02, P1-02, P1-04 ──┘
                                                     │
Phase 3 (安全治理层)                                 │
├── P3-01 沙箱       ← P2-01                        │
└── P3-02 HITL       ← P2-03                        │
                                                     │
Phase 4 (评估任务层)                                 │
├── P4-01 评估器     ← P2-01                        │
├── P4-02 任务解析   ← P1-01, P1-02                 │
├── P4-03 CLI        ← P4-02, P1-03, P1-02          │
├── P4-04 API        ← P4-02, P1-03, P1-02          │
└── P4-05 OpenDesign ← P4-04                        │
                                                     │
Phase 5 (分发)                                       │
├── P5-01 Dockerfile ← 全部                          │
├── P5-02 CI         ← 全部                          │
└── P5-03 README     ← P5-01, P5-02                 │
```

## 并行执行策略

| 批次数 | 可并行任务 | 前置条件 | Worktree 建议 |
|--------|-----------|---------|--------------|
| Batch 1 | P1-02, P1-03, P1-04, P1-05 | P1-01 完成 | 每个任务一个 worktree |
| Batch 2 | P2-01, P2-02 | Batch 1 完成 | 2 个 worktree |
| Batch 3 | P2-03 (单线程) | Batch 2 完成 | 单独 worktree |
| Batch 4 | P3-01, P3-02 | Batch 3 完成 | 2 个 worktree |
| Batch 5 | P4-01, P4-02, P4-03, P4-04 | Batch 3 完成 | 4 个 worktree |
| Batch 6 | P4-05 (Open Design) | P4-04 完成 | 单独 worktree |
| Batch 7 | P5-01, P5-02 | Batch 6 完成 | 2 个 worktree |
| Batch 8 | P5-03 | Batch 7 完成 | 单独 worktree |

## 任务总数

- **Phase 1**: 5 个任务
- **Phase 2**: 3 个任务
- **Phase 3**: 2 个任务
- **Phase 4**: 5 个任务 (含 Open Design 集成)
- **Phase 5**: 3 个任务
- **合计**: 18 个任务

## 完成清单

完成所有任务后检查以下交付物:
- [ ] `SPEC.md` — 完整设计规约
- [ ] `PLAN.md` — 完整执行计划
- [ ] `SPEC_PROCESS.md` — 过程文档
- [ ] `AGENT_LOG.md` — 过程日志
- [ ] `README.md` — 项目文档
- [ ] `Dockerfile` — 容器分发
- [ ] `.github/workflows/ci.yml` — CI 配置
- [ ] 所有测试通过 (`pytest`)
- [ ] 最后一次 CI 执行为 pass 状态
- [ ] 仓库无真实凭据 (自查 .env, history, 配置)