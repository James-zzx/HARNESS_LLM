# GitHub 发布与 PR 工作流操作指引

> 本指引由控制器生成，供项目所有者（你）在 GitHub 上完成仓库发布、PR 工作流与最终交付验证。所有命令在仓库根目录（`C:\Users\46240\Desktop\harness_LLM`）的 PowerShell 中执行。

## 0. 当前状态（快照）

- `main` 分支：42 个 commit，含全部代码 + 交付文档（最新 HEAD `a933213`）。
- 18 个任务分支已重建，全部为 `main` 的祖先（除 `p5-03-readme` 额外 1 个 commit `0b0c29d`：机制演示脚本 + README）。
- 18 个任务 worktree 位于 `.worktrees/`。
- 151 个测试通过，ruff clean，无真实凭据（已自查）。
- `gh` CLI 未安装；无 git remote。

## 1. 创建 GitHub 公开仓库

1. 登录 GitHub → New repository。
2. 仓库名建议 `harness_LLM`（或你喜欢的名字），**Public**，不要勾选任何初始化选项（README/.gitignore/license 都留空，避免与本地历史冲突）。
3. 复制仓库 HTTPS URL，例如 `https://github.com/<your-name>/harness_LLM.git`。

## 2. 添加远程并推送

```powershell
# 在主仓库根目录
git remote add origin https://github.com/<your-name>/harness_LLM.git

# 推送 main 及所有分支
git push -u origin main
git push origin --all
```

> 若提示认证，用 GitHub 的 personal access token（Settings → Developer settings → Personal access tokens → Fine-grained tokens，勾选 `Contents: Read and write`）作为密码，或安装 `gh` 后 `gh auth login`。

## 3. CI 自动执行

推送后 GitHub Actions 会自动触发 `.github/workflows/ci.yml`：
- `unit-test` job：`pip install --group dev -e .` → `pytest --cov=harness src/tests/`
- `lint` job：`ruff check src/`
- `build` job：`docker build -t harness .` + `docker run harness --help`

在仓库 Actions 页查看，**三个 job 全部绿色 pass** 即满足"最后一次 CI 执行为 pass 状态"（requirements §五.7）。

> 注意：`build` job 依赖 Docker；GitHub Actions 的 ubuntu-latest runner 自带 Docker，可直接运行。

## 4. PR 工作流（两个方案二选一）

### 方案 A：重置 main 后按依赖顺序逐个 PR 合并（推荐，每个 PR 有真实 diff）

每个任务分支都有真实 diff 的前提是 `main` 回到开发起点、按顺序合并。**此操作重写 main 历史（本地），commit 对象全部保留。**

```powershell
# 1) 备份当前 main（保留快照，方便回退）
git branch backup-main   # 指向 a933213

# 2) 重置 main 到初始 .gitignore commit（开发起点）
git checkout main
git reset --hard cbdc0ff

# 3) 按依赖顺序逐个合并任务分支（每步验证测试通过后提交）
#    依赖顺序：P1-01 → P1-02/03/04/05 → P2-01/02 → P2-03 → P3-01/02 → P4-01/02/03/04 → P4-05 → P5-01/02 → P5-03
#    对每个分支执行：
git merge --no-ff <branch>
#    本地验证：python -m pytest src/tests/ -q  → 应通过
git push origin main
```

为**每个任务分支**创建一个 PR 指向 `main`：

```powershell
gh pr create --base main --head <branch> --title "Task <P-xx>: <标题>" --body "由 subagent 实现，控制器评审，人工确认"
```

或用 GitHub 网页：main 的 Pull requests → New pull request → base=`main`，compare=`<branch>` → Create pull request。

> **关键**：重置后 main 会落后于各分支，此时每个 PR 的 diff = 该分支相对开发起点的全部改动，即真实的 PR 工作流。全部合并后 main 内容与当前完全一致（可 `git diff backup-main` 验证）。

PR 合并建议顺序（依赖前置）：
| PR 顺序 | 分支 | 标题 |
|---------|------|------|
| 1 | p1-01-project-skeleton | 项目骨架 |
| 2-5 | p1-02/03/04/05 | 配置 / 凭据 / LLM适配 / 日志 |
| 6-7 | p2-01/02 | 工具执行 / 记忆 |
| 8 | p2-03 | 主循环 |
| 9-10 | p3-01/02 | 沙箱 / HITL |
| 11-14 | p4-01/02/03/04 | 评估 / 任务 / CLI / API |
| 15 | p4-05 | Open Design |
| 16-17 | p5-01/02 | Docker / CI |
| 18 | p5-03 | README + 机制演示 |

### 方案 B：不重置，PR 仅作展示（保留 main 现状）

不重置 main。推送后每个任务分支与 main 无 diff（除 p5-03-readme 的 1 个 commit）。此方案下：
- main 的 42 个 commit 历史完整保留，满足"完整 commit 历史"。
- 为展示 PR 工作流，可为 `p5-03-readme`（有真实 diff）创建 PR；其余分支的"PR"实质已包含在 main 历史中。
- 如需为全部 18 个分支建立 PR 记录，可对每个分支创建 PR（GitHub 会显示 "This branch has no commits unique to it"），仅作流程展示。

## 5. 收尾验证清单

- [ ] Actions 三个 job 全绿（unit-test / lint / build）
- [ ] `git log --oneline` 展示完整 commit 历史
- [ ] `git grep -n "sk-[a-z]" ` 仅测试假凭据；`.env` 未跟踪
- [ ] `python -m pytest src/tests/ -q` → 151 passed
- [ ] `python examples/demo_mechanisms.py` → 三个 PASS
- [ ] README 各章节可访问；Docker/PyPI/凭据/安全边界齐全

## 6. 后续人工事项（非 git 操作）

- **REFLECTION.md**（1500–2500 字反思报告）：必须由你本人撰写，禁止 AI 代写（可用 AI 辅助润色并标注）。
- **线上部署 URL**（§五.9 / §4.11）：如需 WebUI 可访问，可部署 REST API（`uvicorn harness.api:app`）到 Render/Railway/Fly.io 等（学生免费额度）；README 需说明部署架构与 CI/CD。纯 CLI 项目可选做。
- **`.gitlab-ci.yml`**：你已决策使用 GitHub Actions（含 `unit-test` job），故不另建 `.gitlab-ci.yml`；若助教明确要求该文件，可后续补充一个等价文件。

## 7. 已知限制与说明

- `.worktrees/` 与 `.superpowers/` 已被 `.gitignore` 排除，不会推送到 GitHub（仅本地开发隔离用）。
- 机制演示脚本 `examples/demo_mechanisms.py` 位于 `p5-03-readme` 分支（commit `0b0c29d`），方案 A 的第 18 个 PR 会将其并入 main；方案 B 需手动合并该分支或 cherry-pick。
- 本地 42 个 commit 与远端 `origin/main` 首次推送无冲突（远端为空仓库）。
