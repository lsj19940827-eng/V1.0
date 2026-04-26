# 当前进度

- 当前正在做什么：准备发布 `1.3.2` 正式版。
- 上次停在哪个位置：已确认分支、版本、tag、token 和验证方案。
- 近期关键决定和原因：
- `1.3.1 -> 1.3.2` 按 `patch` 发版；发布说明采用朴素语言自动归纳，方便普通用户理解。
- 正式发版继续使用 `.venv\Scripts\python.exe tools\release.py patch`，由脚本统一完成版本递增、打包、提交、tag、GitHub Release 和 Gist 更新。
