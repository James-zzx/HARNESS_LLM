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
- **状态**: ✅ 已完成 (commit: 1dd3738)
- **依赖**: 无
- **并行**: —
- **复杂度**: S
- **涉及文件**: `pyproject.toml`, `src/harness/__init__.py`, `src/harness/__main__.py`, `src/tests/__init__.py`, `src/tests/conftest.py`
- **内容**:
  - [x] 创建 `pyproject.toml` (hatchling 构建, 依赖: click, fastapi, uvicorn, pyyaml, structlog, keyring, httpx)
  - [x] 创建 `src/harness/` 包结构，含 `__init__.py` 和 `__main__.py`
  - [x] 创建 `src/tests/` 包结构，含 `__init__.py` 和 `conftest.py` 基础 fixture
  - [x] 验证: `pip install -e .` 可安装，`python -m harness` 输出帮助信息
- **验证步骤**:
  - [x] `pip install -e .` 成功无报错
  - [x] `python -m harness --help` 输出非空帮助信息
  - [x] `pytest src/tests/` 无测试但至少运行不报错

### P1-02: 配置系统 (Config)
- **状态**: ✅ 已完成 (commit: bba58fd)
- **依赖**: P1-01
- **并行**: P1-03, P1-04, P1-05
- **复杂度**: M
- **涉及文件**: `src/harness/config.py`, `src/tests/test_config.py`, `examples/config.yaml`
- **内容**:
  - [x] 定义 `HarnessConfig` dataclass (所有可配置项)
  - [x] 实现 `load_config(path: str) -> HarnessConfig` 从 YAML/JSON 加载
  - [x] 实现配置合并: 默认值 → 文件配置 → 环境变量 → CLI 覆盖
  - [x] 实现配置校验 (schema validation)
  - [x] 示例配置文件 `examples/config.yaml`
- **TDD 先写测试**:
  - [x] `test_load_default_config`: 无文件时返回默认配置
  - [x] `test_load_yaml_config`: 加载 YAML 文件并验证字段
  - [x] `test_config_merge`: 环境变量覆盖文件配置
  - [x] `test_config_validation`: 无效配置抛出 `ConfigError`
- **验证步骤**:
  - [x] `pytest src/tests/test_config.py` 全部通过
  - [x] 手动运行 `harness config show` 输出默认配置

### P1-03: 凭据安全存储 (Credential Store)
- **状态**: ✅ 已完成 (commit: fb2a92d)
- **依赖**: P1-01
- **并行**: P1-02, P1-04, P1-05
- **复杂度**: M
- **涉及文件**: `src/harness/credential_store.py`, `src/tests/test_credential_store.py`
- **内容**:
  - [x] 实现 `CredentialStore` 类 (封装 keyring)
  - [x] `set_key(service, key, value)` — 存储
  - [x] `get_key(service, key) -> str` — 读取
  - [x] `delete_key(service, key)` — 删除
  - [x] `list_keys(service) -> list` — 列出 (不显示明文)
  - [x] 首次启动隐藏输入引导 (`getpass`)
  - [x] CLI 命令: `harness cred set/get/delete/list`
- **TDD 先写测试**:
  - [x] `test_set_and_get`: 存储后可通过相同 key 读取
  - [x] `test_delete`: 删除后 get 返回 None
  - [x] `test_list_hides_plaintext`: list 输出不包含明文值
  - [x] `test_key_not_found`: 不存在的 key 返回 None
- **验证步骤**:
  - [x] `pytest src/tests/test_credential_store.py` 全部通过
  - [x] 手动运行 `harness cred set test-service test-key` 隐藏输入正常
  - [x] `harness cred list test-service` 不显示明文

### P1-04: LLM Adapter + MockLLM
- **状态**: ✅ 已完成 (commit: 3169d24)
- **依赖**: P1-01
- **并行**: P1-02, P1-03, P1-05
- **复杂度**: M
- **涉及文件**: `src/harness/llm_adapter.py`, `src/harness/mock_llm.py`, `src/tests/test_llm_adapter.py`, `src/tests/test_mock_llm.py`, `src/tests/base.py`
- **内容**:
  - [x] 定义 `LLMClient` 抽象基类，`chat(messages: list[Message]) -> Response` 接口
  - [x] 定义 `Message` / `Response` dataclass
  - [x] 实现 `OpenAIClient` (真实 LLM 调用，httpx)
  - [x] 实现 `MockLLM(preset_responses: list[str])` (循环返回预设响应)
  - [x] 实现 `LLMFactory` 根据配置创建对应实例
  - [x] 实现 `BaseHarnessTest` 测试基座 (提供 mock_llm fixture)
- **TDD 先写测试**:
  - [x] `test_mock_llm_returns_preset`: MockLLM 返回预设响应列表
  - [x] `test_mock_llm_cycles`: 超出预设数量时循环回到第一个
  - [x] `test_llm_factory_creates_mock`: 配置 `llm.mock=true` 时创建 MockLLM
  - [x] `test_llm_factory_creates_openai`: 配置 `llm.mock=false` 时创建 OpenAIClient
- **验证步骤**:
  - [x] `pytest src/tests/test_llm_adapter.py src/tests/test_mock_llm.py` 全部通过
  - [x] MockLLM 确定性: 相同预设输入，100 次调用返回相同结果

