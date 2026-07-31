# AGENT_LOG.md — 代理工作日志

## 约定

- 按时间顺序记录关键节点
- 每条包含：时间戳、task 编号、触发的技能、关键操作、人工干预、学到的教训

---

## 2026-07-26

### [2026-07-26 00:00] — 项目初始化 & Brainstorming

- **技能**: `brainstorming`
- **操作**: 启动智能体，读取 workspace 和 requirements.md，开始 brainstorming 流程
- **关键决策**:
  - 选择 Python 技术栈
  - 确定项目为 Coding Agent Harness (A 类项目)
  - 设计 12 个功能模块
- **人工干预**: 用户要求增加凭据存储、分发/CI/CD、Mock-LLM 三个模块
- **教训**: 初始 brainstorming 时智能体未主动检查 requirements.md 中的课程约束，导致后续需要多次补充

### [2026-07-26 00:30] — Writing Plans

- **技能**: `writing-plans`
- **操作**: 将 brainstorming 结果转化为 SPEC.md 和 PLAN.md
- **产出**: 初始版 SPEC.md（12 模块 + 架构图 + 技术选型）、PLAN.md（18 个 task + 依赖关系）
- **人工干预**: 用户要求增加 Open Design 集成，修改 SPEC.md 和 PLAN.md
- **教训**: Open Design 的集成方案需要先调研其架构再决定，避免空对空的设计

### [2026-07-26 01:00] — Open Design 调研

- **技能**: `explore` (subagent)
- **操作**: 调研 Open Design 仓库的架构、插件系统、MCP 集成方式
- **关键发现**: Open Design 通过 HTTP API (port 7456) 和 MCP stdio 两种方式暴露能力，Python 可以通过 httpx 客户端集成
- **产出**: Open Design 集成方案（模块 13）
- **人工干预**: 无

### [2026-07-26 01:30] — SPEC.md 补充检查

- **技能**: 手动检查
- **操作**: 对照 requirements.md 中的 SPEC 要求清单逐项检查
- **发现缺失**:
  - 用户故事（至少 5 个）
  - 数据模型
  - 验收标准
  - 风险与未决问题
  - 领域与机制设计（A 项目特有）
  - 凭据威胁模型
  - Open Design 设计系统与 skill 说明
  - 非功能性需求
- **人工干预**: 用户要求补充所有缺失项
- **教训**: 应该在 brainstorming 结束时主动做完整性检查，而不是等到用户要求

### [2026-07-26 02:00] — SPEC.md 完整重写 & PLAN.md 规范化

- **技能**: 手动编辑
- **操作**: 重写 SPEC.md（14 个章节，含所有缺失项），规范化 PLAN.md（每个 task 添加 TDD 测试 + 验证步骤）
- **产出**:
  - SPEC.md: 14 章 → 项目概述、用户故事、功能规约、非功能性需求、系统架构、数据模型、凭据与分发设计、技术选型、验收标准、风险与未决问题、领域与机制设计、实现顺序、文件结构、测试策略
  - PLAN.md: 每个 task 添加 "TDD 先写测试" 和 "验证步骤" 子节，新增完成清单
- **人工干预**: 用户要求进一步规范 PLAN.md 书写
- **教训**: PLAN.md 的 task 颗粒度需要足够细，每个 task 的验证步骤要具体到可执行的命令