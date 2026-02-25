# -*- coding: utf-8 -*-
"""授权管理图形界面 — qfluentwidgets Win11 Fluent 风格（仅供管理员使用）"""
import base64, calendar, csv, hashlib, hmac, json, os, sys, urllib.request
from datetime import datetime

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QDialog, QFormLayout, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QMainWindow,
    QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, CardWidget, ComboBox, ElevatedCardWidget,
    InfoBar, InfoBarPosition, LineEdit, MessageBox, Pivot,
    PrimaryPushButton, PushButton, SubtitleLabel, TableWidget,
    setTheme, Theme,
)

_EXPIRE_OPTIONS = [
    ("永久（不限期）", (0, 0)), ("1 个月", (0, 1)), ("3 个月", (0, 3)),
    ("6 个月", (0, 6)), ("1 年", (1, 0)), ("2 年", (2, 0)), ("3 年", (3, 0)),
]
_EXPIRE_LABELS = [lbl for lbl, _ in _EXPIRE_OPTIONS]


def _calc_expire_date(label):
    for lbl, (years, months) in _EXPIRE_OPTIONS:
        if lbl == label:
            if not years and not months: return ""
            today = datetime.today()
            total = today.month - 1 + months + years * 12
            y, m = today.year + total // 12, total % 12 + 1
            return datetime(y, m, min(today.day, calendar.monthrange(y, m)[1])).strftime("%Y-%m-%d")
    return ""

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
try:
    from _secret_key import HMAC_SECRET, GIST_ID, GITHUB_TOKEN, GIST_FILENAME, GIST_LEDGER_FILENAME
except ImportError:
    _app = QApplication.instance() or QApplication(sys.argv)
    MessageBox("错误", "未找到 tools/_secret_key.py，请先配置密钥文件", None).exec()
    sys.exit(1)

LEDGER_PATH = os.path.join(_HERE, "授权台账.csv")
LEDGER_FIELDS = ["姓名", "机器码", "授权时间", "过期时间", "状态"]