### P1-05: 日志与追踪系统 (Logger)
- **状态**: ✅ 已完成 (commit: 55258ba)
- **依赖**: P1-01
- **并行**: P1-02, P1-03, P1-04
- **复杂度**: S
- **涉及文件**: `src/harness/logger.py`, `src/tests/test_logger.py`
- **内容**:
  - [x] 配置 structlog (控制台 + JSON 文件输出)
  - [x] 实现 `get_logger(name) -> Logger` 工厂
  - [x] 实现 `TraceContext` 上下文管理器 (trace_id 贯穿)
  - [x] 自动添加 trace_id, module, phase 到每条日志
  - [x] 日志级别: DEBUG / INFO / WARNING / ERROR
  - [x] 敏感字段自动脱敏 (key, secret, token, password)
- **TDD 先写测试**:
  - [x] `test_logger_creates_entry`: logger.info 输出包含预期字段
  - [x] `test_trace_context_adds_trace_id`: 上下文内日志包含 trace_id
  - [x] `test_trace_context_nesting`: 嵌套上下文 trace_id 不同
  - [x] `test_sensitive_field_redaction`: 日志中 key 字段被替换为 `***`
- **验证步骤**:
  - [x] `pytest src/tests/test_logger.py` 全部通过
  - [x] 手动检查 JSON 日志文件内容格式正确

---

## Phase 2: 核心执行层

> 依赖 Phase 1 完成。此层通过 MockLLM 可完全脱离 LLM 测试。

### P2-01: Action/Tool Executor
- **状态**: ✅ 已完成 (commit: b72b7fa)
- **依赖**: P1-01, P1-05
- **并行**: P2-02
- **复杂度**: M
- **涉及文件**: `src/harness/tool_executor.py`, `src/tests/test_tool_executor.py`
- **内容**:
  - [x] 定义 `Tool` 基类 (`name`, `description`, `execute(params) -> Result`)
  - [x] 实现内置工具:
    - [x] `read_file(path)` — 读取文件
    - [x] `write_file(path, content)` — 写入文件
    - [x] `edit_file(path, old_string, new_string)` — 编辑文件
    - [x] `run_shell(command)` — 执行 shell 命令
    - [x] `list_dir(path)` — 列出目录
  - [x] 实现 `ToolRegistry` (注册/查找工具)
  - [x] 实现 `ToolExecutor` (解析 LLM 意图 → 调用对应工具)
  - [x] 安全校验: 每个工具执行前检查 sandbox 权限
  - [x] 结果格式化: 统一返回 `ToolResult {success, output, error}`
- **TDD 先写测试**:
  - [x] `test_write_and_read_file`: 写入文件后读取内容一致
  - [x] `test_edit_file`: 替换字符串后文件内容正确
  - [x] `test_run_shell_echo`: 执行 echo 命令返回预期输出
  - [x] `test_run_shell_failure`: 执行不存在命令返回非零 exit_code
  - [x] `test_tool_registry_lookup`: 注册后可通过名称查找
  - [x] `test_tool_executor_parse_intent`: 解析 JSON 意图并调用正确工具
- **验证步骤**:
  - [x] `pytest src/tests/test_tool_executor.py` 全部通过
  - [x] 手动测试: 创建临时目录，执行 write → read → edit → list 序列

### P2-02: Context & Memory Manager
- **状态**: ✅ 已完成 (commit: 70be60e)
- **依赖**: P1-01, P1-05
- **并行**: P2-01
- **复杂度**: M
- **涉及文件**: `src/harness/memory.py`, `src/tests/test_memory.py`
- **内容**:
  - [x] 定义 `Message` dataclass (role, content, tool_calls, timestamp)
  - [x] 实现 `ConversationMemory` 类
  - [x] `add_message(msg)` — 添加消息
  - [x] `get_history() -> list[Message]` — 获取完整历史
  - [x] `get_context_window(max_tokens) -> list[Message]` — 按 token 裁剪
  - [x] `clear()` — 清空会话
  - [x] token 估算: 简单字符计数 (4 chars ≈ 1 token)
  - [x] 策略: 保留系统提示 + 最近 N 轮对话
- **TDD 先写测试**:
  - [x] `test_add_and_get_history`: 添加消息后历史包含该消息
  - [x] `test_context_window_truncation`: 超过 max_tokens 时裁剪
  - [x] `test_context_window_keeps_system_prompt`: 裁剪后系统提示保留
  - [x] `test_clear`: 清空后历史为空
- **验证步骤**:
  - [x] `pytest src/tests/test_memory.py` 全部通过
  - [x] 模拟 20 轮对话后验证裁剪行为

### P2-03: Main Loop / Orchestrator
- **状态**: ✅ 已完成 (commit: 320ed2d)
- **依赖**: P2-01, P2-02, P1-02, P1-04
- **并行**: —
- **复杂度**: XL
- **涉及文件**: `src/harness/orchestrator.py`, `src/tests/test_orchestrator.py`
- **内容**:
  - [x] 定义状态机状态: `INIT → TASK_LOADED → LLM_CALL → TOOL_EXEC → EVAL → HITL_CHECK → 循环/结束`
  - [x] 实现 `Orchestrator` 类
  - [x] `run(task_config)` — 主入口
  - [x] 状态转换: 每个状态有明确的进入/退出条件
  - [x] 与 LLM 交互: 调用 `LLMClient.chat()`
  - [x] 与 ToolExecutor 交互: 解析 LLM 响应 → 执行工具 → 结果回灌
  - [x] 与 Memory 交互: 每次 LLM 调用前注入上下文
  - [x] 与 Evaluator 交互: 任务完成后调用评估
  - [x] 与 HITL 交互: 遇到危险命令时暂停
  - [x] 错误处理: 超时、重试、崩溃恢复
