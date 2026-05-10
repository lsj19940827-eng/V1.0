# V1.0 渠系计算工具

## 项目功能简介

这是一个本地桌面计算工具，用来处理渠系纵断面、水面线、倒虹吸、有压管道、土石方等工程计算与导出。
当前版本的明渠模块已经补齐 `复式梯形` 断面，支持在明渠设计面板中直接输入 `m1 / B1 / m2 / B2 / m3 / h1` 六个固定参数完成计算，并把同一断面同步带到批量计算和推求水面线兼容链路。
当前版本的隧洞模块已经完整补齐 `平底圆形` 断面：单断面页可直接输入 `直径 D + 平底宽 B` 计算，表1批量、共享结果、表3导入复算、DXF/Word/TXT、`xx管` 隧洞摘要和断面汇总都会同步识别 `D / B / H_total`；表3继续只允许来源带入，不允许手工新建该类型。
当前版本的 `隧洞-圆拱直墙型` 支持 `底宽 B + 直墙高度 H直 + 圆心角 θ`：`H直` 留空时沿用自动搜索并说明推导公式，填写时固定几何并同步到单项、表1批量、Excel 模板、表3和导出；隧洞设计面板里还提供“按净空反推尺寸”弹窗，可按 `Q加大 / 目标净空比例 / H/B / θ` 反推当前工况可采用的 `B、H_total、H直`。
当前版本的明渠、渡槽、隧洞、暗涵设计面板统一新增“工况对比”：完成计算后，右侧会用“水力结果对比表 + 结构尺寸对比表”横向汇总成功工况；隧洞原有单表也已拆成双表，周长和断面积继续按完整洞身几何口径统计。
当前版本的 DXF 中文文字宽度因子默认统一为 `0.7`；四类设计面板的单工况和多工况 DXF 都会在断面图下方追加两张同口径对比表，表头里的流量、面积单位使用 CAD MTEXT 上标控制码显示为 `m³/s`、`m²`，避免单位乱码和文字压出单元格。
当前版本已把“矩形暗涵设计”升级为“暗涵设计”家族：标准类型为 `暗涵-矩形` 与 `暗涵-圆拱直墙型`，旧 `矩形暗涵 / 矩形暗渠 / 暗渠` 继续兼容到 `暗涵-矩形`；圆拱直墙型暗涵也支持可选 `H直`，留空自动推导，填写时固定几何，但仍走暗涵净空、表1/表3、渐变段和导出口径，不走隧洞规则。
当前仓库重点包含表3水面线计算、渐变段联动、倒虹吸/有压管道结果回写，以及连续承压线路的“整线纵断面 + 中心线高程导出 + 整线弹窗”规则。
当前版本已把有压管道弹窗里的水击验算收口为“先判别水击类型并形成最高/最低压力水头线，再分别做承压和负压校核”：系统把连续有压段视为一条串联管线，`Ts` 表示末端阀门启闭时间；未免验算时按等价 `L / am / vm` 判别直接水击、一相水击和末相水击，形成 `Hmax / Hmin`。默认允许压力为 `1.0 MPa`，换算为 `101.9368m` 允许压力水头；承压按管底 `Hmax - Zc + D/2` 校核，负压/满管按管顶 `Hmin - Zc - D/2` 校核。水击波速按 GB/T 公式引入管材系数 `cp`，钢筋混凝土管和 PCCP 管有 `a0` 时按公式折算，未填 `a0` 时按 `cp=1` 简化计算并提示。沿线采样只是检查整条管线各处承压或管顶负压风险，不表示每个采样点都有阀门；结果只在弹窗里并列展示和保存，不参与表3主水位、水头损失和累计损失递推。
水锤验算里的 `v0` 现在跟随“考虑加大流量”开关自动取值：勾选时采用 `Q加大/A`，未勾选时采用 `Q设计/A`；历史保存的 `v0` 只在缺少有效管径或流量时作为兜底。
表3基础设置区里的“设计流量 / 加大流量”现已收口为共享当前流量段的只读查看组：主界面默认只显示当前段（默认第一段）的名称和值，不再展示整串逗号文本，也不再提供“编辑全部”入口；需要改值时，回原始 Excel 来源处理。
当前口径下，主界面这两个流量字段只负责查看和切换当前流量段；当上游来源刷新设计流量时，系统仍会按最新设计流量整体重算全部加大流量。批量同步后，当前流量段会回到第一段；项目重开后主界面也默认回到第一段显示。
现在如果确实需要手工指定某一段“Q加大”，唯一入口是导入 Excel 模板 `导入模板` 页第 1 行右侧的 `J1` 单元格；按流量段顺序用逗号填写，例如 `5.5,,7.25` 表示第 1 段和第 3 段手工指定，第 2 段继续按自动比例。
明渠、渡槽、隧洞、暗涵、倒虹吸、有压管道这 6 个设计面板现在统一支持“按比例 / 按Q加大”二选一输入：保留原“考虑加大流量”开关，默认仍按比例；`按比例` 允许留空并继续自动查表；切到“按Q加大”后，输入的是加大后的总流量，且必须严格大于设计流量。旧工程仍按原比例方式打开；关闭开关只隐藏这组输入，不会清掉上一次内容。结果页、TXT、Word、DXF 会同时写清输入方式、用户输入值和系统换算值。
明渠、渡槽、隧洞、暗涵的计算结果详情顶部现在会按工况显示“重点结果汇总”，先列出设计/加大水深流速、净空或超高、结构关键尺寸和简短校核状态；多工况仍保持每个工况独立汇总。Word 报告也会在这四类面板的每个工况计算过程前插入同口径汇总表；有压管道继续保持原有结果摘要，不纳入本次调整。
明渠、渡槽、隧洞、暗涵的界面断面图现在统一走共享绘图底座：断面几何由 `section_shapes.py` 适配，matplotlib 绘制由 `section_plotting.py` 统一完成；只有 1 个成功工况时统一显示单图并叠加加大水位，多工况按每个成功工况一个小图显示，并通过默认 2 列、窄窗口 1 列、断面图页内部滚动和双击小图弹出大图来保持标注可读；切到断面图页时会按真实可视宽度重排，避免宽屏误退单列；计算内核、DXF 和 Word 规则保持原口径。
渡槽现已支持可选“拉杆高度”：该值表示拉杆自身尺寸高度，程序按拉杆顶与槽顶齐平处理；`H` 作为含拉杆的槽身总高参与深宽比。有拉杆时，设计流量既要满足槽顶规范超高，也要满足设计水面距拉杆底 ≥ 0.10m；加大流量 `Fb` 按水面到拉杆底的加大有效超高校核。单项、批量 Excel、结果汇总、断面图和 DXF 同步显示设计拉杆底净距与加大有效超高；未启用加大流量时，同步隐藏加大工况及加大有效超高。
当前版本的倒虹吸面板已把 `D` 行收口为“当前输入下的实时结果”：只要 `Q / v / N` 可算就立即显示；普通模式显示 `D设计 + D理论`，多管并联会同时说明“每管Q”；指定管径生效后改为“采用D + 实际流速”，拟定流速框同步切成灰色只读并显示反算流速，取消指定后恢复勾选前的拟定流速和确认态；弯管 `R/D0` 查表统一使用当前实际采用管径，理论管径只作为设计参考展示；工况确认态按工况在本次运行内单独记忆，重启后清空。
当前版本已把倒虹吸弯管/折管的“手工局部系数”真正接入执行计算：平面与纵断面局部损失不再合并成 3D 复合弯道，而是按来源分别计算后相加；平面或纵断面里能一一对应到单个弯/折段时，会按手工值参与计算；旧项目在唯一可恢复时会自动补回 `source_ip_index / source_long_node_index`，无法唯一恢复时会回退自动值并说明原因；详细过程会同时写出自动值、最终采用值、沿程长度来源，以及平面/纵断面/通用构件的局部损失合计。
当前版本的有压管道水损也统一为“平面 + 纵断面独立叠加”：平面弯头/折管、纵断面竖向弯折各自计算局部损失后相加；沿程损失只算一次，有有效纵断面实长时优先采用，否则回退平面点长度；通用构件局部损失可单独传入，进出口渐变段仍只各算一次。旧的空间合并工具保留给诊断和历史兼容，不再作为有压管道或倒虹吸水损主路径。
当前版本也把倒虹吸的两套系数彻底分开了：上方 `ξ₁ / ξ₂` 继续只表示进口、出口渐变段系数，结构段表里的进水口/出水口系数则作为构件局部损失并入 `ΔZ2`；总落差 `L.1.6` 统一按 `ΔZ = ΔZ1 + ΔZ2 - ΔZ3` 执行和展示。
当前版本已把倒虹吸纵断面大图的点位语义收口：弯管统一显示“两绿一橙”（弯前、弯后两个绿点 + 圆弧中点橙点），折管只显示折点橙点；绿点只写高程，橙点统一写角度，折管橙点额外带折点高程，避免把普通节点和转弯本体混在一起。
当前版本里，`xx管` 纵断面已经把“画线”和“取值”分开：导入时会把用户选中的原始纵断面多段线保存到 route 级 `raw_profile_polyline`，导出时 `centerline_draw_segments` 直接按这条原线裁切后出图；`profile_breakpoint_records` 继续只负责工程折点接口和覆盖判断；当前表格里的“管中心线高程（米）”仍由 `centerline_records` 在平面桩号位置取值。工程折点指原始轴线上真正用于分段、转折和校验的点，不拿普通采样点充数。
连续承压链里的命名 `有压管道 / 定向钻 / 顶管` 现在统一按逐行正式计损：中间命名承压段也会把每一行的承压损失显示到表3，并直接参与总损失、累计损失和水位递推；父命名组继续只保留在有压管道窗口里做汇总，不再参与表3重复累计。
有压管道结果弹窗现在把“正式计入表3/累计水损”的逐段值和“仅供复核”的整组参考值分开展示；顶部统计、连续链总览、单条详情和回写按钮都只把正式逐段值作为最终口径。
对于这类已经锁定的逐行承压行，表3列38仍保持只读；如果需要人工采用值，现在直接双击列38详情，在弹窗底部填写“本行采用值”即可，保存后会联动刷新总损失、累计损失和后续水位，恢复自动计算也走同一入口。
这条统一口径同时覆盖 `xx渠` 连续承压场景，以及所有 `xx管`（`总干管 / 分干管 / 干管 / 支管 / 分支管`）里的连续承压链，但只作用于真正进入连续承压链的承压类成员。
xx管 现在已经支持“有压管道 / 定向钻 / 顶管”整线里夹带隧洞：系统会按有压连续段拆整线卡，每张卡只覆盖自己的非隧洞段；像九龙右支管这种“前隧洞 + 后续一路有压”的场景只需导入 1 次，像蒲家湾支管这种“前半段有压 + 中间隧洞 + 后半段有压”的场景会拆成 2 次导入。
有压整线现在统一按“有压连续段数”决定要导入几次纵断面 DXF：前置无压隧洞和尾置无压隧洞都不再单独占一次，只有中间无压隧洞把前后两段 `有压管道 / 定向钻 / 顶管` 切开时，才会新增一次导入。
xx管 夹带隧洞的导出口径已经收口为“按结构拆成上下两张表”：上方普通渠道表继续跟随当前 `7/扩展项` 配置，承接隧洞和其他非 `xx管` 项；下方 `xx管` 表只保留 `有压管道 / 定向钻 / 顶管`，继续使用固定 5 项表头。隧洞参数统一只认表1手填或 Excel 导入的现有值，弹窗只做只读摘要和缺项提示，不再新增单独录入口；圆拱直墙型隧洞读取 `B / H直 / θ`，`H_total` 为推导值，不再把总高 `H` 当作输入。
有压管道窗口现在改成按“连续承压整线”判断：`xx管` 继续支持整线卡；`xx渠` 只有在末端或跨流量段形成连续承压线时才显示整线卡。底层按整线管理，但压力管道特性表、统计摘要和结果回写继续按原来的分段和流量段表达。
支渠连续承压链现在只从首个真正的有压段开始，前置隧洞不会再被误并进整线卡、route 起点和导入锚点；`xx管` 这边也同步改成按有压连续段决定整线卡数量。
支渠连续承压链里的前后同名普通有压管道，现在不会再被批量计算入口误判成必须改名；只有中间被明渠、闸、倒虹吸、暗涵等真正断开时，才继续按重名拦截。
同名隧洞如果只是被分水闸、节制闸、泄水闸、退水闸或分水口这类闸点隔开，现在也会继续按同一条隧洞处理，不会再误报成重名建筑物。
命名有压段现在也改成按“连续出现的同名段”建身份；表1导入到表3时会补齐承压行稳定身份，这样“前段普通有压 + 中间顶管/定向钻 + 后段同名普通有压”会拆成独立子段，导出和回写优先按真实身份匹配。
赛金支渠这类连续承压链现在补上了“起点前缀段 + 整线完成状态”口径：如果链首普通有压到下一段定向钻/顶管/隧洞进口之间存在真实距离，就按前缀段计入沿程损失，并写回下一段特殊承压建筑的进口行；只有拿不到有效长度时才退回起点锚点。执行计算前也会按真实应写回成员判断，不再误报“还没做有压计算”；同一条末尾连续承压尾段里的整组父卡只保留窗口汇总，不再和逐行正式结果抢同一口径。
赛金支渠连续承压链现在进一步收口为“父组只做汇总、子成员各算各的”：支渠链里的命名 `有压管道 / 定向钻 / 顶管` 只要真正进入连续承压链，就统一拆成逐行正式成员；父组继续保留原 `rows...` 身份做窗口汇总，中间普通段只会显示自己的结果或自己的缺失诊断，不会再挂到前缀段失败文案。
连续承压链成员现在也彻底分开了“界面展示名”和“底层校验标签”：界面仍可显示“前缀段 / 前段 / 中段N / 后段”，但底层逐段小分组始终只保留基础名称；如果某个中段真的失败，界面会把失败抬头改成这个中段自己的名字，不会再借到前缀段。
纵断面 DXF 导入不再盲取文件里的首条多段线，而是按图层名、坐标量级和 X 向展开长度自动优选；如果前两名候选过于接近，导入前会先弹一次确认。若导入节点的高程绝对值达到 `10000m`，系统会判断为疑似平面坐标 Y 值并阻止保存，要求重新导入 `X=桩号、Y=真实高程` 的纵断面 DXF。
连续承压 `xx渠` 的纵断面导出现在也复用 `xx管` 固定 5 项表头；如果还没导入或没完全覆盖纵断面轴线 DXF，中心高程会直接留空导出，并在软件里提示回表3补齐后重导。
普通渠道表继续按当前 `7/扩展项` 配置输出；当图2里同时存在普通渠道段和 `xx管` 段时，导出会按结构拆成上下两张表，TXT 导出保持原样。
连续承压支管如果已经导入了整线纵断面 DXF，但某个普通子段缓存只剩 1 个点，导出会自动回退整线纵断面，不会再因为这类单点占位数据误报失败。
有压管道弹窗里导入或清空整线纵断面后，现在会立刻同步到主页面导出读取的持久层，不用再靠“开始计算”这一步才生效。
双桥支管这类连续承压支管在导出时，如果同桩号节点合并后代表节点换了身份，系统会继续用同桩号节点组里的稳定 identity 回退匹配整线纵断面，不再把“identity 没对上”误说成“没导入 DXF”。
连续承压整线现在正式拆成 `route + segment` 两层模型：`route` 管整线范围、导入状态和整线纵断面，`segment` 管每一段的正式结果、DXF 名称和子段纵断面；这样赛金支渠这类“普通渠道 + 末尾连续承压”不再靠名称补丁维持。
支渠连续承压成员现在统一使用 `flow{流量段}-row{行号}` 新身份；旧 `rowsxx` 记录不再继续生成，保存时也会把同一整线范围内的旧快照一起清掉，避免前缀段再落回旧空记录。
末尾连续承压的上下分表现在也有了单独规划器：是否拆成“上方渠道表 + 下方有压表”统一按整张表判断，不再由不同导出入口各自猜一次；一旦进入真正的承压尾段，后面的普通有压、定向钻、顶管进入下方 5 项有压表，隧洞和暗涵继续留在上方普通渠道表。
连续承压段的 DXF 建筑物名称现在与软件展示名彻底拆开：DXF 只显示基础名称并按整段居中，软件里仍可保留“前缀段 / 前段 / 后段”等提示，赛金支渠这类结果会稳定显示为“苟家湾 / 大石包 / 苟家湾”。
压力管道特性表里的隧洞统计现在也按渠道级别分流：`xx渠` 只有在同一流量段里被 `有压管道 / 定向钻 / 顶管` 前后夹住的中间隧洞，才会计入主长度、隧洞座数和长度，前置隧洞和末尾隧洞都不再统计；`xx管` 继续按原有整线口径统计，若前段是无压隧洞，则主长度还会把该隧洞及其与首段有压结构之间的空档一起补回。
普通纵断面与 xx管 现在都支持单独控制导出桩号小数位：普通模式默认 2 位，且会同步影响普通纵断面、IP 表、合并 DXF 里的 IP 表和 bzzh2 这类导出结果；xx管 继续只影响自己的纵断面桩号。
表3顶部“转弯半径”现在是一个统一应用入口：导入后默认保留每一行自己的半径，只有点击“应用”才会批量覆盖真实导入行。
应用内自动更新现在按“先验包、再安装、补丁落地后再验收”收口：`V1.3.0` 及以上版本优先补丁；正式 `version.json` 仍由 GitHub Gist 提供，但发布包会同步上传到 GitHub Release 和 Gitee Release，客户端下载时先用主地址，失败或校验不通过时自动尝试 Gitee 镜像地址；补丁下载、校验或安装失败时，安装助手会自动改用完整安装包继续更新，完整包同样支持镜像地址兜底；只有完整包也失败时才显示失败页。补丁发布不再使用固定 64MB 拦截，而是要求补丁明显小于完整包，并继续限制删除文件数和总覆盖文件数；`siphon_autosave.json`、`data/autosave/` 和 `*_autosave.qxproj` 这类运行时文件不再参与补丁严格哈希校验，成功安装后也会保留；安装前仍会自动清理旧 `_update_sessions` 残留，窗口会继续显示“正在清理上次失败残留 / 正在校验更新包完整性 / 正在检查写入权限 / 正在统计安装目录大小 / 正在解压完整安装包或补丁包 / 正在校验补丁适用性（x/y）”这些细分状态，补丁大文件哈希时也会显示单文件百分比；如果旧残留清不掉，窗口会直接提示先关闭软件，仍失败再重启电脑。

