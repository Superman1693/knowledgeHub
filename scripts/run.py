"""KnowledgeHub 本地启动入口（跨平台）。

用法：
    python scripts/run.py                # 完整启动：检查环境 → 装依赖 → 迁移 → 启动前后端
    python scripts/run.py --no-install   # 跳过依赖安装检查

Windows 下由 scripts/start.bat 调用本脚本。
批处理文件保持纯 ASCII，中文提示全部由 Python 输出，
以避免中文在 GBK 控制台下导致 .bat 乱码与语法破坏。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

# ---------------- 输出编码 ----------------
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = "8000"
FRONTEND_PORT = "5173"

# 记录实际使用的端口，供 scripts/stop.py 精确停止
RUNTIME_FILE = ROOT / ".kh_runtime.json"

SKIP_INSTALL = "--no-install" in sys.argv

# pip 源候选：先默认源，失败再切国内镜像（直连 PyPI 可能极慢）
PIP_MIRRORS: list[str | None] = [
    None,
    "https://mirrors.aliyun.com/pypi/simple/",
    "https://pypi.tuna.tsinghua.edu.cn/simple/",
]


def log(msg: str = "") -> None:
    print(msg, flush=True)


def step(n: int, total: int, msg: str) -> None:
    log(f"[{n}/{total}] {msg}")


def venv_python() -> Path:
    if os.name == "nt":
        return BACKEND / ".venv" / "Scripts" / "python.exe"
    return BACKEND / ".venv" / "bin" / "python"


def run(cmd: list[str], cwd: Path | None = None, quiet: bool = False) -> int:
    return subprocess.call(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.DEVNULL if quiet else None,
    )


def check_environment() -> bool:
    ok = True
    if not shutil.which("python") and not Path(sys.executable).exists():
        log("[错误] 未找到 Python，请先安装 Python 3.11 或更高版本。")
        ok = False
    if not shutil.which("node"):
        log("[错误] 未找到 Node.js，请先安装 Node.js 18 或更高版本。")
        ok = False
    return ok


def ensure_env_file() -> None:
    env = ROOT / ".env"
    example = ROOT / ".env.example"
    if env.exists():
        return
    if example.exists():
        env.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        log("[提示] 已从 .env.example 生成 .env，请按需修改数据库密码 DB_PASSWORD。")


def ensure_backend_venv() -> Path:
    py = venv_python()
    if py.exists():
        return py
    log("[提示] 正在创建后端虚拟环境 backend/.venv ...")
    code = run([sys.executable, "-m", "venv", str(BACKEND / ".venv")])
    if code != 0 or not py.exists():
        log("[错误] 创建虚拟环境失败。")
        sys.exit(1)
    return py


def backend_deps_ok(py: Path) -> bool:
    return run([str(py), "-c", "import fastapi, sqlalchemy, pgvector"], quiet=True) == 0


def install_backend_deps(py: Path) -> bool:
    req = BACKEND / "requirements.txt"
    for index in PIP_MIRRORS:
        cmd = [str(py), "-m", "pip", "install", "-r", str(req)]
        if index:
            log(f"[提示] 尝试镜像源：{index}")
            cmd += ["-i", index]
        else:
            log("[提示] 尝试默认源（若过慢会自动切换国内镜像）...")
        if run(cmd) == 0 and backend_deps_ok(py):
            return True
    return False


def frontend_deps_ok() -> bool:
    return (FRONTEND / "node_modules").exists()


def install_frontend_deps() -> bool:
    npm = "npm.cmd" if os.name == "nt" else "npm"
    log("[提示] 正在安装前端依赖（首次较慢）...")
    return run(
        [npm, "install", "--registry=https://registry.npmmirror.com", "--no-audit", "--no-fund"],
        cwd=FRONTEND,
    ) == 0


def migrate(py: Path) -> bool:
    code = run([str(py), "-m", "alembic", "upgrade", "head"], cwd=BACKEND)
    if code != 0:
        log("")
        log("[错误] 数据库迁移失败。请检查：")
        log("       1) PostgreSQL 是否已启动（默认 127.0.0.1:5432）")
        log("       2) .env 中的 DB_USER / DB_PASSWORD 是否正确")
        log("       3) 是否已建库：psql -U postgres -f scripts/init_db.sql")
        return False
    return True


def find_free_port(preferred: int, host: str = "127.0.0.1", span: int = 20) -> int:
    """从 preferred 起找一个空闲端口；找不到则返回原值。

    注意：不设置 SO_REUSEADDR，否则 Windows 下会误判已占用端口为空闲。
    """
    for port in range(preferred, preferred + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    return preferred


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
            return False
        except OSError:
            return True


def start_services(py: Path) -> None:
    backend_port = find_free_port(int(BACKEND_PORT))
    frontend_port = find_free_port(int(FRONTEND_PORT))

    if backend_port != int(BACKEND_PORT):
        log(
            f"[提示] 端口 {BACKEND_PORT} 已被其他程序占用，"
            f"后端改用 {backend_port}。"
        )
    if frontend_port != int(FRONTEND_PORT):
        log(
            f"[提示] 端口 {FRONTEND_PORT} 已被其他程序占用，"
            f"前端改用 {frontend_port}。"
        )

    log("")
    log("=" * 46)
    log("  正在启动服务 ...")
    log(f"  前端地址：http://{BACKEND_HOST}:{frontend_port}")
    log(f"  后端接口：http://{BACKEND_HOST}:{backend_port}/docs")
    log("  按 Ctrl+C 停止（或运行 scripts/stop.bat）")
    log("=" * 46)
    log("")

    backend_proc = subprocess.Popen(
        [
            str(py),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            BACKEND_HOST,
            "--port",
            str(backend_port),
        ],
        cwd=str(BACKEND),
    )

    # 把端口注入前端，让 Vite 的代理指向正确的后端
    frontend_env = os.environ.copy()
    frontend_env["KH_BACKEND_PORT"] = str(backend_port)
    frontend_env["KH_FRONTEND_PORT"] = str(frontend_port)

    npm = "npm.cmd" if os.name == "nt" else "npm"
    frontend_proc = subprocess.Popen(
        [npm, "run", "dev"],
        cwd=str(FRONTEND),
        env=frontend_env,
    )

    # 记录实际端口，供 stop.py 使用
    try:
        RUNTIME_FILE.write_text(
            json.dumps(
                {"backend_port": backend_port, "frontend_port": frontend_port},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass

    try:
        backend_proc.wait()
    except KeyboardInterrupt:
        log("")
        log("[提示] 正在停止服务 ...")
        for proc in (backend_proc, frontend_proc):
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
    finally:
        try:
            RUNTIME_FILE.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    total = 6
    log("=" * 46)
    log("  KnowledgeHub 本地启动")
    log("=" * 46)

    step(1, total, "检查运行环境 ...")
    if not check_environment():
        sys.exit(1)

    step(2, total, "检查配置文件 ...")
    ensure_env_file()

    step(3, total, "准备后端虚拟环境 ...")
    py = ensure_backend_venv()

    if SKIP_INSTALL:
        log("[4/6] 跳过依赖安装检查（--no-install）")
    else:
        step(4, total, "检查依赖 ...")
        if not backend_deps_ok(py):
            if not install_backend_deps(py):
                log("[错误] 后端依赖安装失败。可手动执行：")
                log(
                    f"       {py} -m pip install -r backend/requirements.txt "
                    "-i https://mirrors.aliyun.com/pypi/simple/"
                )
                sys.exit(1)
        else:
            log("      后端依赖已就绪")

        if not frontend_deps_ok():
            if not install_frontend_deps():
                log("[错误] 前端依赖安装失败，请进入 frontend/ 手动执行 npm install。")
                sys.exit(1)
        else:
            log("      前端依赖已就绪")

    step(5, total, "应用数据库迁移 ...")
    if not migrate(py):
        sys.exit(1)

    step(6, total, "启动前后端服务 ...")
    start_services(py)


if __name__ == "__main__":
    main()