- **TDD 先写测试**:
  - [x] `test_orchestrator_completes_task`: MockLLM 预设"写文件"路径 → 状态机到达 COMPLETED
  - [x] `test_orchestrator_max_iterations`: MockLLM 始终返回同一动作 → 达到 max_iterations 后 FAILED
  - [x] `test_orchestrator_tool_error`: 工具执行失败 → 错误回灌给 LLM → LLM 换方案
  - [x] `test_orchestrator_hitl_pause`: MockLLM 返回危险命令 → 状态机进入 PAUSED
  - [x] `test_orchestrator_full_cycle`: 写文件 → 评估失败 → 修正 → 评估通过 → COMPLETED
- **验证步骤**:
  - [x] `pytest src/tests/test_orchestrator.py` 全部通过
  - [x] 所有测试使用 MockLLM，不依赖网络

---

## Phase 3: 安全与治理层

> 依赖 Phase 2 完成。

### P3-01: Sandbox & Resource Limiting
- **状态**: ✅ 已完成 (commit: 64ee97d)
- **依赖**: P2-01
- **并行**: P3-02
- **复杂度**: L
- **涉及文件**: `src/harness/sandbox.py`, `src/tests/test_sandbox.py`
- **内容**:
  - [x] 定义 `Sandbox` 类
  - [x] 子进程管理: `Popen` 封装, 超时强制终止
  - [x] CPU 限制: 进程优先级, 最大运行时间
  - [x] 内存限制: 监控 RSS, 超限终止
  - [x] 文件系统限制: 白名单目录, 禁止访问系统目录
  - [x] 网络限制: 可选禁用/白名单
  - [x] 命令黑名单: 禁止 `rm -rf /`, `shutdown` 等
  - [x] 沙箱上下文管理器: `with Sandbox(config) as sb:`
  - [x] 集成到 ToolExecutor: 每个工具执行前检查沙箱权限
- **TDD 先写测试**:
  - [x] `test_sandbox_allows_whitelist_path`: 白名单内文件可读写
  - [x] `test_sandbox_blocks_blacklist_path`: 白名单外文件操作被拒绝
  - [x] `test_sandbox_blocks_dangerous_command`: `rm -rf /` 被拦截
  - [x] `test_sandbox_timeout`: 超时后进程被终止
  - [x] `test_sandbox_context_manager`: with 块退出后进程清理
- **验证步骤**:
  - [x] `pytest src/tests/test_sandbox.py` 全部通过
  - [x] 手动测试: 配置白名单后尝试写入系统目录应被拒绝

### P3-02: Governance & HITL State Machine
- **状态**: ✅ 已完成 (commit: ada1f7e)
- **依赖**: P2-03
- **并行**: P3-01
- **复杂度**: L
- **涉及文件**: `src/harness/hitl.py`, `src/tests/test_hitl.py`
- **内容**:
  - [x] 定义危险命令规则引擎:
    - [x] 静态规则: `rm -rf`, `git push --force`, `DROP TABLE`, `format C:` 等
    - [x] 正则匹配: 可配置规则列表
  - [x] 实现 `HITLStateMachine`:
    - `RUNNING` → `PAUSED` (危险命令触发)
    - `PAUSED` → `APPROVED` / `REJECTED` / `TIMEOUT`
  - [x] HITL 接口:
    - CLI: 阻塞等待用户输入 `y/n/t`
    - WebUI: 轮询状态 → 按钮点击 (通过 P4-05)
    - 超时: 默认 300s 自动拒绝
  - [x] 回灌机制: 拒绝时构造错误消息 → 要求 LLM 换方案
  - [x] 集成到 Orchestrator: 工具执行前调用 HITL 检查
- **TDD 先写测试**:
  - [x] `test_guardrail_detects_dangerous_command`: `rm -rf /` 被识别为危险
  - [x] `test_guardrail_allows_safe_command`: `ls -la` 通过检查
  - [x] `test_hitl_state_transitions`: PAUSED → APPROVED → RUNNING
  - [x] `test_hitl_timeout`: 超时后自动 REJECTED
  - [x] `test_hitl_rejection_feedback`: 拒绝后反馈消息包含原危险命令信息
  - [x] `test_guardrail_regex_pattern`: 自定义正则规则匹配
- **验证步骤**:
  - [x] `pytest src/tests/test_hitl.py` 全部通过
  - [x] 所有测试不依赖真实 LLM — 直接传入 Action 对象

---

## Phase 4: 评估与任务层

> 依赖 Phase 2 完成。

### P4-01: Result Evaluator
- **状态**: ✅ 已完成 (commit: 334e4ce)
- **依赖**: P2-01
- **并行**: P4-02
- **复杂度**: M
- **涉及文件**: `src/harness/evaluator.py`, `src/tests/test_evaluator.py`
- **内容**:
  - [x] 定义 `EvaluationResult` dataclass: `{passed, output, error, exit_code}`
  - [x] 实现 `Evaluator` 类
  - [x] 默认评估器: 运行 `make test` 或自定义命令
  - [x] 输出解析: 抓取 stdout/stderr, 提取红/绿状态
  - [x] 可扩展: 支持自定义评估脚本
  - [x] 结果回灌: 将评估结果格式化为结构化数据 → 喂给主循环
- **TDD 先写测试**:
  - [x] `test_evaluator_passed`: mock subprocess 返回 exit_code=0 → passed=True
  - [x] `test_evaluator_failed`: mock subprocess 返回 exit_code=1 → passed=False
  - [x] `test_evaluator_captures_output`: mock subprocess 输出被正确捕获
  - [x] `test_evaluator_custom_command`: 自定义 eval_command 被正确执行
- **验证步骤**:
  - [x] `pytest src/tests/test_evaluator.py` 全部通过
  - [x] 手动测试: 在含 `make test` 的目录中运行 evaluator 验证