## 技术架构

- 前端界面：`PySide6`，主要代码在 `app_渠系计算前端/`。
- 启动兼容保护：`app_渠系计算前端/bootstrap.py` 会在主窗口装配前禁用 Python `platform` 的 Windows WMI 查询快速路径，避免 `pandas`、`qfluentwidgets` 等库在导入阶段卡住导致 VS Code 运行 `main.py` 后窗口不出现。
- DXF 共享导出：`app_渠系计算前端/dxf_common.py` 负责断面图层、字体、标注样式和文字宽度因子，当前中文文字样式默认宽度因子为 `0.7`。
- 文档转换工具：`tools/document_to_markdown.py` 可把 Word、PDF、Excel 转成 Markdown，依赖 `python-docx / docx2txt / pdfplumber / pandas`。
- 表3基础设置：设计流量和加大流量在界面上改为共享当前流量段的只读查看组，主界面只负责查看和切换，不再直接编辑；保存时继续兼容旧文本字段与 `ProjectSettings` 里的结构化列表，项目重开默认回到第一段显示。
- 计算内核：Python 纯计算模块，主要代码在 `推求水面线/`、`calc_渠系计算算法内核/`。
- 有压管道结果展示：`推求水面线/utils/pressure_pipe_result_helpers.py` 负责把记录拆成正式计入、参考结果和失败记录；`app_渠系计算前端/water_profile/panel.py` 负责在结果弹窗中分区展示，并只把正式计入记录回写表3。
- 重点结果汇总：`app_渠系计算前端/result_summary.py` 负责把明渠、渡槽、隧洞、暗涵的计算结果整理成界面顶部汇总卡和 Word 汇总表；四个面板复用同一套数据口径，有压管道不走这个模块。
- 工况对比框架：`app_渠系计算前端/section_comparison.py` 负责四类设计面板的双表列定义、数字格式、成功工况过滤、复制到 Excel、DXF 附表和 Word 对比表输出；各面板只提供自己的字段映射。
- 界面断面图绘制底座：`app_渠系计算前端/section_shapes.py` 负责明渠、渡槽、隧洞、暗涵的界面断面几何适配，`app_渠系计算前端/section_plotting.py` 负责统一 matplotlib 轮廓、水域、水位线、尺寸标注、标题、网格和视图范围，`app_渠系计算前端/section_plot_layout.py` 负责多工况默认 2 列、窄窗口 1 列、滚动承载、切页真实宽度重排和双击大图；DXF 与 Word 导出仍按各自原入口处理。
- 明渠断面：`calc_渠系计算算法内核/明渠设计.py` 统一承接梯形、复式梯形、矩形、圆形、U 形；`app_渠系计算前端/open_channel/` 负责单断面设计页、工况对比与 DXF/Word 导出；`app_渠系计算前端/batch/panel.py` 负责批量页与 Excel。
- 渡槽断面：`calc_渠系计算算法内核/渡槽设计.py` 负责 U 形和矩形渡槽计算，支持可选 `tie_rod_height`；`app_渠系计算前端/aqueduct/` 负责单项输入、多工况、工况对比、结果说明、断面图和 DXF 导出；`app_渠系计算前端/batch/panel.py` 负责批量 Excel 列和共享结果。
- 隧洞断面：`calc_渠系计算算法内核/隧洞设计.py` 统一承接圆形、平底圆形、圆拱直墙型与马蹄形；圆拱直墙型支持可选 `manual_H_straight`，留空自动推导，填写后按固定 `H直` 核算，并提供按加大流量目标净空面积比反推 `B / H直 / θ` 的独立内核函数；`app_渠系计算前端/tunnel/geometry.py` 作为共享几何真源，给隧洞面板绘图、DXF、批量结果和表3复算共用；`app_渠系计算前端/tunnel/comparison.py` 负责把多工况结果整理成双表对比行。
- 暗涵断面：既有 `calc_渠系计算算法内核/矩形暗涵设计.py` 与 `app_渠系计算前端/culvert/` 继续承接 `暗涵-矩形`；`暗涵-圆拱直墙型` 复用圆拱几何、分叉暗涵规则，支持可选 `manual_H_straight`，并保留 `B / H_straight / H_total / theta_deg` 进入共享结果、工况对比、表3和导出链路。
- 专项模块：`倒虹吸水力计算系统/`、`有压管道/` 提供专项计算能力。
- 倒虹吸交互：`app_渠系计算前端/siphon/panel.py` 统一负责 `D` 实时显示、指定管径生效后的实际流速反算、取消指定后的拟定流速恢复、工况内确认态隔离，以及倒虹吸手工局部系数的保存/恢复、来源索引回填、未采用提示；现在界面上方 `ξ₁ / ξ₂` 明确只表示渐变段系数，结构段表里的进水口/出水口系数只作为构件局部损失进入 `ΔZ2`；旧项目在唯一可恢复时会自动补回 `source_ip_index / source_long_node_index`，无法唯一恢复时会回退自动值并说明原因；`app_渠系计算前端/siphon/multi_siphon_dialog.py` 与 `推求水面线/managers/siphon_manager.py` 负责单页/多页配置保存与本次运行内的自动确认衔接。
- 加大流量输入：`app_渠系计算前端/increase_input_helper.py` 统一负责“按比例 / 按Q加大”的换算、空值规则、灰色提示文案和结果摘要；6 个设计面板都复用这套 helper，并继续把内核输入收口到原有比例参数。
- 自动化验证：`pytest`，测试文件集中在 `tests/`，其中 xx管 整线纵断面会同时覆盖界面、持久化、计算和导出链路。
- 更新链路：`repo_config.py`、`updater.py`、`update_helper.py`、`app_渠系计算前端/update_dialog.py`、`update_artifact_rules.py`、`tools/patch_policy.py`、`tools/build.py`、`tools/release.py`、`tools/release_snapshot.py` 共同负责版本检查、补丁/全量选择、GitHub/Gitee 下载镜像、下载包 checksum、运行时文件排除、旧会话残留清理、补丁落地后目标验收、独立安装窗口、补丁兜底和正式发版；其中 `tools/release.py` 会在正式发版时同步创建 GitHub Release 和 Gitee Release，并把 Gitee 附件地址写入 `download_url_mirrors / patch_url_mirrors`；`tools/build.py` 现在还会在打包前按分组校验关键依赖，并显式收集 `latex2mathml` 这类 Word 导出运行时数据文件，避免安装包启动时因缺资源直接退出；`tools/patch_policy.py` 统一约束补丁大小和覆盖范围，`tools/backfill_patch_release.py` 与 `tools/disable_patch_release.py` 则分别负责“基于快照回补 patch”和“临时撤下高风险 patch 字段”。
- 导出精度：普通模式导出桩号使用 `station_decimals`，xx管 导出桩号使用 `xxpipe_station_decimals`；两者都在导出链路单独格式化，不改主界面的通用桩号显示函数。
- mixed route 持久化：`PressurePipeManager` 现同时保存 route 级 `longitudinal_nodes`、`raw_profile_polyline` 与 `profile_segments`，用来承接“原线直出 + 平面桩号采样 + 工程折点接口”的混合整线导出。
- 水击验算：`推求水面线/core/pressure_pipe_calc.py` 现按 GB/T 20203-2017 波速公式 `a = 1425 / sqrt(1 + (K / E) * (D / t) * cp)` 计算水击波速，默认 `K=2.06×10⁹ Pa`。钢管、铸铁管、球墨铸铁管、玻璃钢夹砂管、HDPE/PE、PVC/PVC-U 等按 `cp=1`；钢筋混凝土管、预应力钢筒混凝土管和 PCCP 管有 `a0` 时按 `cp=1/(1+0.95a0)` 自动折算，未填 `a0` 时按 `cp=1` 简化计算并在状态、步骤和导出备注中提示。整线水锤按末端阀门启闭理解，保留 `Ts >= 40L/a`（整线按 `40×Σ(Li/ai)`）免验算规则；未免验算时新增等价参数 `L=ΣLi`、`am=L/Σ(Li/ai)`、`vm=Σ(Li vi)/L`，用 `ρ=am vm/(2gH0)`、`σ=L vm/(gH0Ts)` 判别图 `1-3-3` 水击类型并形成 `Hmax / Hmin`。默认允许压力为 `1.0 MPa`，换算允许压力水头 `101.9368m`；承压按管底 `Hmax - Zc + D/2 <= h_allow` 校核，负压/满管按管顶 `Hmin - Zc - D/2 >= 0` 校核。直接水击和一相水击当前采用工程近似沿线分布，结果会明确标注。
- 水锤流速来源：单管和整线成员的 `v0` 由 `resolve_water_hammer_velocity()` 按当前工况解析；勾选“考虑加大流量”时用 `Q加大/A`，未勾选时用 `Q设计/A`，历史保存值只在无法自动计算时兜底，界面和 Excel 明细会记录流速来源与采用流量。
- 纵断面绘图与取值分离：`centerline_draw_segments` 只负责导入原线画线，`profile_breakpoint_records` 只负责工程折点接口和覆盖判断；当前表格文字仍继续走 `centerline_records`。
- 连续承压正式存储：`PressurePipeManager` 现在同时维护 `pipes / routes / segments` 三层数据；旧入口继续兼容，新导出与回读优先使用 `routes / segments`。
- 尾段逐行计损：`xx渠` 末尾连续承压中的命名有压段，会先拆成逐段成员，再统一按行回写和递推；窗口汇总仍保留整组结果。
- 连续承压快照保存：同一整线范围内的旧 `route / segment / pipe` 残留会在保存新结果前先清掉，避免新旧两套记录同时参与导出。
- 结构分表规划：`cad_tools.py` 统一按结构决定导出分表；上方普通渠道表继续跟随当前 `7/扩展项` 配置，下方 `xx管` 表只保留 `有压管道 / 定向钻 / 顶管`。
- 隧洞参数链路：隧洞参数正式来源只有表1/Excel；`PressurePipeManager` 只保留低成本兼容和补缺兜底，弹窗继续只做只读摘要；圆拱直墙型隧洞读取 `B / H直 / θ`，`H_total = H直 + H_arch` 为推导值。`暗涵-圆拱直墙型` 不走这条隧洞摘要链，必须按暗涵参数口径处理。

