# 渠系水力计算综合系统

渠系水力计算综合系统是一款 Windows 桌面软件，面向水利渠道工程的断面计算、水面线计算、倒虹吸、有压管道、隧洞、渡槽、暗涵、土石方和成果导出等日常工作。

本仓库主要用于项目代码管理、版本发布和在线更新镜像。普通用户建议通过正式安装包使用软件；开发和维护人员可按本文档在本地运行、测试和发版。

规范原件与OCR文本见[规范资料索引](docs/规范资料/README.md)，本轮有压管道目录、输入校验和工程边界见[规范配套核验报告](docs/有压管道规范配套核验.md)。

钢管输入统一为公称外径：留空时先反算满足流速和水损上限的最小净内径，补内衬和规范构造最小壁厚后，按100mm整数倍向上取外径并复核；手动输入也按外径校核。SL/T 281-2020未给出固定外径系列，整百步长为本项目规则；其他管材继续按规范目录。结果页、Word和CSV保留完整过程。旧内径工况自动换为保持原净空的等效外径，历史结果待重算；最终承压与稳定性仍需结构验算。

无压管道对比现支持标准9档只读展示和自定义批量坡度，可保留输入并设置项目净空条件。已移除“无压输水能力对比”结果页，批量完成后通过日志中的文件路径查看成果。CSV计算结果、图表PDF、合并PDF和子图PNG四项输出保留；无压输入及后台计算继续供导出使用。专用CSV保留全部规格、底坡和工况，PDF/PNG展示可用底坡最多的最小规格，全无可用结果时展示扫描上限。详见[有压管道PRD](docs/PRD_有压管道批量计算_V1.0.md)。

有压管道结果页现按设计工况和加大工况并列展示流量、流速和水损，候选表同时列出两种流速，并标明经济类别按设计流速判断；关闭加大流量时显示单一设计工况，原选径规则保持不变。

## 主要功能

- 明渠、渡槽、隧洞、暗涵、倒虹吸、有压管道、充水渠、泄水渠与陡坡独立模块等水力计算；有压管道中的 PE 管可按 PE100/PE80 和 PN 推荐规范规格，球墨铸铁管、PCCP 管和玻璃钢夹砂管也可按选定产品目录推荐公称尺寸并换算或采用名义水力内径；其中球墨铸铁管按用户指定采用GB/T 13295-2026。
- 表格化批量输入，支持 Excel 导入、示例数据、模板、工程文件保存；结构形式列填写 `充水渠`、`泄水渠`、`陡坡`、`泄槽`、`陡槽`、`泄水渠与陡坡` 时统一按 `泄水渠与陡坡` 专项类型传参，DXF 建筑物名称行保留用户原始填写名。
- 水面线表、渐变段、连续承压线路、压力管道特性表等联动计算；表3中的充水渠/泄水渠/陡坡连续链由适配层按底坡变化切成固定底坡子段，再逐段调用泄水渠与陡坡专项内核。
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

表3充水渠变坡专项链回归：

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:hypothesispytest tests/test_batch_qiyi_fill_channel_regression.py tests/test_water_profile_spillway_steep_chute_unit.py tests/test_batch_import_dimension_preserve_unit.py -q --basetemp=.pytest_tmp\spillway-chain-target
```

七一水库充水渠真实 Excel 与“导出全部DXF”回归：

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:hypothesispytest tests/test_batch_qiyi_fill_channel_regression.py tests/test_water_profile_combined_dxf_unit.py -q --basetemp=.pytest_tmp\qiyi-dxf
```

## 打包与发版

本地打包：

```powershell
.\.venv\Scripts\python.exe tools\build.py
```

构建脚本会自动从 PyInstaller 子进程的 `PATH` 中排除 Codex 自带的 PDF、图片等原生依赖目录，避免把开发工具附带的 ICU、UCRT 等 DLL 误装进正式软件包；同时通过最早期运行钩子关闭 Python `platform` 的 WMI 查询，防止程序在主窗口创建前无界面卡死。Qt WebEngine 标准模式如被 Windows 拒绝多进程通信，启动编排会在父进程尚未导入 WebEngine 时自动切换到单进程兼容模式；主窗口只先创建首屏模块，其余模块在首次点击时加载。启动期临时窗口不得触发应用隐式退出，只有用户真正关闭主窗口时才结束进程。发包前必须从最终 ZIP 重新解压，并以“实际出现可响应主窗口”为启动验收标准，不能只确认进程仍在运行。

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
| `calc_渠系计算算法内核/pe_pipe_catalog.py` | GB/T 13663.2 PE 管离散规格目录及 PE 牌号、PN、SDR 查询 |
| `calc_渠系计算算法内核/pipe_product_catalog.py` | 球墨铸铁管、PCCP 管和玻璃钢夹砂管离散产品规格目录、标准元数据及名义水力内径换算 |
| `app_渠系计算前端/spillway_steep_chute/` | 泄水渠与陡坡正式模块界面、图表和导出 |
| `推求水面线/` | 水面线、渐变段、表3正式结构类型、充水渠专项链分段调度和连续承压链路 |
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

