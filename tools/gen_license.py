# -*- coding: utf-8 -*-
"""
授权文件生成器（仅供管理员使用）

用法：
    python tools/gen_license.py --machine-id <机器码> --name 张三
    python tools/gen_license.py --machine-id <机器码> --name 张三 --expire 2027-12-31
    python tools/gen_license.py --machine-id <机器码> --name 张三 --out D:/output/license.lic
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _secret_key import HMAC_SECRET
except ImportError:
    print("[错误] 未找到 tools/_secret_key.py，请先创建密钥文件")
    sys.exit(1)


def sign(data: dict) -> str:
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hmac.new(
        HMAC_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def generate_license(machine_id: str, name: str, expire: str = None) -> dict:
    data = {
        "machine_id": machine_id,
        "name": name,
        "issued": datetime.today().strftime("%Y-%m-%d"),
    }
    if expire:
        data["expire"] = expire
    return {"data": data, "sig": sign(data)}


def main():
    parser = argparse.ArgumentParser(description="授权文件生成器")
    parser.add_argument("--machine-id", required=True, help="目标机器码（64位hex）")
    parser.add_argument("--name", required=True, help="被授权人姓名")
    parser.add_argument("--expire", default=None, help="过期日期 YYYY-MM-DD（不填则永久有效）")
    parser.add_argument("--out", default="license.lic", help="输出文件路径（默认 license.lic）")
    args = parser.parse_args()

    if args.expire:
        try:
            datetime.strptime(args.expire, "%Y-%m-%d")
        except ValueError:
            print("[错误] 日期格式错误，应为 YYYY-MM-DD，例如 2027-12-31")
            sys.exit(1)

    lic = generate_license(args.machine_id, args.name, args.expire)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(lic, f, ensure_ascii=False, indent=2)

    print(f"[成功] 授权文件已生成: {os.path.abspath(args.out)}")
    print(f"  被授权人: {args.name}")
    print(f"  机器码:   {args.machine_id[:16]}...（共{len(args.machine_id)}位）")
    print(f"  授权时间: {lic['data']['issued']}")
    print(f"  过期时间: {args.expire or '永久有效'}")
    print(f"\n  → 请将 license.lic 连同程序 zip 一起发给 {args.name}")


if __name__ == "__main__":
    main()
