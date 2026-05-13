# 渠系水力计算综合系统

渠系水力计算综合系统是一款 Windows 桌面软件，面向水利渠道工程的断面计算、水面线计算、倒虹吸、有压管道、隧洞、渡槽、暗涵、土石方和成果导出等日常工作。

本仓库主要用于项目代码管理、版本发布和在线更新镜像。普通用户建议通过正式安装包使用软件；开发和维护人员可按本文档在本地运行、测试和发版。

## 主要功能

- 明渠、渡槽、隧洞、暗涵、倒虹吸、有压管道、泄水渠与陡坡等水力计算。
- 表格化批量输入，支持 Excel 导入、示例数据、模板和工程文件保存。
- 水面线表、渐变段、连续承压线路、压力管道特性表等联动计算。
- 断面图、纵断面、DXF、TXT、Excel、Word 等成果导出。
- 自动更新：完整包使用 GitHub 发布包；补丁包在不超过 100MB 时会额外上传到 Gitee 作为备用下载地址。

## 仓库地址

| 用途 | 地址 |
|------|------|
| GitHub 主仓库 | <https://github.com/lsj19940827-eng/V1.0> |
| Gitee 镜像仓库 | <https://gitee.com/pig-farming-pays-off-as-a-dog/canal-update> |

GitHub 和 Gitee 的 `master` 分支保持同步。Gitee 只作为同一正式版本的补丁包备用下载源，不作为测试通道，也不承载完整安装包。

## 本地运行

建议在 Windows 环境下运行。项目依赖较多，首次运行请先创建虚拟环境并安装依赖：

```powershell
cd V1.0
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r tools\requirements.txt
.\.venv\Scripts\python.exe main.py
```

如果项目根目录已经存在 `.venv`，直接使用已有虚拟环境即可：

```powershell
.\.venv\Scripts\python.exe main.py
```

## 常用测试

更新链路回归：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_updater_versioning_unit.py tests/test_updater_install_flow_unit.py tests/test_update_helper_unit.py tests/test_release_snapshot_unit.py tests/test_release_gitee_unit.py -q --basetemp=.pytest_tmp\gitee-regression
```

结果导航和断面图回归：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_result_navigation_widget_unit.py tests/test_case_tag_navigator_ui_unit.py tests/test_section_plot_layout_unit.py tests/test_open_channel_panel_plot_unit.py tests/test_aqueduct_panel_plot_unit.py tests/test_culvert_panel_plot_unit.py tests/test_multi_case_panel_smoke_unit.py tests/test_result_summary_unit.py tests/test_culvert_comparison_unit.py -q --basetemp=.pytest_tmp\ui-prd-regression
```

泄水渠与陡坡第二版模块：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -k spillway_steep_chute --basetemp=.pytest_tmp\spillway-steep-chute-v2 -p no:hypothesispytest
```

## 打包与发版

本地打包：

```powershell
.\.venv\Scripts\python.exe tools\build.py
```

正式发版使用项目脚本：

```powershell
.\.venv\Scripts\python.exe tools\release.py patch
```

发版前需要在本地 `.env` 或系统环境变量中配置：

```env
GITHUB_TOKEN=你的 GitHub Token
GITEE_TOKEN=你的 Gitee 私人令牌
```

正式发版会创建 GitHub Release，并上传完整包和补丁包。Gitee 只在补丁包不超过 100MB 时创建同版本 Release 并上传补丁包；完整安装包不上传 Gitee，避免触发 Gitee 单附件大小限制。

## 自动更新规则

- GitHub Gist 仍是正式 `version.json` 的主入口。
- `download_url`、`patch_url` 等旧字段保持兼容。
- 新版本客户端会读取 `patch_url_mirrors`；当前完整包不写入 Gitee 镜像地址。
- 下载包必须通过同一个 SHA256 校验；任一来源校验失败都会被丢弃。
- 补丁下载或安装失败后，会自动回退完整安装包；完整包继续使用 GitHub 地址。

## 目录说明

| 路径 | 说明 |
|------|------|
| `main.py` | 程序入口 |
| `app_渠系计算前端/` | PySide6 桌面界面 |
| `calc_渠系计算算法内核/` | 主要计算内核 |
| `app_渠系计算前端/spillway_steep_chute/` | 泄水渠与陡坡正式模块界面、图表和导出 |
| `推求水面线/` | 水面线、渐变段和表3相关逻辑 |
| `tools/` | 打包、发版、发布快照和维护脚本 |
| `tests/` | 单元测试和回归测试 |
| `docs/` | PRD、发版指南和设计说明 |
| `data/` | 示例数据和模板 |

## 提交约定

以下内容不应提交到 GitHub 或 Gitee：

- `.env`、本地令牌和账号信息。
- `logs/`、缓存目录、构建产物和临时测试目录。
- 本地工程文件、用户成果文件和自动保存数据。
- 授权工具脚本、个人调试文件和临时导出文件。

## 搜索记录

- 2026-05-10：为 GitHub/Gitee 双下载源核对 Gitee 官方 OpenAPI Release 与附件上传接口；未重复搜索 skills.sh 或 GitHub 外部方案。
- 2026-05-12：泄水渠与陡坡模块按本地 PRD、教材 OCR 和项目既有明渠内核完成第一版与第二版实现；README 已有搜索记录，因此未重复访问 skills.sh 或 GitHub 搜索外部方案。

## 已完成功能与待办

- 已完成：明渠、渡槽、隧洞、暗涵、倒虹吸、有压管道和表3水面线的主要计算与导出链路。
- 已完成：泄水渠与陡坡第二版正式模块，支持矩形/梯形陡槽、熊启钧教学算例、新手/专业模式、三种水面线模式、水面线型识别、上下游衔接、掺气侧墙、水跃消能、出口整流、多流量控制、项目保存恢复、纵断面图和文档/表格导出。
- 待办：泄水渠与陡坡的表3正式结构类型接入、DXF 导出、扩散陡槽、多级消能、消力槛式和综合式消力池。

## 当前状态

- 当前版本号：`1.3.8`
- 当前主分支：`master`
- 当前更新策略：GitHub 完整包 + GitHub/Gitee 补丁包备用源