## 模板填写说明

- 需要手工指定“Q加大”时，只改导入 Excel 模板 `导入模板` 页第 1 行的 `J1` 单元格，不用去表3里找入口。
- `I1` 是说明标签，`J1` 是唯一输入格；按流量段顺序用逗号填写，例如 `5.5,,7.25`。
- 某一段留空时，程序会继续按自动比例生成加大流量，不会因为没填就卡住。
- 模板不再预铺 20 组横向列对；旧版“标签列 + 值列”的 Excel 仍可继续导入。
- 表3里这两个流量字段仍然只是查看当前段，不在这里直接改值。

## 本地运行方法

1. 若本地还没有虚拟环境，先执行 `python -m venv .venv`。
2. Windows 环境可直接运行 `install_deps.bat` 安装依赖；该脚本现在会覆盖 DXF、Word 导出、PDF/Word 转 Markdown 等常用功能所需依赖。
3. 启动程序使用 `D:\V1.0\.venv\Scripts\python.exe main.py`。

## 部署方法和命令

当前项目主要作为本地桌面工具使用，日常开发通常不做云端部署。
正式发版按仓库约定使用 `D:\V1.0\.venv\Scripts\python.exe tools/release.py`，也可通过 `发版工具.bat` 进入标准发版流程；正式打包和发版前会先校验 Word 导出依赖，并要求 `.env` 或环境变量同时提供 `GITHUB_TOKEN` 与 `GITEE_TOKEN`。发版成功后会额外在 `.release-snapshots/` 固化本次正式包、manifest 和 version.json；若线上 patch 需要临时撤下或事后回补，分别使用 `tools/disable_patch_release.py` 与 `tools/backfill_patch_release.py`。

