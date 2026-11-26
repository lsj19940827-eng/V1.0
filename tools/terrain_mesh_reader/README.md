# 已保存 Rhino 地形网格读取器

读取 `.3dm` 中已经保存的三角网，保留原始面索引和双精度 XYZ。
使用 McNeel 官方 Rhino3dm 8.35.0 / OpenNURBS 独立库（MIT），不引用
RhinoCommon，不启动 RhinoCore，不要求 Rhino 安装或许可证。

Python 入口为 `reader.read_mesh(path, mesh_index=None, cancelled=None)`，返回
`(points float64[N,3], triangles int64[M,3], metadata)`。模型单位须为米；
多个网格须明确选择索引；四边面不会被自动分割或重新建网。

直接运行兼容参数为 `TerrainMeshReader.exe unused-system-path input.3dm output.bin [mesh-index]`。
第一参数仅为兼容旧调用保留，实际依赖固定从 `bin/` 加载。

构建使用 Windows .NET Framework 编译器，无需另装 .NET SDK：

```powershell
& .venv/Scripts/python.exe tools/terrain_mesh_reader/build.py --download
```

离线已有 `vendor/rhino3dm.8.35.0.nupkg` 时省略 `--download`。
`build-manifest.json` 绑定源码、官方包、可执行文件及库的 SHA256。
NuGet 包较大，下载中断时不要把残缺包作为可用包；ZIP 读取将拒绝它。

官方来源：

- [Rhino3dm 8.35.0 NuGet 包](https://www.nuget.org/packages/Rhino3dm/8.35.0)
- [MIT 许可](https://github.com/mcneel/rhino3dm/blob/main/LICENSE)
- [双精度 Point3dAt 源码](https://github.com/mcneel/rhino3dm/blob/8.x/src/dotnet/opennurbs/opennurbs_mesh.cs)

二进制传输格式为 `QXTIN01\0`、两个 little-endian int32 计数、float64 XYZ、
int32 三角面索引；Python 解码前核对总字节数，再核对有限坐标及有效索引。
不经过 Python rhino3dm 的 `Mesh.Vertices[i]`（Point3f）接口。

`writer.append_meshes(source_3dm, output_3dm, mesh_specs, document_strings=...)`
使用相同二进制格式批量追加计算Mesh。每个spec包含`vertices`、`faces`、
`name`、`layer`、RGBA `color`及`user_strings`；默认要求追加网格闭合。
读取完整源文档后，通过Rhino3dm.NET的double Add写入一次，实际重开并严格核对
全部原地形和新增Mesh的双精度XYZ及原面索引、原对象ID和新增属性。
源文件及已有目标在失败或取消时保持不变。该入口用于避开Python绑定的
`Vertices.Add(x,y,z)`仍可能先转成Point3f的问题，不通过放宽精度检查交付。
