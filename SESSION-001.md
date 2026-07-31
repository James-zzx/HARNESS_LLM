# AI Agent Harness — 会话历史记录

## 会话信息

- **会话编号**: SESSION-001
- **日期**: 2026-07-26
- **项目**: AI Agent Harness (Coding Agent Harness — A 类项目)
- **目标**: 安全、自主、可分发地运行编码型 AI Agent 的 Harness
- **当前阶段**: Brainstorming + Writing-Plans 完成，准备进入 Using-Git-Worktrees

---

## 一、项目设计决策记录

### 1.1 核心设计

| 维度 | 决策 |
|------|------|
| 技术栈 | Python 3.11+ |
| 沙箱方案 | subprocess + 权限限制（非 Docker） |
| 任务定义 | YAML/JSON 本地文件 |
| 接口 | CLI + REST API + Open Design WebUI |
| 测试框架 | pytest + MockLLM |
| 凭据存储 | OS 钥匙串（keyring 库） |
| 分发 | Docker 容器（首选）+ PyPI（备选） |
| 设计/UI 引擎 | Open Design (https://github.com/nexu-io/open-design) |

### 1.2 模块清单（共 13 个）

| # | 模块 | 功能 | 关键文件 |
|---|------|------|---------|
| 1 | Task Definition & Execution | YAML/JSON 任务定义，CLI/API/WebUI 三种接口 | `cli.py`, `api.py`, `task.py` |
| 2 | Sandbox & Resource Limiting | subprocess 沙箱，文件/网络/资源限制 | `sandbox.py` |
| 3 | Logging & Tracing | 结构化日志，trace_id 贯穿 | `logger.py` |
| 4 | Result Evaluation & Scoring | 执行 `make test`，抓取红/绿状态回灌 | `evaluator.py` |
| 5 | Action/Tool Executor | LLM 意图 → 确定性系统调用 | `tool_executor.py` |
| 6 | Main Loop / Orchestrator | 状态机驱动的主循环 | `orchestrator.py` |
| 7 | Governance & HITL State Machine | 危险命令拦截、HITL 审批/拒绝/超时 | `hitl.py` |
| 8 | Context & Memory Management | 会话内记忆，按 token 裁剪 | `memory.py` |
| 9 | Declarative Configuration | YAML/JSON 配置系统，禁止硬编码 Key | `config.py` |
| 10 | Credential Secure Storage | OS 钥匙串存取 API Key | `credential_store.py` |
| 11 | Distribution & CI/CD | Dockerfile + GitHub Actions CI | `Dockerfile`, `ci.yml` |
| 12 | Mock-LLM & Test Base | LLM Adapter + MockLLM + 测试基座 | `llm_adapter.py`, `mock_llm.py`, `base.py` |
| 13 | Open Design Integration | WebUI/设计层，daemon 管理 + HTTP 客户端 | `open_design.py` |

### 1.3 重点维度：治理护栏（Governance）

选择治理作为深入实现的维度，因为：
- 天然由代码构成，符合"移除 LLM 后仍可用单测验证"的硬性要求
- 多层护栏架构：沙箱层 → 规则引擎层 → HITL 状态机层
- 每个测试用例结果确定，可精确测试所有边界条件

### 1.4 用户故事（7 个）

| ID | 标题 | 角色 | 故事 |
|----|------|------|------|
| US-1 | 运行编码任务 | 开发者 | 通过 YAML 文件定义任务，`harness run` 自动驱动 agent 完成 |
| US-2 | 拦截危险命令 | 开发者 | `rm -rf /` 等危险命令被拦截，等待 HITL 审批 |
| US-3 | 验证代码质量 | 开发者 | 修改代码后自动 `make test`，失败则修正 |
| US-4 | 安全配置 API Key | 开发者 | 隐藏输入录入，list 不显示明文 |
| US-5 | WebUI 监控任务 | 开发者 | 浏览器查看任务状态、日志、HITL 审批 |
| US-6 | 脱离 LLM 测试 | 测试者 | MockLLM 替换真实 LLM，不依赖网络运行测试 |
| US-7 | 并行运行任务 | 开发者 | 多个任务并行执行，独立沙箱和日志 |

### 1.5 数据模型关键实体

- `Task`: id, prompt, eval_command, max_iterations, timeout, status
- `Message`: role, content, tool_calls, timestamp
- `ToolCall`: id, tool_name, parameters
- `ToolResult`: success, output, error, exit_code
- `EvaluationResult`: passed, output, error, exit_code
- `HarnessConfig`: llm, sandbox, hitl, logging, open_design, credential

---

## 二、实现计划摘要

### 2.1 Phase 划分

| Phase | 内容 | 任务数 |
|-------|------|--------|
| Phase 1 | 基础设施（配置/凭据/LLM适配/日志） | 5 个 |
| Phase 2 | 核心执行（工具/记忆/主循环） | 3 个 |
| Phase 3 | 安全治理（沙箱/HITL） | 2 个 |
| Phase 4 | 评估与任务（评估器/CLI/API/Open Design） | 5 个 |
| Phase 5 | 分发（Docker/CI/README） | 3 个 |

### 2.2 并行执行策略

| Batch | 可并行任务 | 前置条件 |
|-------|-----------|---------|
| Batch 1 | P1-02, P1-03, P1-04, P1-05 | P1-01 完成 |
| Batch 2 | P2-01, P2-02 | Batch 1 完成 |
| Batch 3 | P2-03 (单线程) | Batch 2 完成 |
| Batch 4 | P3-01, P3-02 | Batch 3 完成 |
| Batch 5 | P4-01, P4-02, P4-03, P4-04 | Batch 3 完成 |
| Batch 6 | P4-05 (Open Design) | P4-04 完成 |
| Batch 7 | P5-01, P5-02 | Batch 6 完成 |
| Batch 8 | P5-03 | Batch 7 完成 |

---

## 三、关键决策记录

### 3.1 用户提出的关键要求

1. **功能模块扩展**: 用户要求在初始 4 个模块基础上增加 8 个模块，最终形成 13 个模块
2. **凭据安全**: 禁止硬编码 API Key，要求 OS 钥匙串 + 管理 CLI
3. **Open Design 集成**: 替换自建 WebUI，通过 HTTP API 集成 Open Design Daemon
4. **脱离 LLM 可单测**: 所有核心机制必须能用 MockLLM 做确定性测试
5. **三种接口并存**: CLI + REST API + WebUI 三种接口都必须提供

### 3.2 被修正的 AI 建议

| 建议 | 用户修正 | 原因 |
|------|---------|------|
| Docker 沙箱 | subprocess + 权限限制 | 更轻量，无需 Docker 依赖 |
| 仅 REST API | CLI + REST API + WebUI | 用户需要多种交互方式 |
| 环境变量凭据 | OS 钥匙串 | 更安全，符合课程要求 |

### 3.3 被采纳的 AI 建议

| 建议 | 说明 |
|------|------|
| Python 技术栈 | FastAPI + structlog + pytest |
| Open Design 集成 | 替换自建 WebUI |
| LLM Adapter 模式 | 抽象接口 + Mock 实现 |
| 领域与机制设计 | 四类机制（工具/反馈/危险动作/记忆） |

---

## 四、当前状态

### 4.1 已完成

- [x] Brainstorming — 设计确认（13 个模块）
- [x] Writing-Plans — SPEC.md（14 章）+ PLAN.md（18 个 task）
- [x] SPEC_PROCESS.md — 过程文档
- [x] AGENT_LOG.md — 代理日志
- [x] 对照 requirements.md 检查 — 所有缺失项已补充

### 4.2 待完成

- [ ] 冷启动验证（requirements.md §4.5）— 用陌生 agent 仅凭 SPEC + PLAN 实现 1-2 个 task
- [ ] Using-Git-Worktrees — 初始化 git 仓库，创建 worktree
- [ ] Subagent-Driven-Development — 每个 task 派 subagent 实现
- [ ] Test-Driven-Development — 先红后绿再重构
- [ ] Requesting-Code-Review — 两阶段评审
- [ ] Finishing-A-Development-Branch — 合并/PR

### 4.3 当前工作目录

```
C:\Users\46240\Desktop\harness_LLM\
├── SPEC.md          # 完整设计规约（14 章）
├── PLAN.md          # 执行计划（18 个 task）
├── SPEC_PROCESS.md  # 过程文档
├── AGENT_LOG.md     # 代理日志
├── requirements.md  # 课程要求
├── readme.md        # 初始占位
└── src/             # 空目录
```

---

## 五、接续指南

### 5.1 下一步操作

1. **冷启动验证**（必须）：用一个与当前 agent 不同的智能体，在全新 session 中仅提供 `SPEC.md` + `PLAN.md`，让它实现 P1-01（项目骨架），记录它遇到的问题和 spec 缺陷
2. **根据冷启动反馈修改** SPEC.md 和 PLAN.md
3. **初始化 git 仓库**: `git init`，创建 main 分支
4. **创建 worktree**: 为每个 Batch 创建独立的 worktree
5. **开始 Phase 1 实现**: 从 P1-01 开始，按 PLAN.md 顺序执行

### 5.2 关键文件路径

- 源代码: `src/harness/`
- 测试: `src/tests/`
- 配置示例: `examples/config.yaml`
- 任务示例: `examples/task.yaml`
- 容器: `Dockerfile`
- CI: `.github/workflows/ci.yml`

### 5.3 重要约束

- 所有核心机制必须通过 MockLLM 做确定性单元测试
- 凭据绝不能硬编码、绝不能提交至 Git
- 每个 task 必须先写失败测试（TDD）
- 每个 task 完成后标记 PLAN.md 并附 commit hash
- 维护 AGENT_LOG.md 持续更新