## 测试方法和常用命令

- 运行针对性测试：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_external_head_loss_unit.py -q`
- 运行界面口径测试：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_loss_formula_dialog_unit.py tests/test_water_profile_loss_dialog_alignment_unit.py -q`
- 运行本次四类工况对比回归：`$env:PYTHONPATH='D:\V1.0;D:\V1.0\calc_渠系计算算法内核'; D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_tunnel_comparison_unit.py tests/test_tunnel_dxf_export_unit.py tests/test_open_channel_comparison_unit.py tests/test_aqueduct_comparison_unit.py tests/test_culvert_comparison_unit.py tests/test_section_comparison_output_unit.py tests/test_section_comparison_panel_wiring_unit.py tests/test_multi_case_dxf_export_unit.py tests/test_formula_renderer_result_pages_unit.py tests/test_result_summary_unit.py -q`
- 运行本次相关回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_external_head_loss_unit.py tests/test_pressure_pipe_loss_formula_dialog_unit.py tests/test_channel_level_options_unit.py tests/test_pressure_pipe_preprocessing_unit.py tests/test_water_profile_coord_precision_unit.py tests/test_water_profile_loss_dialog_alignment_unit.py tests/test_water_profile_transition_ready_unit.py -q`
- 运行“按Q加大输入”面板回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_increase_input_mode_panels_unit.py -q`
- 运行启动链路回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_webengine_diagnostics_unit.py -q`
- 运行回补 patch 相关回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_backfill_patch_release_unit.py tests/test_build_patch_floor_unit.py tests/test_updater_versioning_unit.py tests/test_updater_install_flow_unit.py tests/test_release_snapshot_unit.py -q`
- 运行本次窗口联动回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_extractor_fallback_unit.py tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_pressure_pipe_window_override_unit.py tests/test_external_head_loss_unit.py tests/test_pressure_pipe_loss_formula_dialog_unit.py tests/test_water_profile_coord_precision_unit.py tests/test_water_profile_loss_dialog_alignment_unit.py tests/test_water_profile_transition_ready_unit.py -q`
- 运行本次 xx管 整线回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_extractor_fallback_unit.py tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_pressure_pipe_export_longitudinal_nodes_unit.py tests/test_pressure_pipe_persistence_with_long_unit.py tests/test_pressure_pipe_longitudinal_utils_unit.py tests/test_pressure_pipe_spatial_calc_unit.py tests/test_xxpipe_export_context_unit.py tests/test_xxpipe_longitudinal_export_unit.py tests/test_xxpipe_axis_elevation_unit.py tests/test_water_profile_transition_ready_unit.py -q`
- 运行本次 xx管 弹窗与导出回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_water_profile_transition_ready_unit.py tests/test_pressure_pipe_export_longitudinal_nodes_unit.py tests/test_xxpipe_longitudinal_export_unit.py tests/test_xxpipe_axis_elevation_unit.py -q`
- 运行本次 xx管 夹带隧洞回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_water_profile_transition_ready_unit.py tests/test_water_profile_combined_dxf_unit.py tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_pressure_pipe_persistence_with_long_unit.py tests/test_pressure_pipe_export_longitudinal_nodes_unit.py tests/test_xxpipe_longitudinal_export_unit.py tests/test_xxpipe_axis_elevation_unit.py -q`
- 运行本次 xx管 隧洞水力核算模式回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_pressure_pipe_export_longitudinal_nodes_unit.py tests/test_pressure_pipe_persistence_with_long_unit.py tests/test_pressure_pipe_result_report_unit.py tests/test_water_profile_coord_precision_unit.py tests/test_xxpipe_longitudinal_export_unit.py -q`
- 运行本次连续承压 xx渠 导出回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_xxpipe_profile_rows_unit.py tests/test_xxpipe_longitudinal_export_unit.py tests/test_water_profile_combined_dxf_unit.py tests/test_pressurized_dxf_rules_unit.py -q`
- 运行本次末尾有压段分表回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_xxpipe_profile_rows_unit.py tests/test_xxpipe_longitudinal_export_unit.py tests/test_water_profile_combined_dxf_unit.py tests/test_pressurized_dxf_rules_unit.py -q`
- 运行本次本地分支收口回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressurized_dxf_rules_unit.py tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_pressure_pipe_export_longitudinal_nodes_unit.py tests/test_water_profile_combined_dxf_unit.py tests/test_xxpipe_export_context_unit.py -q`
- 运行本次赛金支渠重构回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_*unit.py tests/test_xxpipe_*unit.py tests/test_water_profile_combined_dxf_unit.py -q`
- 运行本次普通纵断面桩号精度回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_text_export_settings_dialog_ui_unit.py tests/test_water_profile_longitudinal_scale_unit.py tests/test_water_profile_ip_table_export_unit.py tests/test_water_profile_bzzh2_export_unit.py tests/test_water_profile_combined_dxf_unit.py tests/test_water_profile_longitudinal_dedup_unit.py tests/test_xxpipe_longitudinal_export_unit.py -q`
- 运行本次连续承压链回归：`$env:PYTHONPATH='D:\V1.0;D:\V1.0\calc_渠系计算算法内核'; D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_pressure_pipe_config_dialog_sizing_unit.py tests/test_pressure_pipe_chain_apply_unit.py tests/test_pressure_pipe_chain_extractor_unit.py tests/test_pressure_pipe_result_report_unit.py tests/test_pressure_pipe_extractor_fallback_unit.py tests/test_pressure_pipe_preprocessing_unit.py tests/test_external_head_loss_unit.py`
- 运行本次 xx渠 末尾逐行计损回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_chain_extractor_unit.py tests/test_pressure_pipe_chain_apply_unit.py tests/test_water_profile_transition_ready_unit.py tests/test_external_head_loss_unit.py tests/test_water_profile_loss_dialog_alignment_unit.py -q`
- 运行本次列38锁定行手动录入回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_loss_formula_dialog_unit.py tests/test_pressure_pipe_chain_apply_unit.py tests/test_pressure_pipe_window_override_unit.py -q`
- 运行本次连续承压整线回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_extractor_fallback_unit.py tests/test_pressure_pipe_chain_extractor_unit.py tests/test_water_profile_transition_ready_unit.py tests/test_pressurized_dxf_rules_unit.py tests/test_external_head_loss_unit.py tests/test_pressure_pipe_chain_apply_unit.py tests/test_pressure_pipe_window_override_unit.py tests/test_pressure_pipe_export_longitudinal_nodes_unit.py tests/test_pressure_pipe_persistence_with_long_unit.py tests/test_pressure_pipe_canvas_viewer_gui_unit.py -q`
- 运行本次三清支渠纵断面/链路回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_longitudinal_dxf_reverse_import_unit.py tests/test_pressure_pipe_chain_extractor_unit.py tests/test_pressure_pipe_extractor_fallback_unit.py tests/test_pressure_pipe_canvas_viewer_gui_unit.py -q`
- 运行本次同名连续承压链回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_batch_panel_dialog_parent_unit.py tests/test_pressure_pipe_chain_extractor_unit.py tests/test_water_profile_coord_precision_unit.py tests/test_pressure_pipe_export_results_unit.py -q`
- 运行本次赛金支渠连续承压链回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_extractor_fallback_unit.py tests/test_pressure_pipe_chain_extractor_unit.py tests/test_pressure_pipe_chain_apply_unit.py tests/test_pressure_pipe_result_report_unit.py tests/test_pressure_pipe_export_results_unit.py tests/test_pressure_pipe_canvas_viewer_gui_unit.py tests/test_water_profile_transition_ready_unit.py tests/test_xxpipe_longitudinal_export_unit.py -q`
- 运行本次“中段借到前缀失败”回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_chain_extractor_unit.py tests/test_pressure_pipe_chain_apply_unit.py tests/test_pressure_pipe_result_report_unit.py tests/test_external_head_loss_unit.py -q`
- 运行本次水击验算回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_pressure_pipe_water_hammer_core_unit.py tests/test_pressure_pipe_water_hammer_dialog_unit.py tests/test_pressure_pipe_water_hammer_velocity_unit.py tests/test_water_profile_transition_ready_unit.py -q`
- 运行更新链路回归：`$env:PYTEST_ADDOPTS='--basetemp=D:\V1.0\.pytest_tmp\update-regression'; D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_build_patch_floor_unit.py tests/test_updater_install_flow_unit.py tests/test_update_helper_unit.py tests/test_updater_versioning_unit.py tests/test_release_snapshot_unit.py -q`
- 运行 Gitee 双源更新回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_release_gitee_unit.py tests/test_updater_versioning_unit.py tests/test_updater_install_flow_unit.py tests/test_release_snapshot_unit.py -q --basetemp=D:\V1.0\.pytest_tmp\gitee-regression`
- 运行本次构建依赖回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_build_patch_floor_unit.py -q --basetemp=D:\V1.0\.pytest_tmp\build-plan`
- 运行本次复式梯形回归：`$env:PYTHONPATH='D:\V1.0;D:\V1.0\calc_渠系计算算法内核'; D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_open_channel_compound_trapezoid_kernel_unit.py tests/test_open_channel_compound_trapezoid_panel_unit.py tests/test_open_channel_compound_trapezoid_dxf_unit.py tests/test_batch_compound_trapezoid_unit.py tests/test_compound_trapezoid_type_support_unit.py tests/test_compound_trapezoid_shared_hydraulic_unit.py tests/test_water_profile_coord_precision_unit.py -q`
- 运行本次平底圆形隧洞收口回归：`$env:PYTHONPATH='D:\V1.0;D:\V1.0\calc_渠系计算算法内核'; D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_tunnel_flat_bottom_circular_kernel_unit.py tests/test_tunnel_flat_bottom_circular_shared_hydraulic_unit.py tests/test_tunnel_flat_bottom_circular_dxf_unit.py tests/test_tunnel_flat_bottom_circular_panel_batch_unit.py tests/test_tunnel_flat_bottom_circular_table3_xxpipe_unit.py tests/test_tunnel_flat_bottom_circle_section_summary_unit.py tests/test_tunnel_kernel.py tests/test_tunnel_dxf_export_unit.py tests/test_tunnel_panel_plot_unit.py tests/test_formula_renderer_result_pages_unit.py -q`
- 运行本次暗涵家族扩展回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_culvert_arch_kernel_unit.py tests/test_culvert_arch_shared_hydraulic_unit.py tests/test_culvert_arch_type_support_unit.py tests/test_culvert_arch_panel_batch_unit.py tests/test_transition_reference_culvert_unit.py tests/test_pressurized_dxf_rules_unit.py tests/test_xxpipe_longitudinal_export_unit.py tests/test_shared_data_manager_vmax_alias_unit.py tests/test_xxpipe_export_context_unit.py tests/test_xxpipe_mode_rules_unit.py tests/test_culvert_kernel.py -q`
- 运行本次暗涵圆拱直墙 H直 回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_culvert_arch_kernel_unit.py tests/test_culvert_arch_panel_batch_unit.py tests/test_culvert_arch_shared_hydraulic_unit.py tests/test_culvert_arch_table3_unit.py tests/test_clear_preserves_panel_inputs_unit.py tests/test_batch_import_dimension_preserve_unit.py -q`
- 运行本次隧洞圆拱直墙 H直 回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_tunnel_kernel.py tests/test_tunnel_arch_manual_wall_height_unit.py tests/test_tunnel_arch_wall_height_panel_batch_unit.py tests/test_clear_preserves_panel_inputs_unit.py tests/test_batch_import_dimension_preserve_unit.py tests/test_tunnel_flat_bottom_circular_panel_batch_unit.py tests/test_tunnel_flat_bottom_circular_shared_hydraulic_unit.py -q`
- 运行本次倒虹吸 D 显示与指定管径回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_siphon_d_display_override_unit.py tests/test_siphon_unified_auto_confirm.py tests/test_siphon_num_pipes_confirmation_level_unit.py -q`
- 运行本次倒虹吸手工局部系数回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_siphon_manual_xi_execution_regression_unit.py tests/test_siphon_plan_fold_coeff_regression_unit.py tests/test_siphon_num_pipes_confirmation_level_unit.py tests/test_spatial_merger.py -q`
- 运行本次倒虹吸纵断面点位语义回归：`D:\V1.0\.venv\Scripts\python.exe -m pytest tests/test_siphon_profile_marker_semantics_unit.py tests/test_siphon_canvas_viewer_gui_unit.py tests/test_siphon_arc_geometry_fidelity_unit.py -q`

## 搜索记录

- 2026-05-10：本次为正式发版新增 Gitee 镜像仓库和 GitHub/Gitee 双下载源；README 已有更新链路记录，继续复用仓库现有更新器、发版脚本和补丁安全策略，只联网核对 Gitee 官方 OpenAPI Release/附件上传接口，未重复执行 skills.sh 或 GitHub 外部方案搜索。
- 2026-05-08：本次优化明渠、渡槽、隧洞、暗涵多工况界面断面图清晰度，新增默认 2 列、窄窗口 1 列、滚动承载和双击大图；README 已有搜索记录，继续基于现有共享断面图底座和四类面板测试实现，未重复执行 skills.sh 或 GitHub 外部方案搜索。
- 2026-05-08：本次把明渠、渡槽、隧洞、暗涵的单工况界面断面图统一为“单图叠加加大水位”；README 已有搜索记录，继续基于现有共享断面图底座和四类面板测试实现，未重复执行 skills.sh 或 GitHub 外部方案搜索。
- 2026-05-07：本次把明渠、渡槽、隧洞、暗涵的界面断面图收口到共享几何与 matplotlib 绘图模块；README 已有搜索记录，继续基于仓库现有四类面板、隧洞几何 helper 和既有断面图测试实现，未重复执行 skills.sh 或 GitHub 外部方案搜索。
- 2026-04-30：本次为明渠、渡槽、隧洞、暗涵统一新增“工况对比”双表，并接入界面、DXF 和 Word；README 已有搜索记录，继续基于仓库现有隧洞对比、结果汇总和导出链路实现，未重复执行 skills.sh 或 GitHub 外部方案搜索。
- 2026-04-30：本次修复隧洞多工况 DXF 对比表文字溢出和上标单位乱码，README 已有搜索记录，继续基于仓库现有 DXF 字体样式和表格绘制逻辑实现，未重复执行 skills.sh 或 GitHub 外部方案搜索。
- 2026-04-30：本次为既有隧洞设计面板新增多工况参数对比与 DXF 附表，README 已有搜索记录，继续基于仓库现有隧洞面板、几何 helper 和多工况 DXF 导出实现，未重复执行 skills.sh 或 GitHub 外部方案搜索。
- 2026-04-30：本次为既有渡槽模块新增拉杆高度口径，README 已有搜索记录，继续基于仓库现有渡槽内核、单项面板、批量 Excel 和 DXF 导出实现，未重复执行 skills.sh 或 GitHub 外部方案搜索。
- 2026-04-30：本次为明渠、渡槽、隧洞、暗涵结果详情新增顶部“重点结果汇总”，README 已有搜索记录，继续基于仓库现有结果渲染、Word 导出和多工况导航实现，未重复执行 skills.sh 或 GitHub 外部方案搜索。
- 2026-04-28：本次按用户确认口径修正水锤验算 `v0` 的工况来源；勾选“考虑加大流量”时采用 `Q加大/A`，未勾选时采用 `Q设计/A`，未重复执行外部搜索。
- 2026-04-30：本次为 `隧洞-圆拱直墙型` 新增按加大流量净空比例反推尺寸弹窗；README 已有搜索记录，继续基于现有隧洞内核、面板和加大流量 helper 实现，未重复执行 skills.sh 或 GitHub 外部方案搜索。
- 2026-04-29：本次为既有 `隧洞-圆拱直墙型` 新增可选 `直墙高度 H直` 输入与文档口径同步；README 已有搜索记录，继续基于仓库现有隧洞内核、批量表1、共享结果、表3复算和 `xx管` 导出链路梳理，未重复执行 skills.sh 或 GitHub 外部方案搜索。
- 2026-04-30：本次为既有 `暗涵-圆拱直墙型` 增加可选 `直墙高度 H直` 输入；README 已有搜索记录，继续基于仓库现有隧洞 H直、暗涵、批量、共享结果和表3链路调整，未重复执行 skills.sh 或 GitHub 外部方案搜索。
- 2026-04-27：本次按用户提供的水锤验算判断口径，把整线水锤从旧“表3水位/管顶余量”改为先形成 `Hmax / Hmin`，再按管底承压、管顶负压校核；默认允许压力 `1.0MPa≈101.9368m`，未重复执行外部搜索。
- 2026-04-28：本次为 V1.3.4 发版收紧补丁范围，README 已有搜索记录，继续基于仓库现有更新器、补丁构建和发版脚本实现，未重复执行外部方案搜索。
- 2026-04-29：本次为 V1.3.1 升 V1.3.4 卡在补丁适用性校验的线上反馈，README 已有搜索记录，继续基于仓库现有更新器、补丁发布策略和发版脚本排查修复，未重复执行外部方案搜索。
- 2026-04-30：本次为既有 Excel 手工 `Q加大` 输入方式压缩，README 已有搜索记录，继续基于仓库现有批量导入和表3同步链路实现，未重复执行外部方案搜索。
- 2026-04-27：本次继续基于用户提供的 GB/T 20203-2017 5.1.7 OCR 文档，实现缓闭正水击“GB/T 式(21) + 线性启闭理论”双重取大，并把波速公式中的 `cp/a0` 管材系数接入程序，未重复执行外部搜索。
- 2026-04-27：本次按用户提供的 GB/T 20203-2017 5.1.7 OCR 文档和表6口径修正水击默认弹模，并实现 `Ts >= 40L/a` 免验算规则，未重复执行外部搜索。
- 2026-04-26：用户提供管材弹性模量表截图，红框标明玻璃钢复合管 `E=14.7×10⁹ Pa`；本次按该表把 `玻璃钢夹砂管` 水锤默认 `E` 调整为 `14.7×10⁹ Pa`，未重复执行外部搜索。
- 2026-04-25：本次为既有有压管道结果弹窗口径澄清，README 已有搜索记录，继续基于仓库现有正式/参考记录字段实现，未重复执行外部方案搜索。
- 2026-04-24：按用户要求联网核对玻璃钢夹砂管水锤弹性模量；天津市再生水管道工程技术规程给出玻璃纤维增强塑料夹砂管相关模量范围较宽，FRPM 管线探测手册给出纵向弹性模量参考值 `8728 MPa`，当时据此把 `玻璃钢夹砂管` 水锤默认 `E` 调整为 `8.728×10⁹ Pa`；后续以 2026-04-26 用户截图口径为准。
- 2026-04-18：本次为既有多流量段 Excel 模板与文档口径同步，README 已有搜索记录，继续基于已确定的导入模板方案更新说明，未重复执行外部方案搜索。
- 2026-04-17：本次为既有在线更新与正式发版链路加固，README 已有搜索记录，继续基于仓库现有更新器、补丁构建和发版脚本实现，未重复执行外部方案搜索。
- 2026-04-17：本次为既有 6 个设计面板统一支持“按比例 / 按Q加大”输入，README 已有搜索记录，继续基于仓库现有面板、多工况和导出链路实现，未重复执行外部方案搜索。
- 2026-04-16：本次为既有正式发版链路内补挂 `v1.3.0` 近版本 patch，README 已有搜索记录，继续基于仓库现有 `release.py / updater.py / patch_builder.py` 方案实现，未重复执行外部方案搜索。
- 2026-04-15：本次为既有表3流量段交互口径的文档同步，README 已有搜索记录，继续基于已确定方案更新说明，未重复执行外部方案搜索。
- 2026-04-13：本次为既有连续承压链逐行计损规则收口，README 已有搜索记录，继续基于仓库现有计算与回写链路实现，未重复执行外部方案搜索。
- 2026-04-14：本次为既有矩形暗涵升级为暗涵家族并落地 `暗涵-圆拱直墙型`，README 已有搜索记录，继续基于仓库现有暗涵/隧洞/表3/导出链路实现，未重复执行外部方案搜索。
- 2026-03-31：本次为现有功能修正和范围收口，未新增外部方案搜索，直接基于仓库现有逻辑与测试完成实现。
- 2026-04-09：本次为既有明渠体系内新增断面类型，README 已有搜索记录，继续按仓库现有明渠/批量/水面线架构扩展，未重复执行外部方案搜索。
- 2026-04-10：本次为既有 xx管 夹带隧洞能力调整为“水力核算模式”，README 已有搜索记录，继续基于仓库现有 mixed route 与导出链路实现，未重复执行外部方案搜索。
- 2026-04-13：本次为既有隧洞体系内新增 `平底圆形` 断面，README 已有搜索记录，继续沿用现有隧洞/批量/表3共享链路扩展，未重复执行外部方案搜索。

## 已完成功能列表

- 明渠设计面板已新增“复式梯形”断面，支持 6 个固定几何参数、分段公式、断面图、DXF 和 Word 导出。
- 隧洞圆拱直墙型已支持可选 `H直`：单项和批量都可填写，留空自动推导，填写后固定几何核算，并在结果和导出里说明来源。
- 隧洞圆拱直墙型已新增“按净空反推尺寸”弹窗：用户输入 `Q加大 / 目标净空比例 / H/B / θ` 后，系统可反推并校核 `B、H_total、H直`，通过后只回填当前工况的普通参数，不自动触发主计算。
- 明渠、渡槽、隧洞、暗涵设计面板已统一新增“工况对比”页签：单工况和多工况都会拆成“水力结果对比表”和“结构尺寸对比表”，只列成功工况，参数变更后提示重新计算。
- 明渠、渡槽、隧洞、暗涵的界面断面图已统一走共享绘图底座：四类面板复用同一套几何适配与 matplotlib 绘制规则，单工况统一为单图叠加设计水位和加大水位，多工况默认 2 列、窄窗口 1 列并在断面图页内部滚动，进入断面图页时按真实宽度重排，双击小图可查看该工况大图；计算内核、DXF 和 Word 导出保持原有入口。
- DXF 文字默认宽度因子已统一为 `0.7`；四类设计面板的单工况和多工况 DXF 都会在断面图下方追加两张对比表，并在 DXF 表头中使用 CAD MTEXT 上标控制码显示 `m³/s`、`m²`。
- 暗涵圆拱直墙型已支持可选 `H直`：交互与隧洞对齐，留空自动推导，填写后固定几何核算；校核和导出仍按暗涵规则执行。
- 倒虹吸面板已把 `D` 行改成实时显示：普通模式下即时展示 `D设计 / D理论`，多管并联额外展示“每管Q”；指定管径生效后展示“采用D / 实际流速”，拟定流速框切为灰色只读，取消指定后恢复原拟定流速和原确认态；工况确认态按工况在本次运行内分别记忆，重启后清空。
- 明渠、渡槽、隧洞、暗涵、倒虹吸、有压管道 6 个设计面板已统一支持“按比例 / 按Q加大”二选一输入；`按比例` 可留空自动查表，`按Q加大` 必须输入加大后的总流量且大于设计流量；旧工程默认仍按比例回显，多工况复制、恢复和导出说明会一起带上新模式和值。
- 明渠、渡槽、隧洞、暗涵的计算结果详情已新增每工况顶部“重点结果汇总”，Word 报告同步在每个工况开头插入汇总表；有压管道保持原有摘要口径。
- 渡槽已支持“拉杆高度”：单项和批量 Excel 都可填写，`tie_rod_height` 表示拉杆自身尺寸高度且按拉杆顶与槽顶齐平处理；结果中的 `H` 为含拉杆总高，汇总和导出会区分设计拉杆底净距与加大有效超高，断面图和 DXF 会标出拉杆底控制线、顶部占用带和拉杆高度；未启用加大流量时，结果、批量、Word 和 DXF 都不再显示加大工况。
- 批量计算已新增“明渠-复式梯形”，主表、参数弹窗、Excel 导入导出和结果说明全部支持新断面。
- 推求水面线已补上“明渠-复式梯形”的最小兼容，能保留 `m1/B1/m2/B2/m3/h1` 并按新公式参与水力计算。
- 构建和发版现在会在进入 PyInstaller 前先校验 Word 导出依赖，缺失 `python-docx / latex2mathml / lxml` 时直接中止并提示安装命令；打包时还会把 `latex2mathml` 的运行时文本资源一并带进安装包，避免主程序启动时因为缺少 `unimathsymbols.txt` 直接退出。
- 已支持 GitHub/Gitee 双下载源：正式发版会把同一份全量包和安全补丁包同步上传到 GitHub Release 与 Gitee Release，`version.json` 继续保留旧字段，并额外写入 `download_url_mirrors / patch_url_mirrors` 作为备用下载地址；客户端按同一 SHA256 校验所有来源。
- 已支持对已发布正式版单独回补 patch：当前通过 `tools/backfill_patch_release.py` 基于 `.release-snapshots/` 中固化的正式包、manifest 和 `version.json` 回补 patch，补挂到现有 GitHub Release，并只补齐 Gist 里的 patch 字段，不再依赖会漂移的本地 `dist`。
- 表3普通行、渐变段行、累计损失和水位递推的基础链路已接通。
- 倒虹吸和命名有压管道组支持外部专项计算后回写总损失。
- 空名称普通有压管道行现在可在 xx管，以及已形成连续承压整线的 xx渠 场景下，独立显示沿程损失、承压弯头损失和本行承压段总损失。
- 断面汇总弹窗里的有压管道参数现在按“流量段主行 + 顶管/定向钻单独行”显示；普通有压管道同一流量段只显示 1 行，确认后会自动同步到该流量段下全部普通有压管道原始分组。
- 匿名普通有压管道段的窗口结果会回写到当前行，并在后续静默重算中继续作为主来源，表3列38会锁定避免混改。
- 有压管道弹窗现已支持 GB/T 波速、`cp/a0`、允许压力输入和按 `Hmax/Hmin` 的水锤验算：单管卡和整线卡默认允许压力 `1.0MPa`，界面同步显示换算后的允许压力水头 `101.9368m`。单管卡会预填 `L / D / v0 / H0 / E`，钢筋混凝土管和 PCCP 管可补充 `a0`；未填时仍按 `cp=1` 继续验算并提示，补充后按 `cp=1/(1+0.95a0)` 折算。整线卡按“末端阀门启闭、一条连续有压管线”处理，成员参数表展示每个小段的 `Q / D / 管材 / E / v0 / a0`，只把 `e / Ts / 允许压力` 作为整线统一输入；未免验算时按等价 `L / am / vm` 判别图1-3-3水击类型，明细带出 `Hst / Hmax / Hmin / 管底最大压力水头 / 允许压力水头 / 承压余量 / 管顶最低压力水头`。当 `Ts` 满足 GB/T 20203-2017 5.1.7.4 的免验算条件时，结果直接显示“可不验算”，数值区和明细区不再给出误导性水击增压。沿线采样点只是安全校核点，不是独立阀门位置；结果可随项目一起保存和重开恢复，但不会进入主水位链。
- 水锤验算 `v0` 已改为按当前工况自动取值：勾选“考虑加大流量”时用加大流量计算，未勾选时用设计流量计算；单管、整线成员表、明细和 Excel 会同步显示流速来源与采用流量。
- 相关双击说明已经补齐，且总损失、水位、累计损失说明不会再把同一笔承压段损失重复展示。
- 隧洞沿程损失继续保持原有“底坡 × 有效长度”口径，没有被承压管道逻辑带偏。
- 表3 里只要相邻两边都属于 `有压管道 / 定向钻 / 顶管`，现在都统一按同类承压结构处理：不再插渐变段，也不再插中间连接段；但它们与隧洞相邻时仍会保留原有渐变段。
- 普通有压管道/定向钻/顶管的渐变段长度详情，现已和插入阶段统一按 `5h/6h` 显示；当长度被压缩时，也会继续明确标出物理上限和最终采用值。
- 表3执行“插入渐变段”后，软件会同步刷新内部节点状态；同一会话里再打开“有压管道水力计算”或自动保存时，不会继续读到插段前的旧拓扑。
- xx管 有压管道窗口现在只保留整线卡：同一条纯“有压管道 / 定向钻 / 顶管”线路只导入一份平面/纵断面，弹窗里不再编辑子段 `R / D`。
- xx管 整线纵断面现按 `route_key` 持久化，纵断面实长、导出中心线高程和材料/建筑物分段都会先找整线数据，再按子段桩号裁切。
- 多个空名称 xx管 子段现在会优先使用 `pressure_pipe_row_identity` 区分，避免导出和纵断面取值时相互串用。
- 压力管道特性表里的设计流速和长度现在会按流量段逐行输出；主长度默认优先取当前流量段有压边界的 `segment_start_mc / segment_end_mc`，缺失时才回退旧的整段扫描结果；其中 `xx管` 会在边界长度基础上继续补回前置无压隧洞及其与首段有压结构之间的空档，保证整线口径不丢。
- 压力管道特性表里的渠首水位和渠末水位，也会跟着流量段逐行输出；现在优先取有压管道起点和终点对应节点水位。只有连续承压线跨流量段且相邻承压节点处在同一桩号交界点时，前一段末值和后一段首值才会共用后一流量段首个边界点水位；中间有断点时仍各算各的。
- 压力管道特性表里的隧洞、定向钻、顶管摘要长度，现统一按每组“出口里程MC - 进口里程MC”统计；出口后的普通有压管道首段不再误并进建筑物长度。
- `xx渠` 的压力管道特性表里，隧洞只在同一流量段内被 `有压管道 / 定向钻 / 顶管` 前后夹住时才统计；前置隧洞和末尾隧洞都不会再进入主长度或隧洞栏。
- `支管` 的压力管道特性表里，前置无压隧洞如果属于整条承压线路，主长度会连同“隧洞出口到首段有压入口”的空档一起计回去；九龙右支管这类场景切回 `支管` 后会恢复到整线长度。
- 连续承压逐行结果现在统一以 `pressure_pipe_window_override` 为正式来源重建；表3列38、总损失、累计总损失和水位递推会一起跟随，不再出现只显示不累计的情况。
- 支渠连续承压整线现在只会从首个真正有压段起算；前置隧洞不会再被误串进整线卡、route 起点或纵断面导入锚点，但进入有压段后的后续隧洞仍会保留。
- 支渠连续承压链里的前后同名普通有压管道现在允许直接通过批量校验；真正被明渠、闸、倒虹吸、暗涵等断开的同名段仍会继续拦截，避免把后续结果串到一起。
- 命名有压段现在按连续出现的同名段分别建 `identity / storage_key`，并保留旧 `flow_section::name` 兼容别名；如果同一名称跨到新的流量段，会按新的流量段和行范围拆成独立身份，后续导出和回写优先按真实身份命中。
- 赛金支渠这类“普通有压 + 定向钻/顶管 + 同名普通有压”的连续承压链，现在会先判断链首到下一段特殊承压建筑进口之间是否存在真实距离；有长度时生成“前缀段”并把沿程损失写回下一段特殊承压建筑的进口行，无有效长度时才退回“起点锚点”。同链重名成员会自动显示为“前缀段 / 起点锚点 / 前段 / 后段”，整条链未完整成功时也会明确标成“未完成”并隐藏整线总损失。
- 赛金支渠连续承压链里的命名父组和正式子成员现在彻底分开：父组继续保留 `rows...` 身份做窗口汇总，正式写回和链汇总只认 `flow-row` 成员；中间普通段找不到自己的记录时，会直接提示“未匹配到本成员计算记录”，不再借用前缀段失败原因。
- 连续承压链里的逐段小分组现在只保留基础名称作为底层校验标签；`苟家湾（中段8）` 这类成员如果失败，失败原因抬头也会同步改成它自己的名字，不会再显示成 `苟家湾（前缀段）: ...`。
- 赛金支渠 `赛支3+968.95 / 405m` 这类前缀段导出，现在会优先按新身份找分段；若先碰到旧空记录，也会继续按 `route_key` 回退整线纵断面，不再被误判成“已导入 DXF 但未匹配”。
- xx管 弹窗里的纵断面 DXF 现在会在导入时立即校验整线导出节点是否都被覆盖，覆盖不足会直接拦截，不再“先导入、导出时再发现缺口”。
- 纵断面 DXF 导入现在会先自动筛掉闭合线、工程坐标辅助线和横向展开不足的候选，再按优先规则选中真正的纵断面；当前两名候选非常接近时，导入前会先提醒确认。
- xx管 夹带隧洞整线现在继续使用整线卡导入纵断面 DXF，但导出会按结构拆成上下两张表：上方普通渠道表承接隧洞，下方 `xx管` 表只保留 `有压管道 / 定向钻 / 顶管`。
- 连续承压 mixed route 现在把弹窗导入和“导出全部 DXF”的覆盖规则统一成同一口径：都只强校验非隧洞节点；如果真的还差范围，软件会直接说清楚差到哪个桩号、当前到哪、还差多少，以及哪些节点没覆盖。
- xx管 隧洞参数现在统一只认表1/Excel 当前值；弹窗只展示只读摘要和缺项提示，不再新增单独录入。下方专用表也不再单独展示隧洞底线或断面参数；圆拱直墙型隧洞读取 `B / H直 / θ` 并把 `H_total` 作为推导结果。
- xx渠 在末端或跨流量段形成连续承压线时，也会进入整线底座；非连续场景仍只看当前分组，同时点击“开始计算”时不再因为 identity helper 调用方式错误而报 `group` 参数缺失。
- 连续承压链中的命名 `有压管道 / 定向钻 / 顶管` 现在统一按逐行正式计损：中间命名承压段也会把每一行的损失正式写回表3，列38、总损失、累计损失和水位都改用逐段值递推；父命名组继续只保留在有压管道窗口里做汇总。
- 如果旧工程或静默重算时，命名尾段出口行只剩列38里的本段显示值，系统现在也会自动把这笔值补回总损失、累计损失和水位递推，不再出现“列38有值、列39还是 `-`、累计值停在上一行”的错位。
- 连续承压 `xx渠` 的图2导出现在复用 `xx管` 固定 5 项表头；普通有压管道第 1 行优先显示用户名称；缺少或未覆盖完整的纵断面轴线 DXF 时，第 4 行会留空并给出补导提示，但严格 `xx管` 仍保持原来的拦截规则。
- 表3第38列里被锁定的逐行承压行，现在可通过双击详情弹窗底部的“本行采用值”手动录入正式承压损失；保存后列38、总损失、累计损失和后续水位同步刷新，恢复自动计算后会回到自动结果。
- 有压管道结果弹窗已分清正式逐段值和参考整组值：正式逐段值进入表3、连续链总损失和累计水损，参考整组值只放在参考区供复核。
- 普通渠道项目如果只在末尾连续进入有压管道，图2 DXF 现在会在同一个文件里拆成上下两张表：上面继续按渠道表头输出，下面把末尾有压段单独改成 `xx管` 固定 5 项表头；合并 DXF 里的断面汇总表和 IP 表也会一起下移，避免压到新增的有压子表。
- 连续承压支管在导出时，如果普通子段缓存里只剩 1 个纵断面点，会自动回退整线 DXF；跨流量段时新流量段首个匿名普通行就算只对应单点边界，也会直接继承整线纵断面，不再把“整线已导入”误报成“点不够”。
- 整线卡里导入或清空纵断面 DXF 后，会立即写入持久层；主页面导出和弹窗预览现在读取的是同一份整线数据，不再出现“窗口里看得到、导出里却说没导入”。
- 连续承压支管在导出时，如果同桩号合并后的代表节点 identity 没命中整线纵断面，系统会继续按同桩号节点组、route 锚点和旧口径 identity 回退重试，不再把“identity 没匹配上”误报成“还没导入 DXF”。
- 连续承压 `xx渠` 的末尾双表和建筑物名称现在都走正式分段模型：上方渠道表不再整块空白，下方有压表固定 5 项表头，建筑物名称按整段范围只画一次并居中。
- xx管 mixed route 会继续保存 route 级分段结果，但对外导出口径改成“隧洞回上表、下方 xx管 表只保留有压管道 / 定向钻 / 顶管”；旧的隧洞单独参数展示不再作为文档口径保留。
- 图2“管中心线高程（米）”继续在导出时按当前平面桩号现算；节点 `station_MC` 缺失时只对个别节点按平面累计距离回退，整线都没有有效桩号锚点时直接报错。
- 普通纵断面导出现在新增 `station_decimals`，默认保留 2 位小数；同一设置会同步影响普通纵断面、IP 表、合并 DXF 里的 IP 表和 bzzh2 的桩号输出，但不会改表3和说明文字的原有显示。
- 表3顶部“转弯半径”改成“待应用统一值”：导入混合半径时保持空白，点击“自动”只填栏位，点击“应用”才统一覆盖真实导入行。
- 自动更新链路已完成一轮全面加固：补丁现在只覆盖 `1.3.0+` 近版本，更老版本仍可用全量包更新；同时会额外排除运行时自动保存文件、给全量包和 patch 增加发布级 checksum、在补丁应用完成后按 `target_files` 再做一次目标版本验收，并把“无需回滚 / 已成功回滚 / 回滚失败”三种结果分开提示。构建、正式发版和回补 patch 都共用补丁安全策略：删除文件过多、总覆盖量过大或补丁接近完整包时直接跳过 patch，只发布全量包；正式发版会同步 GitHub 与 Gitee 下载镜像，补丁或全量包下载失败时会自动尝试备用地址，补丁安装失败且回滚安全时，安装助手会自动下载完整包继续安装。补丁适用性校验遇到大文件哈希时会继续显示单文件百分比。正式发版后会额外固化 `.release-snapshots/` 快照，后续回补 patch 不再依赖会漂移的本地 `dist`。
- 明渠设计面板现已支持 `复式梯形`：输入 `m1 / B1 / m2 / B2 / m3 / h1` 后可直接反算设计水深、加大流量水深、断面图、TXT/Word/DXF 导出。
- 表3基础设置区的“设计流量 / 加大流量”现已升级为共享当前流量段的只读查看组：主界面默认只显示当前段并支持下拉切换，不再提供“编辑全部”入口；当上游来源刷新设计流量时会整体重算加大流量，批量同步和项目重开后当前段都回到第一段。
- Excel 模板里的手工 `Q加大` 已改为 `J1` 单格逗号输入，空位表示该段自动计算；旧版横向列对格式继续兼容。
- 批量计算现已支持 `明渠-复式梯形`：主表、参数弹窗、Excel 导入导出和结果文本均已补齐 6 个专用参数列。
- 推求水面线已补上 `明渠-复式梯形` 的最小兼容：能识别类型、保留 6 个参数，并按新几何公式完成开放渠道面积、湿周和水力半径计算。
- 隧洞设计面板现已支持 `平底圆形`：用户固定输入 `直径 D + 平底宽 B`，程序自动推导 `H_total`，并同步输出断面图、TXT/Word/DXF。
- 表1批量、共享结果、表3导入复算、工程保存恢复、`xx管` 隧洞摘要和断面汇总现已支持 `隧洞-平底圆形`，统一保留 `D / B / H_total` 口径；表3对该类型只允许来源带入，不允许手工新建。
- 暗涵设计家族现已落地：侧边入口统一改为“暗涵设计”，单页支持 `矩形 / 圆拱直墙型` 子类型切换，保存、批量、共享结果、表3复算、导出和断面汇总统一写回 `暗涵-矩形 / 暗涵-圆拱直墙型`。
- `暗涵-圆拱直墙型` 现已按暗涵规则参与表3、渐变段、补段、推荐转弯半径和断面汇总；它支持 `H直` 来源透传，只复用圆拱几何与水力公式，不进入 `xx管` 下方固定 5 项表，也不计入隧洞摘要、隧洞座数或隧洞长度。
- 暗涵家族最后一轮收口已补齐：表3渐变段与建筑物长度明细统一按“有效暗涵子类型”识别；表3手工入口不再允许新建 `暗涵-圆拱直墙型`；表1旧项目重存会把 `矩形暗涵 / 矩形暗渠 / 暗渠` 自动归一为 `暗涵-矩形`；倒虹吸出口局部阻力弹窗和断面汇总也补齐了暗涵旧别名映射。

## 待办事项

- 结合真实工程样表继续验收隧洞“水力核算模式”的字段命名、默认值和提示文案是否还需要再收口。
- 继续补充 route 覆盖不足、接点高差告警、连续承压链，以及更多匿名子段组合场景的回归样例。
- 继续补充暗涵家族在真实工程样表和历史工程文件上的回归样例，重点覆盖旧名兼容、导出标题和 mixed route 上下分表。