- 2026-09-05：无压对比改版复用本项目圆管曼宁模型、Qt输入框/网格/表格和Matplotlib图表；已有搜索记录，未引入外部界面框架或新依赖。新回归见`tests/test_unpressurized_comparison.py`和`tests/test_unpressurized_controls.py`。

- 2026-09-05：钢管按用户提供的SL/T 281-2020本地PDF第51页（印刷44页）核对第8.1.1、8.1.2条，接入构造最小壁厚；[全国标准信息公共服务平台](https://std.samr.gov.cn/hb/search/stdHBDetailed?id=D02D254C62E10D3BE05397BE0A0A60C1)用于标准信息核对。复用本项目已有候选、水力计算和结果公式组件，已有方案搜索记录，未重复搜索外部代码。规范PDF和OCR已分别归档钢管类别，PRD V2.13.10记录当前范围。用户随后明确要求先求最小水力内径再补壁厚上取外径，已复核本规范第3.1.3条不提供固定外径系列，100mm步长按用户指定采用；复用现有水力内核和公式渲染组件。

- 2026-05-10：为 GitHub/Gitee 双下载源核对 Gitee 官方 OpenAPI Release 与附件上传接口；未重复搜索 skills.sh 或 GitHub 外部方案。
- 2026-05-12：泄水渠与陡坡模块按本地 PRD、教材 OCR 和项目既有明渠内核完成第一版与第二版实现；README 已有搜索记录，因此未重复访问 skills.sh 或 GitHub 搜索外部方案。
- 2026-09-04：PE 管产品规格选型依据引用调研、本地 GB/T 13663.1-2017、GB/T 13663.2-2018 与 GB/T 20203-2017 资料完成；README 已有搜索记录，因此未重复访问 skills.sh 或 GitHub 搜索外部实现。
- 2026-09-05：按用户指定，将现归档于 `docs/规范资料/Markdown/球墨铸铁管/` 的本地OCR及 `docs/规范资料/PDF/球墨铸铁管/` 对应PDF的 GB/T 13295-2026 表16、表C.1作为球墨铸铁管运行目录真源，开放32档DN与7个C等级的表列组合，删除新选型中的K等级。配套内衬采用GB/T 17457-2019，厚度由中国铸造协会公开标准的对应引述交叉核验；国家标准平台确认配套标准状态。2027-03-01实施日保留说明，但按本项目选择提前采用新版。PCCP仍配套SL 702-2015与GB/T 19685-2017，FRPM仍按GB/T 21238-2016；已有搜索记录，未重复搜索外部代码实现。

## 已完成功能与待办

- 已完成：明渠、渡槽、隧洞、暗涵、倒虹吸、有压管道和表3水面线的主要计算与导出链路。
- 已完成：有压管道 PE100/PE80 按 PN 映射 SDR，逐表选取规范公称外径和壁厚，以名义内径统一完成水力计算，并在单次结果、Word 与批量 CSV 中保留可用于采购造价的完整规格。
- 已完成：有压管道球墨铸铁管按 `DE - 2×(壁厚 + 内衬)` 换算名义内径，PCCPL/PCCPE 与历史摩阻预设分离，玻璃钢夹砂管以内径基准系列自动推荐；新项目默认使用产品目录，旧项目继续保留原水力内径语义。普通钢筋混凝土管未纳入本次有压管道目录。
- 已完成：表3沿程摩阻长度统一采用完整 MC—MC 水流长度，仅扣除单列渐变段；弧段普通摩阻与弯道二次流附加损失分项累计，公式详情保留半弧长核查信息但不再扣减。
- 已完成：泄水渠与陡坡第二版正式模块，支持矩形/梯形陡槽、熊启钧教学算例、新手/专业模式、三种水面线模式、水面线型识别、上下游衔接、掺气侧墙、水跃消能、出口整流、多流量控制、项目保存恢复、纵断面图和文档/表格导出。
- 已完成：表1/表3中 `充水渠 / 泄水渠 / 陡坡 / 泄槽 / 陡槽 / 泄水渠与陡坡` 的结构形式别名归一；批量页只传参，表3按连续专项链调用泄水渠与陡坡内核，导出全部 DXF 时建筑物名称行保留用户原始填写名。
- 已完成：七一水库充水渠真实 Excel 回归，覆盖末尾 4 行专项导入、`100 / 10 / 24.5` 变坡分段、同坡 IP 合并、表3水面线和可打开的“导出全部DXF”文件。
- 已完成：修复 V1.3.9 冻结包中水面线核心与同名顶层 `core` 的加载冲突；“插入渐变段”等入口改用完整包名，构建时收集整个 `推求水面线` 包，并保留真实异常、可复制详情和本机日志作为故障兜底。最终冻结版已通过用户真实点击验证。
- 已完成：软件授权机器码升级为“系统标识 + 实体硬件”组合指纹，可区分使用同一 Windows 镜像的不同电脑；旧机器码继续作为兼容候选，现有授权升级后无需重新申请。
- 待办：泄水渠与陡坡专项 DXF 成果图、扩散陡槽、多级消能、消力槛式和综合式消力池。

## 当前状态

- 当前版本号：`1.3.11`
- 当前主分支：`master`
- 当前更新策略：GitHub 完整包 + GitHub/Gitee 补丁包备用源
