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

### [2026-08-01] — GitHub PR 工作流完成 + 部署前改进

- **技能**: `finishing-a-development-branch`（PR 序列）、`test-driven-development`
- **操作**:
  - 重置 main 到开发起点，通过 GitHub 逐个合并 18 个任务 PR（PR #1-17 按依赖顺序 + PR #19 承载 final review 修复；PR #18 因历史冲突关闭）
  - 修复 Dockerfile 两处 CI 阻塞（hatchling 构建后端 + wheel 文件名规范），最终 CI 三 job 全绿
  - 文档恢复（PLAN 标记/冷启动/凭据自查因 reset 丢失，从保留 commit 恢复并推送）
- **人工决策**: 部署暂停；先确认 WebUI 架构 + API-key 接入口；随后处理三个改进建议
- **改进实现**:
  - 建议1: `harness init` 生成的 harness.yaml 添加 API-key 配置注释（keyring / env / mock 三方式）
  - 建议2: README Docker 章节说明容器内用 `credential.backend: env` + `HARNESS_*` 注入
  - 建议3: 新增 `python-dotenv` 依赖，`load_config` 自动加载 `.env`（不覆盖已有环境变量）；新增 4 测试
- **成果**: 155 测试通过（+4），ruff clean；提交待推送
- **教训**: main reset 重写历史会丢失"不在任何任务分支上的收尾文档 commit"——应先把文档 commit 合并进某分支再 reset，或用 cherry-pick 恢复

## 2026-08-02

### [2026-08-02] — Phase 6 WebUI Dashboard 与运行时对话

- **技能**: `using-git-worktrees`, `subagent-driven-development`, `test-driven-development`, `verification-before-completion`
- **操作**: 在独立 worktree `p6-dashboard` 上按 P6-01..P6-06 顺序完成 Phase 6，每 task 先红后绿 TDD
- **成果**:
  - P6-01 `41e685b` MessageQueue：线程安全消息队列（Lock + Event 事件等待，push 唤醒等待者）
  - P6-02 `daf4fbf` Orchestrator 新增 `USER_INPUT` 状态，未传 message_queue 时行为与现状一致（向后兼容）
  - P6-03 `f9aec63` REST 对话端点：`POST /api/tasks/{id}/message` / `GET /api/tasks/{id}/messages` / `POST /api/tasks/{id}/interrupt`
  - P6-04 `60ed6bb` 零依赖 Dashboard 静态前端（任务列表/HITL 按钮/运行时对话/文件上传/连接状态灯，无 CDN、无外部引用，全部内联）
  - P6-05 `ce14561` `harness dashboard` CLI（`--host`/`--port`/`--config`）与 `config.webui` section（默认 `127.0.0.1:8000`）
  - P6-06 `7a16d6e` README/PLAN/AGENT_LOG 文档收尾
  - 最终 180 测试通过，ruff clean
- **人工裁决**: Dashboard 硬性约束为开箱即用、零外部依赖（不依赖 Open Design、无 CDN/外部资源）；Open Design 保持可选增强（`harness webui`），未安装/未启用不影响 Dashboard 与全部 CLI/REST API 功能
- **教训**: 把"零外部依赖"这类非功能性约束转成可回归的确定性断言——`test_dashboard_no_external_refs` 校验 index.html 无 `http(s)://` 外部资源引用，避免前端后续引入 CDN 而不自知

### [2026-08-02] — Phase 6 WebUI Dashboard 完成 + 网络阻断推送

- **技能**: subagent-driven-development, test-driven-development, requesting-code-review, finishing-a-development-branch
- **操作**: 完成 Phase 6 六个任务（P6-01 MessageQueue / P6-02 USER_INPUT / P6-03 API 端点 / P6-04 零依赖 dashboard / P6-05 dashboard CLI / P6-06 文档），每任务 TDD + review；final review 修复 C1（asset 404）+ I2/I3/I4/T1
- **成果**: 184 测试通过，dashboard 零外部依赖开箱即用
- **推送**: github.com 网络阻断 → 用 GitHub git data REST API（走 api.github.com）增量重建 9 个 commit 推送，远程与本地 tree 完全一致，CI 三 job 全绿
- **教训**: github.com 与 api.github.com 可能被网络环境区别阻断；git data API 的 commit SHA 与本地不同（content-addressed 仅对 blob/tree 成立），需维护 commit SHA 映射
## 2026-08-14

