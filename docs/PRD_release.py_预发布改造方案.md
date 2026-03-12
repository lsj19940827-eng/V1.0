# PRD：`tools/release.py` 预发布双通道改造方案

> 版本：v1.0  
> 日期：2026-03-07  
> 目标：在不破坏现有正式发版流程前提下，支持“分支预发布 + 测试更新通道”

---

## 1. 背景与目标

当前 `tools/release.py` 默认行为是：

- 自动 bump `version.py`
- 创建正式 Release
- 更新单一 Gist `version.json`

这不满足“候选分支验证”的治理要求。改造后需支持：

1. 正式发布：`master` → 正式 Release → 正式 Gist
2. 预发布：候选分支 → Pre-release → 测试 Gist
3. 预发布可选不改 `version.py`（避免消耗正式版本号）

---

## 2. 范围与非范围

### 2.1 范围

- `tools/release.py` 参数与流程改造
- `repo_config.py` 增加测试 Gist 配置项
- 发版日志输出增强（明确通道、分支、目标 Gist）

### 2.2 非范围

- `updater.py` 版本比对算法改造（本方案不引入 semver 预发布比较）
- GUI 发版工具 `tools/release_gui.py`（可后续跟进）

---

## 3. CLI 设计

## 3.1 新增参数

| 参数 | 类型 | 默认 | 含义 |
|------|------|------|------|
| `--prerelease` | flag | false | 发布为 GitHub Pre-release |
| `--gist-target` | `prod`/`test` | `prod` | 指定更新正式或测试 Gist |
| `--no-bump` | flag | false | 跳过 `version.py` 递增 |
| `--tag-suffix` | str | 空 | 附加 tag 后缀（如 `beta.20260307.1`） |

## 3.2 行为矩阵

| 分支 | `--prerelease` | `--gist-target` | 结果 |
|------|----------------|-----------------|------|
| `master` | 否 | `prod` | ✅ 正式发布 |
| `master` | 是 | `test` | ✅ 预发布（可用于主干灰度） |
| 非 `master` | 否 | 任意 | ❌ 阻断 |
| 非 `master` | 是 | `test` | ✅ 预发布 |
| 任意 | 是 | `prod` | ❌ 阻断（防污染正式通道） |

---

## 4. 关键实现点

## 4.1 分支校验

- 在进入发布流程前读取当前分支（已有逻辑可复用）。
- 当 `branch != "master"` 且未启用 `--prerelease` 时，直接退出并提示。

## 4.2 版本处理

- 现有路径：`step_bump_version(level)`。
- 新增分支：
  - 若 `--no-bump`：读取当前 `version.py` 作为本次发布版本，不执行 bump。
  - 否则沿用现有 bump 行为。

## 4.3 tag/name 生成

- 正式：`v{version}`
- 预发布：
  - 无后缀：`v{version}-beta`
  - 有后缀：`v{version}-{tag_suffix}`

Release 标题同样带后缀，便于页面识别。

## 4.4 Release payload

- `prerelease` 字段由 `--prerelease` 决定：
  - 正式：`false`
  - 预发布：`true`

## 4.5 Gist 目标选择

- `repo_config.py` 保留 `GIST_ID`（正式）并新增 `GIST_ID_TEST`（测试）。
- `step_update_gist()` 新增参数 `gist_target`：
  - `prod` → `GIST_ID`
  - `test` → `GIST_ID_TEST`

---

## 5. 兼容与安全

## 5.1 向后兼容

- 不带新增参数时，行为保持现有正式发版逻辑。

## 5.2 安全保护

必须增加以下阻断：

1. 非 `master` 且未 `--prerelease`。
2. `--prerelease` + `--gist-target prod`。
3. `--gist-target test` 但未配置 `GIST_ID_TEST`。

---

## 6. 日志与可观测性

每次发布开始时输出：

- 当前分支
- 发布类型（正式/预发布）
- 是否 bump
- 目标 Gist（prod/test）
- 最终 tag

发布完成后输出：

- Release URL
- Gist 更新目标与 URL
- 产物清单（全量/补丁）

---

## 7. 验收测试

## 7.1 功能测试

1. `master` 正式发布成功，写正式 Gist。
2. 候选分支无 `--prerelease` 发布被阻断。
3. 候选分支 `--prerelease --gist-target test` 成功。
4. `--prerelease --gist-target prod` 被阻断。
5. `--no-bump` 时 `version.py` 不变。

## 7.2 回归测试

1. 旧命令 `python tools/release.py patch` 在 `master` 行为不变。
2. 发布后 `dist/` 产物命名与下载流程兼容现有 updater。

---

## 8. 实施步骤（建议顺序）

1. 在 `repo_config.py` 增加 `GIST_ID_TEST`。
2. 扩展 `argparse` 参数定义。
3. 增加分支校验与参数组合校验。
4. 增加 `--no-bump` 路径。
5. 增加预发布 tag/name 逻辑。
6. 改造 `step_update_gist()` 支持目标 Gist。
7. 增加日志输出与错误提示。
8. 执行第7章测试用例并记录结果。