### P4-02: Task Definition & Parser
- **状态**: ✅ 已完成 (commit: 1d21f1f)
- **依赖**: P1-01, P1-02
- **并行**: P4-01
- **复杂度**: M
- **涉及文件**: `src/harness/task.py`, `src/tests/test_task.py`, `examples/task.yaml`
- **内容**:
  - [x] 定义 `Task` dataclass: `{id, prompt, eval_command, max_iterations, timeout}`
  - [x] 实现 `TaskParser`:
    - `load_yaml(path) -> Task`
    - `load_json(path) -> Task`
    - `from_dict(dict) -> Task`
  - [x] 任务校验: 必要字段, 类型检查
  - [x] 示例任务: `examples/task.yaml`
- **TDD 先写测试**:
  - [x] `test_parse_yaml_task`: 解析 YAML 文件返回 Task 对象
  - [x] `test_parse_json_task`: 解析 JSON 文件返回 Task 对象
  - [x] `test_task_validation_missing_field`: 缺少必要字段抛出 `TaskError`
  - [x] `test_task_validation_type_error`: 字段类型错误抛出 `TaskError`
- **验证步骤**:
  - [x] `pytest src/tests/test_task.py` 全部通过
  - [x] 手动测试: `harness run examples/task.yaml` 解析正确

### P4-03: CLI Entry Point
- **状态**: ✅ 已完成 (commit: c4ae1e9)
- **依赖**: P4-02, P1-03, P1-02
- **并行**: P4-04, P4-05
- **复杂度**: M
- **涉及文件**: `src/harness/cli.py`, `src/harness/main.py`, `src/tests/test_cli.py`
- **内容**:
  - [x] CLI 命令树:
    - `harness run <task.yaml>` — 执行任务
    - `harness cred set/get/delete/list` — 凭据管理
    - `harness config show` — 查看当前配置
    - `harness init` — 初始化项目 (生成默认配置)
  - [x] 参数解析: 支持 `--config`, `--verbose`, `--timeout` 等
  - [x] 错误处理: 友好的错误提示
- **TDD 先写测试**:
  - [x] `test_cli_run`: 执行 `harness run examples/task.yaml` 返回 0
  - [x] `test_cli_config_show`: 执行 `harness config show` 输出配置
  - [x] `test_cli_cred_set`: 执行 `harness cred set` 提示输入
  - [x] `test_cli_missing_file`: 不存在的 task.yaml 返回非 0
- **验证步骤**:
  - [x] `pytest src/tests/test_cli.py` 全部通过
  - [x] 手动运行所有 CLI 命令验证交互

### P4-04: REST API
- **状态**: ✅ 已完成 (commit: d640b08)
- **依赖**: P4-02, P1-03, P1-02
- **并行**: P4-03, P4-05
- **复杂度**: M
- **涉及文件**: `src/harness/api.py`, `src/tests/test_api.py`
- **内容**:
  - [x] FastAPI 应用
  - [x] 端点:
    - `POST /api/tasks` — 提交任务
    - `GET /api/tasks/{id}` — 查询任务状态
    - `GET /api/tasks/{id}/logs` — 获取任务日志
    - `POST /api/hitl/{task_id}/approve` — 批准
    - `POST /api/hitl/{task_id}/reject` — 拒绝
  - [x] 后台任务执行 (BackgroundTasks)
  - [x] 错误处理: 统一异常处理器
- **TDD 先写测试**:
  - [x] `test_api_create_task`: POST /api/tasks 返回 201 + task_id
  - [x] `test_api_get_task_status`: GET /api/tasks/{id} 返回状态
  - [x] `test_api_hitl_approve`: POST /api/hitl/{id}/approve 返回 200
  - [x] `test_api_task_not_found`: 不存在的 task_id 返回 404
- **验证步骤**:
  - [x] `pytest src/tests/test_api.py` 全部通过
  - [x] 手动启动 `harness serve` 后用 curl 测试各端点

### P4-05: Open Design Integration (WebUI/Design Layer)
- **状态**: ✅ 已完成 (commit: 243acdb)
- **依赖**: P4-04
- **并行**: P4-03, P4-04
- **复杂度**: L
- **涉及文件**: `src/harness/open_design.py`, `src/tests/test_open_design.py`
- **内容**:
  - [x] 实现 `OpenDesignClient` 类:
    - `start_daemon()` — 启动 `od` 子进程（`--headless --no-open`）
    - `stop_daemon()` — 优雅停止 daemon
    - `health_check() -> bool` — 健康检查 (`GET /api/health`)
    - `list_projects() -> list` — 列出项目 (`GET /api/projects`)
    - `create_artifact(project_id, type, content)` — 创建 artifact
  - [x] Daemon 生命周期管理:
    - 自动检测 `od` 是否在 PATH 中
    - 通过 `OD_DATA_DIR` 环境变量隔离数据目录
    - 启动/停止/重启/健康监控
    - 日志重定向到 Harness 的日志系统
  - [x] HITL WebUI 桥接:
    - 通过 Open Design 插件显示 HITL 暂停事件
    - 将批准/拒绝结果回灌给 Orchestrator
  - [x] 任务状态推送:
    - 通过 WebSocket 或轮询将 Harness 任务状态推送到 Open Design WebUI
  - [x] 配置:
    - `config.yaml` 中增加 `open_design.enabled`, `open_design.port`, `open_design.data_dir`
