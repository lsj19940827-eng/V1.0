# 渠系水力计算综合系统

集成渠系建筑物断面计算、倒虹吸水力计算、水面线推求。

---

## 打包成 exe 发给同事

### 一次性准备（只需做一次）

1. 安装 Nuitka（打包工具）：
   ```
   pip install nuitka
   ```

2. 安装 C++ 编译器：
   - 下载 [Visual Studio Build Tools](https://visualstudio.microsoft.com/zh-hans/visual-cpp-build-tools/)
   - 安装时勾选「使用 C++ 的桌面开发」

### 打包

```
python build.py
```

等待 10~30 分钟，完成后在 `dist` 文件夹里会生成一个 zip 压缩包。

### 发给同事

把 `dist` 里的 zip 通过 **微信/QQ** 发给同事，同事解压后双击 `main.exe` 即可使用，不需要安装 Python。

### 更新版本

1. 修改 `build.py` 顶部的 `APP_VERSION = "1.0.0"` 为新版本号
2. 重新运行 `python build.py`
3. 把新的 zip 发给同事即可
