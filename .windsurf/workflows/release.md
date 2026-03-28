---
description: 标准发版流程 - 检查工作区、确认版本与说明、验证、正式发布并核对结果
---

当用户说"发版"、"发布新版本"、"release"等类似意图时，执行此工作流。

## 步骤

1. 先读取并检查以下上下文：
   - `git status --short`
   - 当前分支
   - `version.py`
   - 最近 `git log`

2. 确认版本策略：
   - 如果用户已经明确给出目标版本号，优先按目标版本推导 `hotfix` / `patch` / `minor` / `major`
   - 如果当前版本已经等于目标版本，则改用 `--no-bump`
   - 如果用户没有给出目标版本号，再询问版本级别，默认 `patch`

3. 如果工作区有未提交改动，必须先确认这些改动是否全部纳入本次正式发版；未确认前不要直接执行发布。

4. 生成 changelog：
   - 优先根据 `git diff` 和最近提交自动归纳
   - 如果用户已提供更新说明，直接使用用户说明

5. 发版前执行与本次改动强相关的验证，至少包含相关 `pytest`；如果验证失败，先修复或向用户报告阻塞，不要继续正式发版。

6. 验证通过后，运行发版命令：
```
.venv\Scripts\python.exe tools/release.py <level> -m "<changelog>"
```
工作目录：`D:\V1.0`

7. 该命令会自动完成正式发版主流程：
   1. 更新 `version.py`
   2. PyInstaller 打包（全量包 + 通用补丁包）
   3. Git commit + tag + push
   4. 创建 GitHub Release
   5. 上传 zip 到 Release Assets
   6. 更新 Gist `version.json`

8. 命令执行完成后，再核对：
   - `version.py` 版本号
   - `git status`
   - 新 tag 是否存在
   - Release / Gist 是否更新成功

9. 最后向用户报告发版结果、版本号、关键验证项，以及任何需要注意的风险。