- **TDD 先写测试**:
  - [x] `test_od_client_health_check`: mock HTTP 200 → health_check() 返回 True
  - [x] `test_od_client_health_failure`: mock HTTP 500 → health_check() 返回 False
  - [x] `test_od_daemon_start_stop`: mock subprocess → start/stop 调用正确
  - [x] `test_od_daemon_not_found`: `od` 不在 PATH → 抛出 `ODNotFoundError`
  - [x] `test_od_create_artifact`: mock POST /api/projects/{id}/artifacts → 返回 artifact_id
- **验证步骤**:
  - [x] `pytest src/tests/test_open_design.py` 全部通过
  - [x] 无需真实安装 Open Design — 所有测试 mock 外部依赖

---

## Phase 5: 分发与 CI/CD

> 依赖所有 Phase 完成。

### P5-01: Dockerfile
- **状态**: ✅ 已完成 (commit: f7aa3d9)
- **依赖**: 所有 Phase
- **并行**: P5-02
- **复杂度**: S
- **涉及文件**: `Dockerfile`, `.dockerignore`
- **内容**:
  - [x] 多阶段构建 (builder → runtime)
  - [x] 基于 python:3.11-slim
  - [x] 安装依赖 → 复制代码 → 设置入口
  - [x] 健康检查
  - [x] 非 root 用户运行
- **验证步骤**:
  - [x] `docker build -t harness .` 成功
  - [x] `docker run harness --help` 输出帮助信息
  - [x] 镜像大小 ≤ 500MB

### P5-02: GitHub Actions CI
- **状态**: ✅ 已完成 (commit: e314545)
- **依赖**: 所有 Phase
- **并行**: P5-01
- **复杂度**: S
- **涉及文件**: `.github/workflows/ci.yml`
- **内容**:
  - [x] trigger: push, pull_request
  - [x] jobs:
    - `unit-test`: `pip install -e .[dev] → pytest --cov`
    - `lint`: `ruff check`
    - `build`: `docker build` (如选容器分发)
  - [x] 必须所有 job pass 才合入
- **验证步骤**:
  - [x] 推送到 GitHub 后 CI 自动触发
  - [x] 所有 job 显示绿色 pass 状态
  - [x] `unit-test` job 名称必须包含该词

### P5-03: README & 文档完善
- **状态**: ✅ 已完成 (commit: 081b442)
- **依赖**: P5-01, P5-02
- **并行**: —
- **复杂度**: S
- **涉及文件**: `README.md`
- **内容**:
  - [x] 项目简介
  - [x] 快速开始
  - [x] CLI 使用指南
  - [x] 配置说明
  - [x] 架构说明
  - [x] 凭据安全配置说明
  - [x] 分发说明 (Docker / PyPI)
  - [x] 开发指南
- **验证步骤**:
  - [x] 按 README 从零开始安装运行一遍
  - [x] 所有链接可访问

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
- **Phase 6**: 10 个任务 (Dashboard + 运行时对话 + API-Key 配置 + LLM 双模式 + 对话答复显示 + LLM 开关生效)
- **合计**: 28 个任务

## Phase 6: WebUI Dashboard 与运行时对话

> 依赖 Phase 1-5 完成。此层通过 MockLLM + TestClient 可完全脱离 LLM 与外部插件测试。硬性约束：**dashboard 开箱即用，零外部依赖（不依赖 Open Design、无 CDN/外部资源）**。

### P6-01: MessageQueue（运行时对话队列）
- **状态**: ✅ 已完成 (commit: 41e685b)
- **依赖**: P2-03, P4-04
- **并行**: —
- **复杂度**: S
- **涉及文件**: `src/harness/message_queue.py`, `src/tests/test_message_queue.py`
- **内容**:
  - [x] 定义 `MessageQueue` 类（task_id, pending 列表, threading.Lock, threading.Event）
  - [x] `push(message: dict) -> None` — 追加用户消息并唤醒等待（线程安全）
  - [x] `pop_all() -> list[dict]` — 消费并清空待处理消息
  - [x] `has_pending() -> bool` — 是否有未消费消息
  - [x] `wait_for_message(timeout: float) -> list[dict]` — 事件等待，超时返回空列表
  - [x] `reset() -> None` — 清空（任务开始/结束时调用）
- **TDD 先写测试**:
  - [x] `test_push_and_pop_all`: push 后 pop_all 返回该消息并清空
  - [x] `test_has_pending`: push 后 True，pop 后 False
  - [x] `test_wait_returns_on_push`: 另一线程 push 后 wait 返回（事件唤醒）
  - [x] `test_wait_timeout_returns_empty`: 超时后返回空列表不阻塞
  - [x] `test_concurrent_push_pop`: 多线程 push/pop 无数据丢失或崩溃
- **验证步骤**:
  - [x] `pytest src/tests/test_message_queue.py` 全部通过
  - [x] 全量 `pytest src/tests/` 无回归

### P6-02: Orchestrator USER_INPUT 状态
- **状态**: ✅ 已完成 (commit: daf4fbf)
- **依赖**: P6-01, P2-03
- **并行**: —
- **复杂度**: L
- **涉及文件**: `src/harness/orchestrator.py`, `src/harness/message_queue.py`, `src/tests/test_orchestrator.py`
- **内容**:
  - [x] 新增状态常量 `USER_INPUT = "USER_INPUT"`
  - [x] `Orchestrator.__init__` 增加可选参数 `message_queue: Optional[MessageQueue] = None`
  - [x] 在 `_run_loop` 每轮 LLM 调用前：若 `message_queue` 存在且有 `has_pending()`，则进入 `USER_INPUT` 状态，`wait_for_message(timeout=task.timeout 剩余)`；收到消息后作为 `role="user"` 加入记忆，继续循环
  - [x] 若 `message_queue` 为 None（未启用对话），行为与现状完全一致（向后兼容）
  - [x] `interrupt()` 方法: 设置 `_interrupt_requested` 标志，下一轮循环检查并进入 USER_INPUT
