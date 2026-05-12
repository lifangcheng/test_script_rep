#!/usr/bin/env python3
"""
start_can_agent.py
- 一键启动/调试 can-agent，减少手动步骤。
- 默认自动创建/复用虚拟环境并安装依赖（requirements.txt 更新后自动重新安装）。
- 支持三种模式：api（FastAPI 服务）、cli（命令行处理 BLF+DBC）、quick-test（无 BLF 的快速自检）。
- 新增端口占用检查：启动前可自动杀掉已占用端口的 uvicorn 进程。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parent
DEFAULT_VENV = ROOT / ".venv"
DEPS_MARKER = ".can_agent_deps_installed"


def is_windows() -> bool:
    return os.name == "nt"


def venv_python(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/python.exe" if is_windows() else "bin/python")


def ensure_venv(venv_dir: Path) -> Path:
    if not venv_dir.exists():
        print(f"[setup] 创建虚拟环境: {venv_dir}")
        venv.create(venv_dir, with_pip=True)
    py = venv_python(venv_dir)
    if not py.exists():
        raise RuntimeError(f"虚拟环境的 python 不存在: {py}")
    return py


def reexec_in(py: Path) -> None:
    env = os.environ.copy()
    env.setdefault("CAN_AGENT_BOOTSTRAPPED", "1")
    cmd = [str(py), str(Path(__file__).resolve())] + sys.argv[1:]
    print(f"[setup] 进入虚拟环境并重新执行: {' '.join(cmd)}")
    os.execvpe(str(py), cmd, env)


def install_deps(py: Path, requirements: Path, marker: Path, skip_install: bool) -> None:
    if skip_install:
        print("[setup] 跳过依赖安装（由 --skip-install 指定）")
        return

    needs_install = (not marker.exists()) or (
        requirements.exists() and marker.stat().st_mtime < requirements.stat().st_mtime
    )
    if not needs_install:
        print("[setup] 依赖已是最新，无需安装")
        return

    print(f"[setup] 安装依赖: {requirements}")
    subprocess.check_call([str(py), "-m", "pip", "install", "--upgrade", "pip"], cwd=ROOT)
    subprocess.check_call([str(py), "-m", "pip", "install", "-r", str(requirements)], cwd=ROOT)
    marker.touch()


def run_subprocess(cmd: Sequence[str]) -> int:
    print(f"[run] {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=ROOT)


def find_pids_on_port(port: int) -> list[str]:
    """Return list of PIDs listening on port (IPv4). Windows-only implementation using netstat/findstr."""
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"], shell=False, text=True, encoding="utf-8", errors="ignore"
        )
    except Exception as e:
        print(f"[port] netstat 查询失败: {e}")
        return []
    pids: set[str] = set()
    for line in out.splitlines():
        if f":{port} " in line or f":{port}\t" in line:
            parts = line.split()
            if parts and parts[-1].isdigit():
                pids.add(parts[-1])
    return list(pids)


def kill_pids(pids: list[str]) -> None:
    for pid in pids:
        try:
            print(f"[port] 终止占用进程 PID={pid}")
            subprocess.check_call(["taskkill", "/PID", pid, "/F"], shell=False)
        except subprocess.CalledProcessError as e:
            print(f"[port] 终止 PID={pid} 失败: {e}")


def ensure_port_free(port: int, auto_kill: bool) -> None:
    pids = find_pids_on_port(port)
    if not pids:
        print(f"[port] 端口 {port} 空闲")
        return
    if not auto_kill:
        print(f"[port] 端口 {port} 被占用，PID={','.join(pids)}。可加 --kill-port 自动杀掉。")
        sys.exit(1)
    kill_pids(pids)


def run_api(py: Path, host: str, port: int, reload: bool, kill_port: bool) -> int:
    ensure_port_free(port, auto_kill=kill_port)
    cmd = [str(py), "-m", "uvicorn", "app.main:app", "--host", host, "--port", str(port)]
    if reload:
        cmd.append("--reload")
    return run_subprocess(cmd)


def run_cli(
    py: Path,
    blf: str,
    dbc: str,
    out: str,
    config: str,
    ai: bool,
    skills_dir: str | None,
    slice_window_sec: float | None,
    slice_format: str | None,
) -> int:
    cmd = [
        str(py),
        str(ROOT / "cli.py"),
        "--blf",
        blf,
        "--dbc",
        dbc,
        "--out",
        out,
    ]
    if config:
        cmd += ["--config", config]
    if skills_dir:
        cmd += ["--skills-dir", skills_dir]
    if slice_window_sec is not None:
        cmd += ["--slice-window-sec", str(slice_window_sec)]
    if slice_format is not None:
        cmd += ["--slice-format", slice_format]
    if ai:
        cmd.append("--ai")
    return run_subprocess(cmd)


def run_quick_test(py: Path) -> int:
    cmd = [str(py), str(ROOT / "quick_test.py")]
    return run_subprocess(cmd)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap & start can-agent")
    parser.add_argument(
        "--venv",
        default=str(DEFAULT_VENV),
        help="虚拟环境路径（默认 .venv）",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="跳过依赖安装（假设依赖已满足）",
    )
    parser.add_argument(
        "--use-system-python",
        action="store_true",
        help="使用当前 python，不自动创建/进入虚拟环境",
    )
    parser.add_argument(
        "--kill-port",
        action="store_true",
        help="启动前自动杀掉占用端口的进程（Windows 使用 taskkill）",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    api = sub.add_parser("api", help="启动 FastAPI 服务")
    api.add_argument("--host", default="0.0.0.0", help="监听地址")
    api.add_argument("--port", type=int, default=8000, help="监听端口")
    api.add_argument("--reload", action="store_true", help="启用代码热重载")

    cli = sub.add_parser("cli", help="直接运行 CLI 流程")
    cli.add_argument("--blf", required=True, help="BLF 文件路径")
    cli.add_argument("--dbc", required=True, help="DBC 文件路径")
    cli.add_argument("--out", default="outputs", help="输出目录")
    cli.add_argument("--config", default="", help="可选配置 YAML 路径")
    cli.add_argument("--skills-dir", default="", help="技能目录 (rules/knowledge)")
    cli.add_argument("--slice-window-sec", type=float, default=None, help="异常窗口秒数")
    cli.add_argument("--slice-format", choices=["csv", "json"], default=None, help="窗口序列化格式")
    cli.add_argument("--ai", action="store_true", help="启用 AI 分析")

    sub.add_parser("quick-test", help="运行快速自检脚本（无 BLF）")

    return parser


def main(argv: Sequence[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    venv_dir = Path(args.venv).resolve()
    requirements = ROOT / "requirements.txt"
    marker = venv_dir / DEPS_MARKER

    if args.use_system_python:
        python_exe = Path(sys.executable)
    else:
        python_exe = ensure_venv(venv_dir)
        if Path(sys.executable).resolve() != python_exe.resolve():
            reexec_in(python_exe)

    if not args.use_system_python:
        install_deps(python_exe, requirements, marker, args.skip_install)

    if args.command == "api":
        return run_api(python_exe, host=args.host, port=args.port, reload=args.reload, kill_port=args.kill_port)
    if args.command == "cli":
        return run_cli(
            python_exe,
            blf=args.blf,
            dbc=args.dbc,
            out=args.out,
            config=args.config,
            ai=args.ai,
            skills_dir=args.skills_dir,
            slice_window_sec=args.slice_window_sec,
            slice_format=args.slice_format,
        )
    if args.command == "quick-test":
        return run_quick_test(python_exe)

    parser.error("Unknown command")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
