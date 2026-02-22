# 测试数据目录

存放单元测试所需的小型测试数据文件。

## 文件列表（待补充）

| 文件名 | 说明 | 用于测试 |
|--------|------|----------|
| `simple_contours.dxf` | 5 条等高线（3D LWPOLYLINE）的最小 DXF | `test_tin_builder` |
| `survey_points.csv` | 25 个测量高程点（X,Y,Z 格式）| `test_tin_builder` |
| `centerline_stations.csv` | 10 个桩号坐标点 | `test_centerline` |
| `design_elevations.xlsx` | 纵断面设计底高程表 | `test_profile_cutter` |

## 生成说明

测试数据文件应在开发 P1.2 阶段（DXF 读取）完成后补充。
小型数据文件应满足：
- DXF 文件 < 50KB
- CSV/Excel 文件 < 10KB
- 高程值应反映真实工程尺度（高程 100~200m，坐标范围 < 1km）