- **TDD 先写测试**:
  - [x] `test_orchestrator_user_input`: MockLLM 预设"先写文件再 done"；测试在第二轮前 push 用户消息"改成另一种写法"，断言后续意图变化且用户消息进入记忆（离线确定性）
  - [x] `test_orchestrator_user_input_timeout`: push 后不回复，短 timeout 后自动继续到 COMPLETED
  - [x] `test_orchestrator_no_queue_backward_compat`: 不传 message_queue 时行为与现状一致（现有测试全绿）
  - [x] `test_orchestrator_interrupt`: 运行中调用 interrupt()，下一轮进入 USER_INPUT 并等待
- **验证步骤**:
  - [x] `pytest src/tests/test_orchestrator.py` 全部通过
  - [x] 全量 `pytest src/tests/` 无回归

### P6-03: REST API 对话端点
- **状态**: ✅ 已完成 (commit: f9aec63)
- **依赖**: P6-02, P4-04
- **并行**: —
- **复杂度**: M
- **涉及文件**: `src/harness/api.py`, `src/tests/test_api.py`
- **内容**:
  - [x] `TaskRecord` 增加 `message_queue: Optional[MessageQueue]` 字段
  - [x] `TaskManager.create` 为每个任务创建 `MessageQueue`
  - [x] 新增端点:
    - `POST /api/tasks/{task_id}/message` — body `{content: str}` → `message_queue.push({"role":"user","content":...})` → 200
    - `GET /api/tasks/{task_id}/messages` — 返回对话历史（从 memory 或记录）
    - `POST /api/tasks/{task_id}/interrupt` — 触发 orchestrator.interrupt() → 200
  - [x] 错误处理: 任务不存在 → 404；空 content → 400
- **TDD 先写测试**:
  - [x] `test_api_send_message`: POST message → 200，message_queue 收到
  - [x] `test_api_get_messages`: GET messages → 200 返回历史
  - [x] `test_api_interrupt`: POST interrupt → 200
  - [x] `test_api_message_not_found`: 不存在 task → 404
  - [x] `test_api_message_empty_content`: 空 content → 400
- **验证步骤**:
  - [x] `pytest src/tests/test_api.py` 全部通过
  - [x] 全量 `pytest src/tests/` 无回归

### P6-04: WebUI Dashboard 静态前端
- **状态**: ✅ 已完成 (commit: 60ed6bb)
- **依赖**: P4-04, P6-03
- **并行**: —
- **复杂度**: L
- **涉及文件**: `src/harness/webui/index.html`, `src/harness/webui/app.js`, `src/harness/webui/style.css`, `src/tests/test_dashboard.py`
- **内容**:
  - [x] `webui/index.html` — 单页应用结构：顶栏（标题 + 新任务按钮 + 连接状态灯）、任务列表、任务详情（元数据 + 日志区 + HITL 按钮 + 对话区）、新任务弹窗（表单 + YAML 切换）
  - [x] `webui/style.css` — 采用 minimal 设计系统风格（色板/字体/排版内嵌，无外部引用），状态徽章配色（PENDING 灰/RUNNING 蓝/PAUSED 琥珀/COMPLETED 绿/FAILED 红）
  - [x] `webui/app.js` — 交互逻辑:
    - 每 2s 轮询 `GET /api/tasks`（若有列表端点）或逐任务 `GET /api/tasks/{id}` + `GET /api/tasks/{id}/logs`
    - 新任务表单: `POST /api/tasks`
    - HITL: 状态 PAUSED 时显示 [批准]/[拒绝]，调 `POST /api/hitl/{id}/approve|reject`
    - 对话区: 输入框 + [发送] 按钮 → `POST /api/tasks/{id}/message`; [上传文件] 按钮 → FileReader 读内容填入消息框（可编辑后发送）; 消息框始终可打字
    - 连接状态灯: API 不可达时红灯 + 提示
    - 日志区自动滚到底部（用户上滚时暂停自动滚动）
  - [x] **零外部依赖**: 无 CDN、无外部字体/脚本，全部内联
- **TDD 先写测试**:
  - [x] `test_dashboard_index_served`: `GET /` 或 `/dashboard` 返回 200 + HTML 含关键元素（id 锚点）
  - [x] `test_dashboard_static_assets`: `GET /static/webui/app.js` / `style.css` 返回 200
  - [x] `test_dashboard_no_external_refs`: index.html 不含 `http://`/`https://` 外部资源引用（零外部依赖验证）
  - [x] `test_dashboard_integration`: TestClient 下页面加载 + API 端点（提交任务→轮询→HITL）可交互
- **验证步骤**:
  - [x] `pytest src/tests/test_dashboard.py` 全部通过
  - [x] 全量 `pytest src/tests/` 无回归

### P6-05: `harness dashboard` CLI 命令与配置
- **状态**: ✅ 已完成 (commit: ce14561)
- **依赖**: P6-04, P1-02
- **并行**: —
- **复杂度**: M
- **涉及文件**: `src/harness/main.py`, `src/harness/dashboard.py`, `src/harness/config.py`, `src/tests/test_cli.py`, `src/tests/test_config.py`
- **内容**:
  - [x] config.py 新增 `WebUIConfig` dataclass（`host: str = "127.0.0.1"`, `port: int = 8000`），注册到 `_SECTION_CLASSES` / `_SECTION_FIELDS`，`HarnessConfig` 增加 `webui: WebUIConfig`
  - [x] `src/harness/dashboard.py` 实现 `run_dashboard(config) -> None`: 加载 `create_app()`，挂载 `StaticFiles` 提供 `webui/`，`uvicorn.run(host, port)`，打印 URL，Ctrl+C 优雅停止
  - [x] main.py 新增 `harness dashboard [--host] [--port] [--config]` 命令（参数覆盖 config.webui）
  - [x] `create_app` 增加挂载静态目录（路径由包定位 `webui/`）
