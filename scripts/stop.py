"""KnowledgeHub 停止脚本（跨平台）。

只终止本项目占用的端口（后端 8000 / 前端 5173），不影响其他程序。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILE = ROOT / ".kh_runtime.json"

# 默认端口；若 run.py 记录了实际端口，则以记录为准
DEFAULT_PORTS = [8000, 5173]


def resolve_ports() -> list[int]:
    ports = list(DEFAULT_PORTS)
    try:
        if RUNTIME_FILE.exists():
            data = json.loads(RUNTIME_FILE.read_text(encoding="utf-8"))
            for key in ("backend_port", "frontend_port"):
                value = data.get(key)
                if isinstance(value, int) and value not in ports:
                    ports.append(value)
    except Exception:  # noqa: BLE001
        pass
    return ports


def log(msg: str = "") -> None:
    print(msg, flush=True)


def listening_pids(port: int) -> set[str]:
    """返回监听指定端口的进程 PID 集合。"""
    try:
        out = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            errors="ignore",
        ).stdout
    except Exception:  # noqa: BLE001
        return set()

    pids: set[str] = set()
    for line in out.splitlines():
        if "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local_addr = parts[1]
        if local_addr.endswith(f":{port}"):
            pids.add(parts[-1])
    return pids


def kill_pid(pid: str) -> bool:
    try:
        if os.name == "nt":
            code = subprocess.call(
                ["taskkill", "/PID", pid, "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            code = subprocess.call(
                ["kill", "-9", pid],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return code == 0
    except Exception:  # noqa: BLE001
        return False


def main() -> None:
    log("=" * 46)
    log("  KnowledgeHub 停止")
    log("=" * 46)
    log("仅终止本项目端口（后端 8000 / 前端 5173）。")
    log("")

    found = False
    for port in resolve_ports():
        for pid in listening_pids(port):
            found = True
            log(f"正在终止端口 {port} 上的进程 PID={pid} ...")
            if kill_pid(pid):
                log("  已终止")
            else:
                log("  终止失败（可能需要管理员权限）")

    if not found:
        log("未发现本项目正在运行的服务。")
    else:
        log("")
        log("已停止。")

    try:
        RUNTIME_FILE.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass

    log("")


if __name__ == "__main__":
    main()
