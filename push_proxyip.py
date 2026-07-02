"""推送优选 IP 到 edgetunnel 的 KV 存储 (ADD.txt)

原样读取结果文件，通过 CF KV API 更新。
"""

import sys
from pathlib import Path

import requests

from src.config import load_config


def read_file(filepath: Path) -> str:
    """原样读取文件内容（跳过空行和注释）"""
    if not filepath.exists():
        print(f"错误：未找到文件 {filepath}")
        sys.exit(1)

    lines = []
    with filepath.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                lines.append(stripped)
    return "\n".join(lines)


def read_file_safe(filepath: Path) -> str:
    """安全读取文件内容（文件不存在时返回空字符串）"""
    if not filepath.exists():
        return ""

    lines = []
    with filepath.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                lines.append(stripped)
    return "\n".join(lines)


def push_to_kv(account_id: str, api_token: str, namespace_id: str, content: str) -> bool:
    """调用 CF KV API 写入 ADD.txt"""
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
        f"/storage/kv/namespaces/{namespace_id}/values/ADD.txt"
    )
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "text/plain",
    }
    resp = requests.put(url, data=content.encode("utf-8"), headers=headers, timeout=30)
    if resp.status_code == 200 and resp.json().get("success"):
        return True

    print(f"KV 写入失败 (HTTP {resp.status_code}):")
    print(resp.text)
    return False


def run_push(cfg=None) -> int:
    """供 main.py 调用的入口"""
    if cfg is None:
        cfg = load_config()

    push = cfg.push
    if not push.enabled:
        print("推送未启用，跳过")
        return 0

    if not all([push.account_id, push.api_token, push.kv_namespace_id]):
        print("错误：请在 config.toml [push] 中填写 account_id、api_token、kv_namespace_id")
        return 1

    content = read_file(push.input_file)
    if not content:
        print("文件为空，跳过推送")
        return 0

    # 合并额外地址文件
    if push.extra_enabled:
        extra_content = read_file_safe(push.extra_file)
        if extra_content:
            content = content + "\n" + extra_content
            print(f"[推送] 已合并额外地址文件 {push.extra_file}")
        else:
            print(f"[推送] 额外地址文件 {push.extra_file} 不存在或为空，跳过合并")

    lines = content.splitlines()
    print(f"\n[推送] 共 {len(lines)} 行 → KV (ADD.txt) ...")
    if push_to_kv(push.account_id, push.api_token, push.kv_namespace_id, content):
        print("[推送] 成功 ✓")
        return 0
    else:
        print("[推送] 失败")
        return 1


def main() -> int:
    return run_push()


if __name__ == "__main__":
    raise SystemExit(main())