def _sign(data):
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hmac.new(HMAC_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()

def _generate_lic(row):
    data = {"machine_id": row["机器码"], "name": row["姓名"], "issued": row["授权时间"]}
    expire = row.get("过期时间", "").strip()
    if expire and expire != "(永久)": data["expire"] = expire
    return {"data": data, "sig": _sign(data)}

def _lic_to_code(lic):
    return base64.b64encode(json.dumps(lic, ensure_ascii=False, separators=(",", ":")).encode()).decode()

def _load_ledger():
    if not os.path.exists(LEDGER_PATH): return []
    with open(LEDGER_PATH, "r", encoding="utf-8-sig") as f: return list(csv.DictReader(f))

def _save_ledger(rows):
    with open(LEDGER_PATH, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS); w.writeheader(); w.writerows(rows)

def _sync_to_gist(rows):
    revoked = [r for r in rows if r["状态"] == "已吊销"]
    bl = "\n".join(["# 渠系水力计算系统 - 授权黑名单", "# 每行一个机器码", ""]
                   + [r["机器码"] for r in revoked]) + "\n"
    url = f"https://api.github.com/gists/{GIST_ID}"
    payload = json.dumps({"files": {GIST_FILENAME: {"content": bl},
                                     GIST_LEDGER_FILENAME: {"content": json.dumps(rows, ensure_ascii=False, indent=2)}}}).encode()
    req = urllib.request.Request(url, data=payload, method="PATCH")
    req.add_header("Authorization", f"token {GITHUB_TOKEN}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "license-gui/1.0")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp: return resp.status == 200
    except Exception: return False

def _pull_from_gist():
    url = f"https://api.github.com/gists/{GIST_ID}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {GITHUB_TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "license-gui/1.0")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp: data = json.loads(resp.read().decode())
    except Exception: return False
    files = data.get("files", {})
    if GIST_LEDGER_FILENAME not in files: return None
    try:
        with urllib.request.urlopen(files[GIST_LEDGER_FILENAME]["raw_url"], timeout=10) as r:
            rows = json.loads(r.read().decode())
        return rows if isinstance(rows, list) else None
    except Exception: return False


class _GistWorker(QThread):
    done = Signal(object)
    def __init__(self, mode, rows=None): super().__init__(); self._mode = mode; self._rows = rows
    def run(self): self.done.emit(_sync_to_gist(self._rows) if self._mode == "sync" else _pull_from_gist())


class _CodeDialog(QDialog):
    def __init__(self, parent, name, code):
        super().__init__(parent)
        self.setWindowTitle(f"{name} 的授权码")
        self.setMinimumWidth(580)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        lay = QVBoxLayout(self); lay.setContentsMargins(24, 20, 24, 16); lay.setSpacing(12)
        lbl = BodyLabel(f"<b>{name}</b> 的授权码已生成，复制后通过微信/QQ 发给对方：")
        lbl.setWordWrap(True); lay.addWidget(lbl)
        self._edit = QTextEdit(); self._edit.setPlainText(code); self._edit.setReadOnly(True)
        self._edit.setFont(QFont("Consolas", 9)); self._edit.setFixedHeight(120)
        self._edit.setStyleSheet("QTextEdit{border:1px solid #e0e0e0;border-radius:6px;background:#fafafa;padding:6px;}")
        lay.addWidget(self._edit)
        self._lbl_cp = CaptionLabel(""); self._lbl_cp.setAlignment(Qt.AlignCenter)
        self._lbl_cp.setStyleSheet("color:#0078d4;"); lay.addWidget(self._lbl_cp)
        row = QHBoxLayout()
        btn_copy = PrimaryPushButton("复制授权码"); btn_copy.setFixedHeight(36)
        btn_close = PushButton("关闭"); btn_close.setFixedHeight(36)
        row.addStretch(); row.addWidget(btn_copy); row.addWidget(btn_close); lay.addLayout(row)
        self._code = code; btn_copy.clicked.connect(self._copy); btn_close.clicked.connect(self.accept)
        self._copy()
    def _copy(self):
        QApplication.clipboard().setText(self._code)
        self._lbl_cp.setText("✓ 已复制到剪贴板！直接粘贴发给对方即可")


class _AddTab(QWidget):
    def __init__(self, win): super().__init__(); self._win = win; self._build()
    def _build(self):
        outer = QVBoxLayout(self); outer.setContentsMargins(24, 20, 24, 16); outer.setSpacing(16)
        card = ElevatedCardWidget()
        cl = QVBoxLayout(card); cl.setContentsMargins(24, 20, 24, 20); cl.setSpacing(14)
        cl.addWidget(SubtitleLabel("新增授权"))
        form = QFormLayout(); form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter); form.setSpacing(10)
        self.e_name = LineEdit(); self.e_name.setPlaceholderText("输入被授权人姓名"); self.e_name.setFixedWidth(220)
        form.addRow(BodyLabel("被授权人姓名"), self.e_name)
        self.e_mid = LineEdit(); self.e_mid.setPlaceholderText("同事发来的 64 位机器码粘贴到此处")
        form.addRow(BodyLabel("机器码（64位）"), self.e_mid)
        exp_w = QWidget(); exp_row = QHBoxLayout(exp_w); exp_row.setContentsMargins(0, 0, 0, 0)
        self.combo = ComboBox(); self.combo.addItems(_EXPIRE_LABELS); self.combo.setFixedWidth(170)
        self.lbl_date = CaptionLabel(""); self.lbl_date.setStyleSheet("color:#666;margin-left:8px;")
        exp_row.addWidget(self.combo); exp_row.addWidget(self.lbl_date); exp_row.addStretch()
        form.addRow(BodyLabel("授权有效期"), exp_w)
        self.combo.currentIndexChanged.connect(self._on_expire)
        cl.addLayout(form); outer.addWidget(card)
        br = QHBoxLayout()
        btn_gen = PrimaryPushButton("生成授权码"); btn_gen.setFixedHeight(38); btn_gen.setMinimumWidth(130)
        btn_clear = PushButton("清空"); btn_clear.setFixedHeight(38)
        br.addStretch(); br.addWidget(btn_gen); br.addSpacing(8); br.addWidget(btn_clear); br.addStretch()
        outer.addLayout(br)
        hint_card = CardWidget(); hl = QVBoxLayout(hint_card); hl.setContentsMargins(16, 12, 16, 12)
        hint_lbl = BodyLabel(
            "操作说明：\n"
            "1.  同事运行程序，弹窗显示机器码，点【复制机器码】发给你\n"
            "2.  粘贴机器码，填写姓名，点击【生成授权码】\n"
            "3.  弹窗显示授权码，点【复制授权码】后通过微信/QQ 发给同事\n"
            "4.  同事在激活弹窗中粘贴授权码，点【激活】即可")
        hl.addWidget(hint_lbl); outer.addWidget(hint_card); outer.addStretch()
        btn_gen.clicked.connect(self._do_add); btn_clear.clicked.connect(self._clear)
    def _on_expire(self):
        d = _calc_expire_date(self.combo.currentText()); self.lbl_date.setText(f"到期：{d}" if d else "")
    def _clear(self):
        self.e_name.clear(); self.e_mid.clear(); self.combo.setCurrentIndex(0); self.lbl_date.setText("")
    def _infobar(self, level, title, msg):
        fn = {"success": InfoBar.success, "warning": InfoBar.warning, "error": InfoBar.error, "info": InfoBar.info}[level]
        fn(title, msg, duration=3000, parent=self._win, position=InfoBarPosition.TOP)
    def _do_add(self):
        name = self.e_name.text().strip(); mid = self.e_mid.text().strip()
        exp = _calc_expire_date(self.combo.currentText())
        if not name: self._infobar("warning", "提示", "请填写被授权人姓名"); return
        if len(mid) != 64 or not all(c in "0123456789abcdefABCDEF" for c in mid):
            self._infobar("error", "格式错误", "机器码应为 64 位十六进制字符串"); return
        rows = _load_ledger()
        for r in rows:
            if r["姓名"] == name and r["机器码"] == mid and r["状态"] == "有效":
                dlg = MessageBox("已存在", f"{name} 此设备已有有效授权。\n是否重新生成授权码？", self._win)
                if not dlg.exec(): return
        expire_str = exp if exp else "(永久)"
        row = {"姓名": name, "机器码": mid, "授权时间": datetime.today().strftime("%Y-%m-%d"),
               "过期时间": expire_str, "状态": "有效"}
        rows = [r for r in rows if not (r["姓名"] == name and r["机器码"] == mid)]
        rows.append(row); _save_ledger(rows); self._win._async_sync(rows)
        code = _lic_to_code(_generate_lic(row))
        self._infobar("success", "成功", f"已生成 {name} 的授权码，台账正在同步")
        _CodeDialog(self._win, name, code).exec(); self._win.list_tab.refresh()


class LicenseManager(QMainWindow):
    def __init__(self):
        super().__init__()
        setTheme(Theme.AUTO)
        self.setWindowTitle("授权管理工具")
        _icon_path = os.path.join(_HERE, "license_icon.ico")
        if os.path.exists(_icon_path):
            self.setWindowIcon(QIcon(_icon_path))
        self.setMinimumSize(720, 580)
        self.resize(720, 620)
        self._workers = []

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._pivot = Pivot()
        self._pivot.setContentsMargins(24, 8, 0, 0)
        root.addWidget(self._pivot)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setFixedHeight(1)
        root.addWidget(sep)

        self._stack = QStackedWidget()
        root.addWidget(self._stack)

        self.add_tab  = _AddTab(self)
        self.list_tab = _ListTab(self)
        self._stack.addWidget(self.add_tab)
        self._stack.addWidget(self.list_tab)

        self._pivot.addItem("add",  "新增授权",  lambda: self._stack.setCurrentIndex(0))
        self._pivot.addItem("list", "台账管理",  lambda: self._stack.setCurrentIndex(1))
        self._pivot.setCurrentItem("add")

        if not os.path.exists(LEDGER_PATH) or os.path.getsize(LEDGER_PATH) < 10:
            QTimer.singleShot(400, self._auto_pull)

    def _async_sync(self, rows):
        w = _GistWorker("sync", rows)
        def _done(ok):
            if ok:
                InfoBar.success("台账已同步", "云端台账和黑名单已更新",
                                duration=3000, parent=self, position=InfoBarPosition.TOP)
            else:
                InfoBar.error("同步失败", "云端同步失败，请检查网络",
                              duration=4000, parent=self, position=InfoBarPosition.TOP)
        w.done.connect(_done); w.start(); self._workers.append(w)

    def _auto_pull(self):
        result = _pull_from_gist()
        if isinstance(result, list) and result:
            _save_ledger(result); self.list_tab.refresh()
            InfoBar.success("已恢复", f"从云端恢复 {len(result)} 条授权记录",
                            duration=3000, parent=self, position=InfoBarPosition.TOP)


class _ListTab(QWidget):
    def __init__(self, win): super().__init__(); self._win = win; self._build()
    def _build(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(24, 16, 24, 12); lay.setSpacing(10)
        self.table = TableWidget(self); self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["姓名", "机器码", "授权时间", "过期时间", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 90); self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 100); self.table.setColumnWidth(4, 70)
        self.table.setEditTriggers(TableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(TableWidget.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setBorderVisible(True); self.table.setBorderRadius(8)
        lay.addWidget(self.table)
        br = QHBoxLayout()
        for text, slot in [("刷新", self.refresh), ("重新生成授权码", self._regen),
                            ("吊销授权", self._revoke), ("从云端同步", self._pull)]:
            btn = PushButton(text); btn.setFixedHeight(34); btn.clicked.connect(slot); br.addWidget(btn)
        lay.addLayout(br); self.refresh()
    def refresh(self):
        rows = _load_ledger(); self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [r["姓名"], r["机器码"][:24]+"...", r["授权时间"], r.get("过期时间") or "(永久)", r["状态"]]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(v); item.setTextAlignment(Qt.AlignCenter)
                if r["状态"] == "已吊销": item.setForeground(QColor("#aaa"))
                self.table.setItem(i, j, item)
    def _ib(self, level, title, msg, dur=3000):
        fn = {"s": InfoBar.success, "w": InfoBar.warning, "e": InfoBar.error, "i": InfoBar.info}[level]
        fn(title, msg, duration=dur, parent=self._win, position=InfoBarPosition.TOP)
    def _get_sel(self):
        idx = self.table.currentRow()
        if idx < 0: self._ib("w", "提示", "请先在表格中选中一行"); return None, None
        rows = _load_ledger()
        return (None, None) if idx >= len(rows) else (rows, idx)
    def _regen(self):
        rows, idx = self._get_sel()
        if rows is None: return
        row = rows[idx]
        if row["状态"] == "已吊销": self._ib("e", "无法操作", f"{row['姓名']} 已被吊销"); return
        self._ib("s", "成功", f"已生成 {row['姓名']} 的授权码")
        _CodeDialog(self._win, row["姓名"], _lic_to_code(_generate_lic(row))).exec()
    def _revoke(self):
        rows, idx = self._get_sel()
        if rows is None: return
        row = rows[idx]
        if row["状态"] == "已吊销": self._ib("w", "提示", f"{row['姓名']} 已处于吊销状态"); return
        dlg = MessageBox("确认吊销",
            f"确定吊销 {row['姓名']} 的授权？\n\n吊销后将同步在线黑名单，该用户任意版本下次启动即失效。",
            self._win)
        if not dlg.exec(): return
        rows[idx]["状态"] = "已吊销"; _save_ledger(rows); self.refresh()
        w = _GistWorker("sync", rows)
        def _done(ok):
            self._ib("s" if ok else "e",
                     "已吊销" if ok else "同步失败",
                     f"{row['姓名']} 授权已吊销，云端黑名单已同步" if ok
                     else "吊销成功，但云端同步失败，请检查网络后点【从云端同步】", 4000)
        w.done.connect(_done); w.start(); self._win._workers.append(w)

    def _pull(self):
        self._ib("i", "同步中", "正在从云端拉取台账...", 2000)
        w = _GistWorker("pull")
        def _done(result):
            if result is False:
                self._ib("e", "同步失败", "网络错误或 Token 失效，请检查网络和 _secret_key.py", 5000)
            elif result is None:
                self._ib("w", "无数据", "云端尚无台账，请先通过【新增授权】添加第一条记录", 4000)
            else:
                _save_ledger(result); self.refresh()
                self._ib("s", "同步完成", f"已同步 {len(result)} 条记录")
        w.done.connect(_done); w.start(); self._win._workers.append(w)


if __name__ == '__main__':
    app = QApplication.instance() or QApplication(sys.argv)
    win = LicenseManager()
    win.show()
    sys.exit(app.exec())