- **TDD 先写测试**:
  - [x] `test_config_webui_section`: 默认 host/port 正确；YAML 可覆盖
  - [x] `test_cli_dashboard_help`: `harness dashboard --help` 退出 0 且含 host/port 参数
  - [x] `test_dashboard_uvicorn_invoked`: mock uvicorn.run，断言 host/port 从 config 传入
  - [x] `test_api_mounts_static`: TestClient 下 `/static/webui/index.html` 可访问
- **验证步骤**:
  - [x] `pytest src/tests/test_cli.py src/tests/test_config.py src/tests/test_dashboard.py` 全部通过
  - [x] 手动 `python -m harness dashboard` 启动后浏览器访问 URL

### P6-06: README 与文档收尾
- **状态**: ✅ 已完成 (commit: 7a16d6e)
- **依赖**: P6-05
- **并行**: —
- **复杂度**: S
- **涉及文件**: `README.md`, `AGENT_LOG.md`, `PLAN.md`（本文件状态）
- **内容**:
  - [x] README 新增"图形化界面（Dashboard）"章节: `harness dashboard` 启动命令、功能列表（任务/HITL/对话/文件上传）、零外部依赖说明、Open Design 可选关系
  - [x] README API 端点表补充 message/messages/interrupt
  - [x] AGENT_LOG.md 记录 Phase 6 执行
  - [x] PLAN.md 勾选本 Phase 任务并附 commit hash
- **验证步骤**:
  - [x] 按 README 从零安装并 `harness dashboard` 运行一遍
  - [x] 全量 `pytest src/tests/` 通过


### P6-07: Dashboard 顶栏 API-Key 配置弹窗
- **依赖**: P6-05, P4-04
- **并行**: —
- **复杂度**: M
- **涉及文件**: src/harness/api.py, src/harness/webui/index.html, src/harness/webui/app.js, src/harness/webui/style.css, src/tests/test_api.py, src/tests/test_dashboard.py
- **内容**:
  - [ ] api.py 新增凭据端点:
    - GET /api/credential/{service}/{key} — 返回 {configured: bool}（**不返回明文**）
    - PUT /api/credential/{service}/{key} — body {value}，非空校验，写入 CredentialStore
    - DELETE /api/credential/{service}/{key} — 清除
    - 后端从 config.credential.backend 选择（keyring/env），与 uild_llm 一致
  - [ ] webui/index.html: 顶栏新增 [API Key] 按钮 + API-Key 配置弹窗（service/key 默认 harness/openai、key 值隐藏输入、状态区、保存/清除按钮）
  - [ ] webui/app.js: 弹窗交互 — 打开时 GET 查询状态、保存 PUT、清除 DELETE、结果提示
  - [ ] webui/style.css: 弹窗与按钮样式（复用现有 modal 风格）
  - [ ] 安全: key 值永不在前端/API 响应回显，仅返回 configured
- **TDD 先写测试**:
  - [ ] 	est_api_credential_put: PUT 保存后 GET 返回 configured=true
  - [ ] 	est_api_credential_get_no_leak: GET 响应不含明文 key 值
  - [ ] 	est_api_credential_delete: DELETE 后 GET 返回 configured=false
  - [ ] 	est_api_credential_empty_rejected: PUT 空 value → 400
  - [ ] 	est_dashboard_api_key_button: 页面含 API Key 按钮 + 弹窗元素
- **验证步骤**:
  - [ ] pytest src/tests/test_api.py src/tests/test_dashboard.py 全部通过
  - [ ] 全量 pytest src/tests/ 无回归
  - [ ] 手动: dashboard 弹窗设置/查看/清除 key


### P6-08: LLM 双模式（默认 Mock 离线 + 真实 LLM 切换）
- **依赖**: P6-05, P6-07, P1-04
- **并行**: —
- **复杂度**: M
- **涉及文件**: `src/harness/config.py`, `src/harness/mock_llm.py`, `src/harness/webui/index.html`, `src/harness/webui/app.js`, `src/harness/webui/style.css`, `src/harness/main.py`(init 注释), `examples/config.yaml`, `src/tests/test_config.py`, `src/tests/test_mock_llm.py`, `src/tests/test_dashboard.py`, `src/tests/test_cli.py`, `README.md`, `SPEC.md`
- **内容**:
  - [ ] config.py: `LLMConfig.mock` 默认值 `False -> True`（未配置真实 LLM 时离线运行）
  - [ ] mock_llm.py: 未提供 preset 时返回默认演示循环（写 mock-output.txt → done），任务可完整跑完
  - [ ] webui/index.html: 顶栏新增 LLM 模式开关（离线 Mock / 真实 LLM）
  - [ ] webui/app.js: 模式选择持久化（localStorage）；选“真实 LLM”时提示配置 llm.mock:false + credential_ref + base_url（复用 API-Key 弹窗）；任务提交带上模式
  - [ ] webui/style.css: 模式开关样式
  - [ ] main.py init 注释、examples/config.yaml: mock 默认 true 说明
  - [ ] README: 双模式说明
