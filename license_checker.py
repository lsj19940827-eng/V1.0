# -*- coding: utf-8 -*-
"""
授权校验模块

程序启动时调用 check_license() 验证授权有效性。
支持：本地 HMAC 签名校验 + 机器码绑定 + 过期日期 + 在线黑名单
"""

import base64
import hashlib
import hmac
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime


# ============================================================
# 授权码编解码（供 license_gui 和本模块共用）
# ============================================================
def lic_to_code(lic: dict) -> str:
    """将授权字典编码为可发送的授权码字符串（Base64）"""
    return base64.b64encode(
        json.dumps(lic, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def code_to_lic(code: str) -> dict:
    """将授权码字符串解码为授权字典；格式错误抛出 ValueError"""
    try:
        return json.loads(base64.b64decode(code.strip()).decode("utf-8"))
    except Exception as e:
        raise ValueError(f"授权码格式无效: {e}")

# ============================================================
# 配置
# ============================================================
_HMAC_SECRET = "CanalHydCalc_2026_@#SecretKey!$%^&*"

_GIST_RAW_URL = (
    "https://gist.githubusercontent.com/"
    "lsj19940827-eng/"
    "2c404e0a294dd15de8b171e770ebfb2b/"
    "raw/blacklist.txt"
)

_ONLINE_TIMEOUT = 4   # 在线校验超时秒数
# 未打包（开发/调试时）自动跳过校验；打包为 exe 后自动启用
_DEV_MODE = not getattr(sys, 'frozen', False)


# ============================================================
# 硬件指纹
# ============================================================
def _get_physical_macs():
    """获取物理网卡 MAC，过滤虚拟网卡"""
    macs = []
    try:
        result = subprocess.check_output(
            ["wmic", "nic", "get", "MACAddress,PhysicalAdapter"],
            timeout=5, stderr=subprocess.DEVNULL
        ).decode("gbk", errors="ignore")
        for line in result.splitlines():
            if "TRUE" in line.upper():
                parts = line.split()
                for part in parts:
                    if len(part) == 17 and part.count(":") == 5:
                        macs.append(part.upper())
    except Exception:
        pass
    return sorted(macs)


def _get_disk_serial():
    """获取主硬盘序列号"""
    try:
        result = subprocess.check_output(
            ["wmic", "diskdrive", "get", "SerialNumber"],
            timeout=5, stderr=subprocess.DEVNULL
        ).decode("gbk", errors="ignore")
        lines = [
            ln.strip() for ln in result.splitlines()
            if ln.strip() and "SerialNumber" not in ln
        ]
        if lines:
            return lines[0]
    except Exception:
        pass
    return ""


def get_machine_id():
    """生成当前机器的硬件指纹（SHA256 hex）"""
    macs = _get_physical_macs()
    disk = _get_disk_serial()
    hostname = platform.node()
    raw = "|".join(macs) + "||" + disk + "||" + hostname
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ============================================================
# 路径工具
# ============================================================
def _get_app_dir():
    """返回 exe 所在目录（打包后）或脚本所在目录（开发时）"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _get_license_dir():
    """返回授权文件存储目录（固定在 APPDATA 下，与程序安装位置无关）"""
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        lic_dir = os.path.join(appdata, "CanalHydCalc")
    else:
        # 回退到 exe 目录
        lic_dir = _get_app_dir()
    os.makedirs(lic_dir, exist_ok=True)
    return lic_dir


def _migrate_license_if_needed():
    """向后兼容：若旧位置（exe目录）有 license.lic，自动迁移到新位置"""
    old_path = os.path.join(_get_app_dir(), "license.lic")
    new_path = os.path.join(_get_license_dir(), "license.lic")
    if os.path.exists(old_path) and not os.path.exists(new_path):
        try:
            import shutil
            shutil.copy2(old_path, new_path)
        except Exception:
            pass


# ============================================================
# 在线黑名单
# ============================================================
def _fetch_blacklist_online():
    """从 GitHub Gist 拉取黑名单，返回机器码 set；失败返回 None"""
    try:
        import urllib.request
        req = urllib.request.Request(_GIST_RAW_URL)
        with urllib.request.urlopen(req, timeout=_ONLINE_TIMEOUT) as resp:
            content = resp.read().decode("utf-8")
        ids = set()
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                ids.add(line)
        return ids
    except Exception:
        return None


def _load_cached_blacklist():
    """加载本地缓存的黑名单（离线时使用）"""
    cache_path = os.path.join(_get_license_dir(), ".lc")
    try:
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data.get("ids", []))
    except Exception:
        pass
    return set()


def _save_blacklist_cache(ids):
    """将黑名单缓存到本地"""
    cache_path = os.path.join(_get_license_dir(), ".lc")
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"ids": list(ids), "ts": time.time()}, f)
    except Exception:
        pass


# ============================================================
# HMAC 校验
# ============================================================
def _verify_hmac(data: dict, sig: str) -> bool:
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False)
    expected = hmac.new(
        _HMAC_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig)


# ============================================================
# 弹窗提示
# ============================================================
def _show_error(msg: str):
    """显示普通错误弹窗（优先 Qt，回退 tkinter，再回退控制台）"""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication(sys.argv)
        box = QMessageBox()
        box.setWindowTitle("授权验证失败")
        box.setText(msg)
        box.setIcon(QMessageBox.Icon.Critical)
        box.exec()
    except Exception:
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("授权验证失败", msg)
            root.destroy()
        except Exception:
            print(f"\n[授权错误] {msg}\n")


def _show_activation_dialog(machine_id: str, lic_path: str) -> bool:
    """
    未找到授权时弹出激活对话框：
      步骤1 — 复制机器码发给管理员
      步骤2 — 将管理员回传的授权码粘贴进来，点击激活
    激活成功 → 保存 license.lic，返回 True
    关闭/退出 → 返回 False
    """
    # ── Qt 版本 ──────────────────────────────────────────────
    try:
        from PySide6.QtWidgets import (
            QApplication, QDialog, QVBoxLayout, QHBoxLayout,
            QLabel, QLineEdit, QTextEdit, QPushButton,
        )
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QFont

        app = QApplication.instance() or QApplication(sys.argv)
        activated = [False]

        dlg = QDialog()
        dlg.setWindowTitle("软件激活")
        dlg.setMinimumWidth(560)
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root_layout = QVBoxLayout(dlg)
        root_layout.setSpacing(10)
        root_layout.setContentsMargins(24, 20, 24, 16)

        # ── 标题 ──
        lbl_title = QLabel("本软件需要授权才能使用")
        f = lbl_title.font(); f.setPointSize(13); f.setBold(True)
        lbl_title.setFont(f)
        root_layout.addWidget(lbl_title)

        # ── 步骤1 ──
        lbl_s1 = QLabel("第 1 步：复制本机机器码，通过微信/QQ 发给管理员")
        lbl_s1.setFont(QFont("Microsoft YaHei", 10))
        root_layout.addWidget(lbl_s1)

        mid_row = QHBoxLayout()
        mid_edit = QLineEdit(machine_id)
        mid_edit.setReadOnly(True)
        mid_edit.setFont(QFont("Consolas", 9))
        mid_edit.setToolTip("Ctrl+A 全选后 Ctrl+C 复制")
        mid_row.addWidget(mid_edit)

        lbl_copied = QLabel("")
        lbl_copied.setFixedWidth(100)
        mid_row.addWidget(lbl_copied)

        btn_copy_mid = QPushButton("复制机器码")
        btn_copy_mid.setFixedWidth(100)
        mid_row.addWidget(btn_copy_mid)
        root_layout.addLayout(mid_row)

        def on_copy_mid():
            QApplication.clipboard().setText(machine_id)
            lbl_copied.setText("  已复制！")

        btn_copy_mid.clicked.connect(on_copy_mid)

        # ── 步骤2 ──
        lbl_s2 = QLabel("第 2 步：将管理员发给你的授权码粘贴到下方，点击激活")
        lbl_s2.setFont(QFont("Microsoft YaHei", 10))
        root_layout.addWidget(lbl_s2)

        code_edit = QTextEdit()
        code_edit.setFixedHeight(80)
        code_edit.setFont(QFont("Consolas", 9))
        code_edit.setPlaceholderText("在此粘贴授权码（Ctrl+V）...")
        root_layout.addWidget(code_edit)

        lbl_err = QLabel("")
        lbl_err.setStyleSheet("color: red;")
        root_layout.addWidget(lbl_err)

        # ── 按钮行 ──
        btn_row = QHBoxLayout()
        btn_activate = QPushButton("激  活")
        btn_activate.setFixedHeight(36)
        btn_activate.setDefault(True)
        f2 = btn_activate.font(); f2.setPointSize(11); btn_activate.setFont(f2)
        btn_exit = QPushButton("退出程序")
        btn_row.addStretch()
        btn_row.addWidget(btn_activate)
        btn_row.addWidget(btn_exit)
        root_layout.addLayout(btn_row)

        def on_activate():
            code = code_edit.toPlainText().strip()
            if not code:
                lbl_err.setText("请先粘贴授权码")
                return
            try:
                lic = code_to_lic(code)
            except ValueError:
                lbl_err.setText("授权码格式无效，请确认复制完整")
                return
            # 验证签名
            if not _verify_hmac(lic.get("data", {}), lic.get("sig", "")):
                lbl_err.setText("授权码无效（签名不匹配），请联系管理员重新获取")
                return
            # 验证机器码
            if lic.get("data", {}).get("machine_id") != machine_id:
                lbl_err.setText("此授权码不适用于本机，请联系管理员重新申请")
                return
            # 验证过期
            expire = lic.get("data", {}).get("expire", "")
            if expire:
                try:
                    if datetime.today().date() > datetime.strptime(expire, "%Y-%m-%d").date():
                        lbl_err.setText(f"授权码已于 {expire} 到期，请联系管理员续期")
                        return
                except Exception:
                    pass
            # 保存
            with open(lic_path, "w", encoding="utf-8") as f_out:
                json.dump(lic, f_out, ensure_ascii=False, indent=2)
            activated[0] = True
            dlg.accept()

        btn_activate.clicked.connect(on_activate)
        btn_exit.clicked.connect(dlg.reject)

        dlg.exec()
        return activated[0]

    except Exception:
        pass

    # ── tkinter 回退版本 ──────────────────────────────────────
    try:
        import tkinter as tk
        from tkinter import ttk, scrolledtext

        result = [False]
        root = tk.Tk()
        root.title("软件激活")
        root.resizable(False, False)
        root.geometry("560x380")

        tk.Label(root, text="本软件需要授权才能使用",
                 font=("Microsoft YaHei", 13, "bold")).pack(pady=(14, 4))

        tk.Label(root, text="第 1 步：复制本机机器码，发给管理员",
                 font=("Microsoft YaHei", 10), anchor="w").pack(fill="x", padx=16)

        mid_frm = tk.Frame(root)
        mid_frm.pack(fill="x", padx=16, pady=4)
        mid_var = tk.StringVar(value=machine_id)
        mid_entry = tk.Entry(mid_frm, textvariable=mid_var, state="readonly",
                             font=("Consolas", 9), width=52)
        mid_entry.pack(side="left")
        lbl_cp = tk.Label(mid_frm, text="", width=8)
        lbl_cp.pack(side="left")

        def do_copy():
            root.clipboard_clear(); root.clipboard_append(machine_id)
            lbl_cp.config(text="已复制！")

        tk.Button(mid_frm, text="复制机器码", command=do_copy).pack(side="left", padx=4)

        tk.Label(root, text="第 2 步：将管理员发给你的授权码粘贴到下方，点击激活",
                 font=("Microsoft YaHei", 10), anchor="w").pack(fill="x", padx=16, pady=(10, 2))

        code_box = scrolledtext.ScrolledText(root, font=("Consolas", 9), height=5, width=64)
        code_box.pack(padx=16)

        lbl_err = tk.Label(root, text="", foreground="red")
        lbl_err.pack()

        def do_activate():
            code = code_box.get("1.0", "end").strip()
            if not code:
                lbl_err.config(text="请先粘贴授权码")
                return
            try:
                lic = code_to_lic(code)
            except ValueError:
                lbl_err.config(text="授权码格式无效")
                return
            if not _verify_hmac(lic.get("data", {}), lic.get("sig", "")):
                lbl_err.config(text="授权码无效（签名不匹配）")
                return
            if lic.get("data", {}).get("machine_id") != machine_id:
                lbl_err.config(text="此授权码不适用于本机")
                return
            expire = lic.get("data", {}).get("expire", "")
            if expire:
                try:
                    if datetime.today().date() > datetime.strptime(expire, "%Y-%m-%d").date():
                        lbl_err.config(text=f"授权码已于 {expire} 到期")
                        return
                except Exception:
                    pass
            with open(lic_path, "w", encoding="utf-8") as f_out:
                json.dump(lic, f_out, ensure_ascii=False, indent=2)
            result[0] = True
            root.destroy()

        btn_frm = tk.Frame(root)
        btn_frm.pack(pady=10)
        tk.Button(btn_frm, text="激  活", font=("Microsoft YaHei", 11),
                  width=12, command=do_activate).pack(side="left", padx=8)
        tk.Button(btn_frm, text="退出程序", command=root.destroy).pack(side="left")

        root.mainloop()
        return result[0]

    except Exception:
        print(f"\n[未授权] 本机机器码：\n{machine_id}\n")
        print("请将机器码发给管理员获取授权码，然后重新运行程序。")
        return False


def _show_machine_id_dialog(machine_id: str):
    """主程序内'关于'菜单调用"""
    _show_activation_dialog(machine_id, "")


# ============================================================
# 主校验函数
# ============================================================
def check_license() -> bool:
    """
    验证授权。通过返回 True；失败弹窗提示并返回 False。
    在 main.py 最前面调用：
        from license_checker import check_license
        if not check_license():
            sys.exit(1)
    """
    if _DEV_MODE:
        return True

    _migrate_license_if_needed()
    lic_dir = _get_license_dir()
    lic_path = os.path.join(lic_dir, "license.lic")

    # 1. 文件存在性 — 未找到时弹出激活对话框
    if not os.path.exists(lic_path):
        activated = _show_activation_dialog(get_machine_id(), lic_path)
        if not activated:
            return False
        # 激活成功，license.lic 已保存，继续验证

    # 2. 解析授权文件
    try:
        with open(lic_path, "r", encoding="utf-8") as f:
            lic = json.load(f)
        data = lic["data"]
        sig = lic["sig"]
    except Exception:
        _show_error("授权文件已损坏，请重新向管理员申请。")
        return False

    # 3. HMAC 签名验证（防伪造/篡改）
    if not _verify_hmac(data, sig):
        _show_error("授权文件无效（签名校验失败），\n请联系管理员重新获取。")
        return False

    # 4. 机器码验证
    current_id = get_machine_id()
    if data.get("machine_id") != current_id:
        activated = _show_activation_dialog(current_id, lic_path)
        if not activated:
            return False
        # 激活成功，重新读取新 license.lic 继续验证
        try:
            with open(lic_path, "r", encoding="utf-8") as f:
                lic = json.load(f)
            data = lic["data"]
            sig = lic["sig"]
        except Exception:
            _show_error("授权文件已损坏，请重新向管理员申请。")
            return False
        if not _verify_hmac(data, sig):
            _show_error("授权文件无效（签名校验失败），\n请联系管理员重新获取。")
            return False

    # 5. 过期验证
    expire = data.get("expire", "")
    if expire:
        try:
            exp_date = datetime.strptime(expire, "%Y-%m-%d").date()
            if datetime.today().date() > exp_date:
                _show_error(f"授权已于 {expire} 到期。\n\n请联系管理员续期。")
                return False
        except Exception:
            pass

    # 6. 在线黑名单（支持离线缓存回退）
    online_ids = _fetch_blacklist_online()
    if online_ids is not None:
        _save_blacklist_cache(online_ids)
        blacklist = online_ids
    else:
        blacklist = _load_cached_blacklist()

    if current_id in blacklist:
        _show_error("此授权已被管理员吊销。\n\n如有疑问请联系管理员。")
        return False

    return True