### [2026-08-14] — 真实 LLM 写文件修复：work_dir 锚定 + run_shell cwd + file_path 别名

- **技能**: `brainstorming`, `writing-plans`, `subagent-driven-development`, `systematic-debugging`, `finishing-a-development-branch`
- **背景**: DeepSeek 写文件任务频繁失败——文件区与对话区均空。多次提示词强化无效，改用代码层修复。
- **根因调查**（systematic-debugging 证据链）:
  - ① 沙箱启用时 `run_shell` 的 `cwd` 继承进程目录（项目根），非任务 work_dir → shell 写文件落到项目根 → 文件区（扫描 work_dir）恒空
  - ② 沙箱预检用项目根语义（`allowed_dirs=["."]`），与工具层锚定的任务 work_dir 不一致
  - ③ **写文件失败真因**：DeepSeek 用 `file_path`/`filepath` 参数键调用 write_file，而 harness 只读 `path` → 沙箱读到空路径永远拒绝（此前"路径越界"诊断方向是错的）
  - ④ 对话区空：LLM 全程工具调用 + `{"done":true}`，无自然语言 → conversation_sink 不触发
- **设计**（brainstorming → spec）：方案 A —— 写文件硬锚定到任务 work_dir，机制全在代码（非提示词，符合 §A.4 B/C）
- **实现**（subagent-driven-development，worktree `work-dir-anchoring`，6 commit + final review 1 commit）:
  - `30d172e` `Sandbox.allow_dir` + `Sandbox.run` 加 `cwd`
  - `c5ebba2` 修复 run_shell 沙箱下 cwd（之前跑到项目根）
  - `822e56e` work_dir 路由到 `harness-tasks/<task_id>` + 自动创建 + 沙箱锚定
  - `5dea568` 修复 `.`/`..` id 逃逸
  - `d48c394` `.gitignore` 加 `harness-tasks/`
  - `1b0bcb0` final review 修复：drive-colon id 逃逸 + 锁 + OSError + 测试强化
- **post-merge 修复**（systematic-debugging 定位真因）:
  - `21ead37` 兼容 `file_path`/`filepath` 参数别名（写文件真因）
  - `e574671` 系统提示要求完成前先自然语言总结
  - `6dc8d52` CI 跨平台修复（Linux 上 `cd` 无输出）
- **人工裁决**: ① 写文件越界 → 拒绝（不自动重定位）② work_dir 用已存在的 `harness-tasks/` ③ 对话区空 → 提示要求自然语言总结 ④ 后续可能放宽为用户指定目标文件夹（暂不做）
- **成果**: 236 → 238 测试通过，ruff clean，CI 3 job 全绿；真实 DeepSeek 端到端 PASS（对话区 + 文件区均有内容）；清理 85 个旧 `harness-task-*` 残留目录
- **教训**: 真实 LLM 的参数键名不可控，工具层应宽容解析别名而非假设严格契约；诊断"沙箱拒绝"时应先捕获工具实际收到的 params，而非猜测路径内容

### [2026-08-15] — 交付物审计与文档同步

- **技能**: 无（纯文档检查与更新）
- **操作**: 按 requirements.md 五条交付物逐项审计
- **审计结果**:
  - ① SPEC.md / PLAN.md / SPEC_PROCESS.md：SPEC_PROCESS 无需改；SPEC.md 补 work_dir 锚定机制；PLAN.md P6-12 更新为最终实现
  - ② 完整源码 + commit/PR 历史：完整；凭据扫描零真实 key；`.env` 未跟踪 ✓
  - ③ Dockerfile + 分发说明：完整（多阶段构建 + 非 root + 容器内 env key 说明）✓
  - ④ README.md：补"目录结构"章节（原缺失，要求必须有）、"已知限制"章节、work_dir 锚定说明、更新过时的 `harness-task-*` 描述
  - ⑤ AGENT_LOG.md：补 08-14/08-15 日志（本条目）
- **教训**: README 曾缺"目录结构"与"已知限制"两个要求章节；收尾阶段应逐条对照 requirements 交付清单核验文档完整性
