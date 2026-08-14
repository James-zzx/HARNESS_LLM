# 设计：写文件硬锚定任务 work_dir

- 日期：2026-08-14
- 状态：已批准
- 范围：harness_LLM 仓库

## 背景与问题

DeepSeek 等真实 LLM 在写文件时，可能传绝对路径、`..` 越界路径或猜错的任务临时目录名，导致 `write_file`/`edit_file` 被沙箱拒绝（沙箱预检用项目根语义 `allowed_dirs=["."]`，与工具层锚定的任务 `work_dir` 不一致）。结果是产物写不进任务目录、对话区和文件区无内容。

## 目标

1. 写文件（write_file / edit_file）路径硬锚定到**任务自己的 work_dir**，越界一律拒绝。机制全在代码（工具层 `_PathTool._resolve` + 沙箱预检），不依赖提示词，符合 §A.4(B)(C)：移除真实 LLM 后仍可用确定性单测验证。
2. work_dir 统一落在**已存在的 `harness_LLM/harness-tasks/` 文件夹**下，每任务一个子目录 `<project>/harness-tasks/<task_id>`。
3. `harness-tasks/` 加入 `.gitignore`；若文件夹不存在（新用户从 GitHub 下载后首次运行），自动创建。

## 非目标（明确不做）

- 暂不实现"用户指定目标文件夹"的放宽配置（后续再考虑）。
- 不限制 run_shell 的路径（仅 cwd=work_dir，黑名单命令不变），避免影响正常测试/构建命令。

## 改动点

### ① 沙箱支持动态追加 allowed_dirs（sandbox.py）

新增方法：

```python
def allow_dir(self, path):
    resolved = Path(path).resolve()
    if not any(_is_within(resolved, a) or resolved == a for a in self._allowed_paths):
        self._allowed_paths.append(resolved)
        self.allowed_dirs.append(str(resolved))
```

幂等（同目录重复调用不重复追加）。允许目录是 work_dir 的祖先（如项目根）时也保持幂等。

### ② 复用并自动创建 harness-tasks/（api.py `_default_runner`）

- work_dir 基目录 = `<项目根>/harness-tasks`（相对 runtime.work_dir 即项目根）。
- 若 `harness-tasks/` 不存在则 `mkdir(parents=True, exist_ok=True)`。
- 每任务 work_dir = `<harness-tasks>/<task_id>`；task_id 为空或含路径分隔符时回退到随机目录名（`mkdtemp`）。
- 创建后调用 `runtime.sandbox.allow_dir(task_work_dir)`，把该任务 work_dir 追加进沙箱 allowed_dirs。
- 保持 `manager.set_work_dir(task.id, task_work_dir)` 以便文件端点读取。

### ③ 工具层锚定保持（tool_executor.py）

`_PathTool._resolve` 已锚定 work_dir 并拒绝 `..`/绝对越界路径（tool_executor.py:33-37），无需改动。这是沙箱预检之外的第二道防线。

### ④ .gitignore

新增一行 `harness-tasks/`。

## 数据流

```
POST /api/tasks → _default_runner
  → 确保 harness-tasks/ 存在（不存在则创建）
  → work_dir = harness-tasks/<task_id>（id 非法时 mkdtemp 回退）
  → runtime.sandbox.allow_dir(work_dir)        ← 新增
  → build_orchestrator(work_dir)
LLM 意图 write_file path=X
  → 沙箱预检 is_allowed_path(X)  [work_dir ∈ allowed_dirs]
      ├─ 越界（绝对/../系统）→ 拒绝 → LLM 收到 error 重试
      └─ 放行 → 工具层 _resolve 锚定 work_dir
                  ├─ 仍越界 → 拒绝（双保险）
                  └─ 合法 → 写入 work_dir/<task_id>/ 下
产物 → GET /api/tasks/{id}/files 扫描 work_dir 展示（已实现）
```

## 错误处理

- 越界拒绝返回现有 `sandbox denied execution of <tool>`（沙箱）或 `path escapes working directory`（工具层），LLM 据提示词重试。
- `harness-tasks/` 创建失败（权限等）时抛 TaskError，任务标记失败。

## 测试

新增/修改（全部无 LLM、确定性，符合 §A.4(C)）：

1. `test_sandbox.py`：
   - `allow_dir` 追加后，相对路径解析到该目录内 → 放行。
   - 越界路径（`../`、系统绝对路径）→ 仍拒绝。
   - `allow_dir` 幂等：同一目录重复调用不重复追加。
   - `allow_dir` 传入 work_dir 的祖先目录（如项目根）时幂等。
2. `test_api.py`：
   - 新建任务后 `manager.get_work_dir(task_id)` 落在 `<项目根>/harness-tasks/<task_id>`。
   - `harness-tasks/` 不存在时自动创建。
   - 沙箱 allowed_dirs 含该任务 work_dir。
3. `test_tool_executor.py`：
   - 既有 `test_path_traversal_blocked` 保持（回归双保险）。

## 验证步骤

1. `python -m pytest src/tests/ -q` 全量通过（预期 223+）。
2. 用 mock LLM 提交写文件任务，确认产物出现在 `<项目根>/harness-tasks/<task_id>/` 且 `GET /api/tasks/{id}/files` 能列出。
3. 删除 `harness-tasks/` 后重启 dashboard 并提交任务，确认自动重建。
4. 提交 `.gitignore` 改动，确认 `harness-tasks/` 未被 git 跟踪。
