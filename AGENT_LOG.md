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

## 2026-08-01

### [2026-08-01] — Subagent-Driven-Development 全流程执行

- **技能**: `using-git-worktrees`, `subagent-driven-development`, `test-driven-development`, `requesting-code-review`, `finishing-a-development-branch`
- **操作**: 按 SESSION-001.md 接续指南执行 18 个 task（每 task 独立 worktree + implementer subagent + task review + fix loop），最终 whole-branch review + 3 轮 fix wave + 合并回 main
- **成果**:
  - 18/18 tasks 完成（Phase 1-5），每 task 先红后绿 TDD + spec/quality review
  - 关键修复: P1-02 配置合并丢失兄弟字段、P3-01 命令黑名单复合绕过、P1-04/P2-02/P2-03/P4-02 数据模型协调
  - Final review 发现并修复 4 Critical（护栏未接线/run_shell 无限制/API 认证失败/env 后端缺失）+ 8 Important
  - 最终 151 测试通过，ruff clean，HEAD 081b442 合并入 main
- **人工裁决**: P4-02 timeout 默认 120 + 补 status 字段；P3-02 保留 PAUSED 终态契约 + 危险命令规则取并集
- **教训**: 护栏（sandbox→rule engine→HITL）初版仅为库代码未接入生产路径，final review 实测暴露后补齐 runtime.py 接线——安全维度必须从第一步就端到端接线验证
- **遗留**: 2 个 SAFE-TO-DEFER minor（`$()`-glued 遍历 pre-existing、HITL daemon 线程驻留）；git history 为最终记录，SDD workspace 已删除

### [2026-08-01] — 交付物收尾与凭据自查

- **技能**: `verification-before-completion`（对照 requirements.md 逐项自查）
- **操作**:
  - 回溯恢复 worktrees 合并前状态（fast-forward 保证 41 个 commit 全保留，18 分支 + 18 worktree 精确重建）
  - PLAN.md 回填：18 个 task 全部标记完成并附 commit hash（1dd3738…081b442），完成清单勾选
  - 新增机制演示 `examples/demo_mechanisms.py`（§A.6 三行为，离线确定性，全部 PASS）
  - SPEC_PROCESS.md 补冷启动验证记录（P1-01 陌生 agent 受阻点：包名/exit 5/依赖机制）
  - README 更新测试数与演示脚本
- **凭据自查（§4.7 提交前）**:
  - `git grep` 全历史扫描 `sk-` / `api_key=` / `Bearer `：所有命中均为测试假凭据（`sk-test`、`sk-abc123`、`sk-super-secret`、`sk-live-123`），无真实 key
  - `.env` 未跟踪、`.env` 在 .gitignore；无 CLAUDE/codex history 泄露
  - 日志脱敏已由 P1-05 + I8 修复验证
- **人工裁决**: ① GitHub（保留 GitHub Actions，不另做 .gitlab-ci.yml）② PLAN.md 回填 + 完整 commit/PR 工作流 ③ 演示用脚本
- **待人工**: GitHub 仓库推送与 PR 工作流、CI pass 确认、REFLECTION.md（须学生本人撰写）、线上部署 URL