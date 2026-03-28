# 仓库协作约定

## 发版

- 当用户说“发版”“发布新版本”“release”等同类意图时，默认立即进入标准发版流程，不再额外追问“是否开始”。
- 标准发版流程按以下顺序执行：
  1. 检查 `git status --short`、当前分支、[`version.py`](D:\V1.0\version.py)、最近 `git log`，并读取 [`.windsurf/workflows/release.md`](D:\V1.0\.windsurf\workflows\release.md)。
  2. 若用户已给出精确版本号，优先按目标版本推导 `hotfix` / `patch` / `minor` / `major`；若当前版本已等于目标版本，则改用 `--no-bump`。若用户未给出版本号，再用 `request_user_input` 询问版本级别。
  3. 若工作区存在未提交改动，必须先确认这些改动是否全部纳入本次发版；未确认前不要直接执行正式发布。
  4. 根据 `git diff` 与最近提交自动归纳 changelog；若用户没有提供说明，优先用 `request_user_input` 让用户选择“我来归纳 / 通用说明 / 用户补充”。
  5. 发版前先执行与本次改动强相关的验证，至少包含相关 `pytest` 用例；必要时补充构建或冒烟校验。
  6. 使用项目虚拟环境执行 `tools/release.py` 完成正式发版，除非用户明确要求，否则不要绕过该脚本手工发版。
  7. 发版完成后核对版本号、tag、GitHub Release、Gist/version.json 以及最终 `git status`，再向用户汇报结果。
- 若正式发版依赖的 Token、网络、分支或构建条件不满足，需要先说明阻塞项，再和用户确认是否继续处理。
