# -*- coding: utf-8 -*-
"""
授权台账管理器（仅供管理员使用）

用法：
    python tools/license_manager.py list
    python tools/license_manager.py add --name 张三 --id <机器码>
    python tools/license_manager.py add --name 张三 --id <机器码> --expire 2027-12-31
    python tools/license_manager.py revoke --name 张三
    python tools/license_manager.py gen --name 张三
    python tools/license_manager.py gen --name 张三 --out D:/发给张三/license.lic
"""

import argparse
import csv
import hashlib
import hmac
import json
import os
import sys
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _secret_key import HMAC_SECRET, GIST_ID, GITHUB_TOKEN, GIST_FILENAME
except ImportError:
    print("[错误] 未找到 tools/_secret_key.py，请先创建密钥文件")
    sys.exit(1)

LEDGER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "授权台账.csv")
LEDGER_FIELDS = ["姓名", "机器码", "授权时间", "过期时间", "状态"]


# ============================================================
# 台账读写
# ============================================================
def _load_ledger():
    if not os.path.exists(LEDGER_PATH):
        return []
    with open(LEDGER_PATH, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _save_ledger(rows):
    with open(LEDGER_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


# ============================================================
# 授权文件生成
# ============================================================
def _sign(data: dict) -> str:
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hmac.new(
        HMAC_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def _generate_lic_file(row: dict, out_path: str):
    data = {
        "machine_id": row["机器码"],
        "name": row["姓名"],
        "issued": row["授权时间"],
    }
    expire = row.get("过期时间", "").strip()
    if expire and expire != "(永久)":
        data["expire"] = expire
    lic = {"data": data, "sig": _sign(data)}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(lic, f, ensure_ascii=False, indent=2)


# ============================================================
# 在线黑名单同步
# ============================================================
def _update_gist_blacklist(rows):
    """将已吊销的机器码推送到 GitHub Gist 黑名单"""
    revoked = [r for r in rows if r["状态"] == "已吊销"]
    lines = [
        "# 渠系水力计算系统 - 授权黑名单",
        "# 每行一个机器码（由 license_manager 自动维护，请勿手动编辑）",
        "",
    ]
    for r in revoked:
        lines.append(r["机器码"])

    content = "\n".join(lines) + "\n"
    url = f"https://api.github.com/gists/{GIST_ID}"
    payload = json.dumps({"files": {GIST_FILENAME: {"content": content}}}).encode("utf-8")

    req = urllib.request.Request(url, data=payload, method="PATCH")
    req.add_header("Authorization", f"token {GITHUB_TOKEN}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "license-manager/1.0")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[警告] 更新 Gist 失败: {e}")
        return False


# ============================================================
# 子命令实现
# ============================================================
def cmd_list(args):
    rows = _load_ledger()
    if not rows:
        print("台账为空，尚未授权任何用户。")
        return
    valid_count = sum(1 for r in rows if r["状态"] == "有效")
    revoked_count = sum(1 for r in rows if r["状态"] == "已吊销")

    print(f"\n{'姓名':<8} {'机器码（前16位）':<20} {'授权时间':<12} {'过期时间':<14} 状态")
    print("─" * 65)
    for r in rows:
        mid_short = r["机器码"][:16] + "..."
        expire = r.get("过期时间") or "(永久)"
        status = r["状态"]
        print(f"{r['姓名']:<8} {mid_short:<20} {r['授权时间']:<12} {expire:<14} {status}")
    print("─" * 65)
    print(f"共 {len(rows)} 条  |  有效: {valid_count}  |  已吊销: {revoked_count}\n")


def cmd_add(args):
    rows = _load_ledger()
    for r in rows:
        if r["姓名"] == args.name and r["状态"] == "有效":
            print(f"[警告] {args.name} 已有有效授权，如需更换机器请先 revoke 再重新 add")
            return

    if args.expire:
        try:
            datetime.strptime(args.expire, "%Y-%m-%d")
        except ValueError:
            print("[错误] 日期格式错误，应为 YYYY-MM-DD，例如 2027-12-31")
            return

    expire_str = args.expire if args.expire else "(永久)"
    row = {
        "姓名": args.name,
        "机器码": args.id,
        "授权时间": datetime.today().strftime("%Y-%m-%d"),
        "过期时间": expire_str,
        "状态": "有效",
    }
    rows.append(row)
    _save_ledger(rows)
    print(f"[成功] 已将 {args.name} 添加到台账")

    out_path = f"{args.name}_license.lic"
    _generate_lic_file(row, out_path)
    print(f"[成功] 授权文件已生成: {os.path.abspath(out_path)}")
    print(f"  过期时间: {expire_str}")
    print(f"  → 请将此文件连同程序 zip 一起发给 {args.name}")


def cmd_revoke(args):
    rows = _load_ledger()
    target = None
    for r in rows:
        if r["姓名"] == args.name and r["状态"] == "有效":
            target = r
            break

    if target is None:
        existing = [r for r in rows if r["姓名"] == args.name]
        if existing and existing[-1]["状态"] == "已吊销":
            print(f"[提示] {args.name} 已处于吊销状态，无需重复操作")
        else:
            print(f"[错误] 台账中未找到有效授权用户: {args.name}")
        return

    target["状态"] = "已吊销"
    _save_ledger(rows)
    print(f"[成功] 已将 {args.name} 标记为已吊销")

    print("正在同步在线黑名单...")
    if _update_gist_blacklist(rows):
        print(f"[成功] 在线黑名单已更新，{args.name} 的任意版本程序将在下次启动时失效")
    else:
        print("[警告] 在线黑名单更新失败，请检查网络或 GitHub Token 是否有效")
        print("       可重试：python tools/license_manager.py revoke --name " + args.name)


def cmd_gen(args):
    rows = _load_ledger()
    target = None
    for r in rows:
        if r["姓名"] == args.name and r["状态"] == "有效":
            target = r
            break

    if target is None:
        print(f"[错误] 台账中未找到有效授权用户: {args.name}，请先 add")
        return

    out_path = args.out if args.out else f"{args.name}_license.lic"
    _generate_lic_file(target, out_path)
    print(f"[成功] 授权文件已重新生成: {os.path.abspath(out_path)}")
    print(f"  → 发给 {args.name}，放到程序 exe 同目录即可")


# ============================================================
# 入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="授权台账管理器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python tools/license_manager.py list
  python tools/license_manager.py add --name 张三 --id <机器码>
  python tools/license_manager.py add --name 张三 --id <机器码> --expire 2027-12-31
  python tools/license_manager.py revoke --name 张三
  python tools/license_manager.py gen --name 张三
        """
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="查看所有授权记录")

    p_add = sub.add_parser("add", help="新增授权")
    p_add.add_argument("--name", required=True, help="被授权人姓名")
    p_add.add_argument("--id", required=True, help="目标机器码（64位hex）")
    p_add.add_argument("--expire", default=None, help="过期日期 YYYY-MM-DD（不填则永久）")

    p_rev = sub.add_parser("revoke", help="吊销授权（实时更新在线黑名单）")
    p_rev.add_argument("--name", required=True, help="被吊销人姓名")

    p_gen = sub.add_parser("gen", help="重新生成授权文件")
    p_gen.add_argument("--name", required=True, help="被授权人姓名")
    p_gen.add_argument("--out", default=None, help="输出文件路径（默认 <姓名>_license.lic）")

    args = parser.parse_args()
    {"list": cmd_list, "add": cmd_add, "revoke": cmd_revoke, "gen": cmd_gen}[args.cmd](args)


if __name__ == "__main__":
    main()
