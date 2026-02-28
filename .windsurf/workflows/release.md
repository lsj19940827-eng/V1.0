---
description: 一键发版 - 自动递增版本号、打包、git提交、创建GitHub Release、上传zip、更新Gist
---

当用户说"发版"、"发布新版本"、"release"等类似意图时，执行此工作流。

## 步骤

1. 先询问用户两个信息：
   - **版本级别**：patch（补丁）/ minor（次版本）/ major（主版本），默认 patch
   - **更新日志**：这次改了什么（用于 changelog），可以从最近的 git log 中提取

2. 确认后，运行发版命令：
// turbo
```
python tools/release.py <level> -m "<changelog>"
```
工作目录：`c:\Users\大渔\Desktop\V1.0`

该命令自动完成 7 步：
1. 递增 `version.py` 版本号
2. PyInstaller 打包（全量包 + 增量补丁包）
3. Git commit + tag + push
4. 创建 GitHub Release
5. 上传 zip 到 Release Assets
6. 更新 Gist `version.json`（用户客户端自动检测到新版本）
7. 同步到局域网共享文件夹（如可访问）

3. 命令执行完成后，确认输出中没有错误，向用户报告发版结果。