- **TDD 先写测试**:
  - [ ] `test_config_mock_default_true`: 默认配置 `llm.mock is True`
  - [ ] `test_mock_llm_default_demo_cycle`: MockLLM() 无 preset 时返回写文件→done 序列，chat 两次内容不同且含 tool 动作
  - [ ] `test_dashboard_llm_mode_toggle`: 页面含模式开关元素
  - [ ] `test_cli_init_mock_true`: init 生成 harness.yaml 含 `mock: true`
  - [ ] 现有测试更新: test_config.py:9 (`mock is False` -> `True`), test_cli.py:24 (`mock: false` -> `mock: true`)
- **验证步骤**:
  - [ ] `pytest src/tests/test_config.py src/tests/test_mock_llm.py src/tests/test_dashboard.py src/tests/test_cli.py` 全部通过
  - [ ] 全量 `pytest src/tests/` 无回归
  - [ ] 手动: dashboard 默认离线提交任务成功（MockLLM 演示循环）；切真实模式提示配置


### P6-09: 对话区显示 agent 答复（隐私限制）
- **依赖**: P6-03, P6-02
- **并行**: —
- **复杂度**: M
- **涉及文件**: `src/harness/orchestrator.py`, `src/harness/api.py`, `src/tests/test_orchestrator.py`, `src/tests/test_api.py`, `src/tests/test_dashboard.py`, `src/harness/webui/app.js`(确认), `SPEC.md`, `README.md`
- **内容**:
  - [ ] orchestrator: 新增可选 `conversation_sink: Optional[Callable[[dict], None]]` 参数；运行时把**自然语言答复**（`_parse_intent` 返回 None 的非空响应）记录为 `{"role":"assistant","content":...}` 推给 sink；**工具调用 JSON 意图不记录**
  - [ ] api: `_run_task` 的 `on_orchestrator` 给 orchestrator 注入 `conversation_sink=manager.append_message`；`get_messages` 现返回 user + assistant
  - [ ] **隐私（§3.1）**: messages 绝不包含工具参数/结果/命令/文件内容；敏感字段（key/secret/token/password）在记录前脱敏兜底；GET 响应不回显凭据明文
  - [ ] 前端: `renderConversation` 已支持双角色，确认只渲染 user/assistant（无 tool 消息）
- **TDD 先写测试**:
  - [ ] `test_orchestrator_records_natural_reply`: MockLLM 返回自然语言 → conversation_sink 收到 assistant 消息
  - [ ] `test_orchestrator_skips_tool_intent`: MockLLM 返回工具 JSON → sink 不收到（工具不记录）
  - [ ] `test_api_messages_include_assistant`: GET messages 含 assistant
  - [ ] `test_api_messages_no_tool_content`: messages 不含工具参数/命令（隐私）
  - [ ] `test_api_messages_redacts_secrets`: messages 中 key/token 字段被脱敏（§3.1）
- **验证步骤**:
  - [ ] `pytest src/tests/test_orchestrator.py src/tests/test_api.py src/tests/test_dashboard.py` 全部通过
  - [ ] 全量 `pytest src/tests/` 无回归
  - [ ] 手动: 任务运行中提问，对话区显示 user + agent 答复


### P6-10: UI LLM 模式开关真正切换 llm.mock（运行时动态覆盖）
- **依赖**: P6-08, P6-07
- **并行**: —
- **复杂度**: M
- **涉及文件**: `src/harness/task.py`, `src/harness/api.py`, `src/harness/webui/app.js`(确认), `src/tests/test_task.py`, `src/tests/test_api.py`, `SPEC.md`, `README.md`
- **内容**:
  - [ ] task.py: `Task` dataclass 增加 `llm_mode: Optional[str] = None`；`from_dict` 解析 `llm_mode`（"mock"/"real"，可选）
  - [ ] api.py: `_run_task` 读取任务 `llm_mode`，构建覆盖后的 config（`dataclasses.replace(config, llm=replace(config.llm, mock=...))`），传给 `build_llm`；缺 key 时真实模式返回明确提示（复用现有错误处理）
  - [ ] 前端: `task.llm_mode` 已随提交发送（P6-08），确认后端解析生效；开关 title/提示更新为"任务运行时生效"
  - [ ] 隐私: 不改动（§3.1）
- **TDD 先写测试**:
  - [ ] `test_task_llm_mode_field`: from_dict 解析 llm_mode（默认 None / "mock" / "real"）
  - [ ] `test_api_task_llm_mode_real_uses_real_llm`: 提交 llm_mode=real 任务 → _run_task 用 mock=false 构建 build_llm（注入 stub 验证）
  - [ ] `test_api_task_llm_mode_mock_uses_mock`: 提交 llm_mode=mock → build_llm 用 mock=true
  - [ ] `test_api_task_default_mock`: 无 llm_mode → 默认 mock（服务端 config）
- **验证步骤**:
  - [ ] `pytest src/tests/test_task.py src/tests/test_api.py` 全部通过
  - [ ] 全量 `pytest src/tests/` 无回归
  - [ ] 手动: dashboard 切"真实 LLM"提交任务 → 实际调用真实端点（本地 mock 验证）；切"离线" → 走 mock


## 完成清单

完成所有任务后检查以下交付物:
- [x] `SPEC.md` — 完整设计规约
- [x] `PLAN.md` — 完整执行计划
- [x] `SPEC_PROCESS.md` — 过程文档
- [x] `AGENT_LOG.md` — 过程日志
- [x] `README.md` — 项目文档
- [x] `Dockerfile` — 容器分发
- [x] `.github/workflows/ci.yml` — CI 配置
- [x] 所有测试通过 (`pytest`)
- [x] 最后一次 CI 执行为 pass 状态
- [x] 仓库无真实凭据 (自查 .env, history, 配置)