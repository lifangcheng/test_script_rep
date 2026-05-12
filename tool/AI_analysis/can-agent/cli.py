from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from graph.builder import compile_graph
from graph.state import CANState
from utils.io import ensure_dir, write_json


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists() and src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="CAN Agent CLI")
    p.add_argument("--blf", required=True, help="Path to .blf")
    p.add_argument("--dbc", required=True, help="Path to .dbc")
    p.add_argument("--out", default="outputs", help="Output directory")
    p.add_argument("--config", default="", help="YAML config path")
    p.add_argument("--skills-dir", default="", help="Skills directory (rules.yaml, knowledge.txt)")
    p.add_argument("--slice-window-sec", type=float, default=None, help="Window seconds before/after anomaly")
    p.add_argument("--slice-format", choices=["csv", "json"], default=None, help="Slice serialization format")
    p.add_argument("--ai", action="store_true", help="Enable AI analysis")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    out_root = Path(args.out).resolve()
    if out_root.suffix:
        raise SystemExit("--out must be a directory path, not a file path")

    blf_stem = Path(args.blf).stem
    out_dir_path = out_root / blf_stem
    out_dir = str(out_dir_path)
    ensure_dir(out_dir)

    print(f"开始处理CAN数据...")
    print(f"BLF文件: {args.blf}")
    print(f"DBC文件: {args.dbc}")
    print(f"输出目录: {out_dir}")
    print(f"AI分析: {'启用' if args.ai else '禁用'}")

    cfg: dict = {"config_path": args.config} if args.config else {}
    if args.skills_dir:
        cfg.setdefault("skills", {})["dir"] = str(Path(args.skills_dir).resolve())
    if args.slice_window_sec is not None:
        cfg.setdefault("slice", {})["window_sec"] = float(args.slice_window_sec)
    if args.slice_format is not None:
        cfg.setdefault("slice", {})["format"] = args.slice_format

    state = CANState(
        blf_path=str(Path(args.blf).resolve()),
        dbc_path=str(Path(args.dbc).resolve()),
        config=cfg,
        enable_ai=bool(args.ai),
        output_dir=out_dir,
    )

    try:
        print(f"\n正在初始化处理流程...")
        app = compile_graph()

        print(f"正在执行处理流程...")
        final_state = app.invoke(state)

        # langgraph may return a dict-like state depending on version/config.
        if isinstance(final_state, dict):
            status_payload = {
                "status": final_state.get("status", "unknown"),
                "error": final_state.get("error"),
                "logs": final_state.get("logs", []),
            }
        else:
            status_payload = {
                "status": final_state.status,
                "error": final_state.error,
                "logs": final_state.logs,
            }

        if status_payload.get("status") in {"created", "running"}:
            status_payload["status"] = "success"

        report_html = Path(out_dir) / "report.html"
        report_json = Path(out_dir) / "report.json"
        status_payload = dict(status_payload)
        status_payload.update(
            {
                "blf": str(Path(args.blf).resolve()),
                "dbc": str(Path(args.dbc).resolve()),
                "out_dir": out_dir,
                "report_html": str(report_html) if report_html.exists() else None,
                "report_json": str(report_json) if report_json.exists() else None,
            }
        )

        try:
            if report_json.exists():
                rj = json.loads(report_json.read_text(encoding="utf-8"))
                if isinstance(rj, dict):
                    stats = rj.get("stats") or {}
                    status_payload["signals_count"] = stats.get("signals")
                    status_payload["anomalies_count"] = stats.get("anomalies")
        except Exception:
            pass

        write_json(f"{out_dir}/status.json", status_payload)

        artifacts = Path(out_dir) / "artifacts"
        _copy_if_exists(Path(out_dir) / "report.html", artifacts / "report.html")
        _copy_if_exists(Path(out_dir) / "report.json", artifacts / "report.json")
        _copy_if_exists(Path(out_dir) / "graph.html", artifacts / "graph.html")
        _copy_if_exists(Path(out_dir) / "status.json", artifacts / "status.json")

        error = status_payload.get("error") or {}
        _write_text(
            artifacts / "summary.md",
            "\n".join(
                [
                    f"blf: {Path(args.blf).resolve()}",
                    f"dbc: {Path(args.dbc).resolve()}",
                    f"out: {out_dir}",
                    f"status: {status_payload.get('status')}",
                    f"error_code: {error.get('code') if isinstance(error, dict) else ''}",
                    f"error_stage: {error.get('stage') if isinstance(error, dict) else ''}",
                ]
            )
            + "\n",
        )

        # 输出详细的处理日志
        print(f"\n处理结果:")
        for log in status_payload.get("logs", []):
            stage = log.get("stage", "unknown")
            status = log.get("status", "unknown")
            error = log.get("error")

            if status == "success":
                print(f"  {stage}: 成功")
            elif status == "failed":
                print(f"  {stage}: 失败")
                if error:
                    print(f"     错误代码: {error.get('code', 'unknown')}")
                    print(f"     错误信息: {error.get('message', 'unknown')}")
                    print(f"     修复建议: {error.get('fix', 'unknown')}")
            elif status == "running":
                print(f"  {stage}: 运行中...")

        if status_payload["status"] == "failed":
            print(f"\n处理失败!")
            if status_payload.get("error"):
                error = status_payload["error"]
                print(f"失败阶段: {error.get('stage', 'unknown')}")
                print(f"错误代码: {error.get('code', 'unknown')}")
                print(f"错误信息: {error.get('message', 'unknown')}")
                print(f"修复建议: {error.get('fix', 'unknown')}")

            sys.stderr.write(json.dumps(status_payload, ensure_ascii=False, indent=2) + "\n")
            return 2

        print(f"\n处理成功完成!")
        print(f"输出文件保存在: {out_dir}")

        # 列出生成的文件
        output_files = list(Path(out_dir).glob("*"))
        if output_files:
            print(f"生成的文件:")
            for file in output_files:
                print(f"  - {file.name}")

        sys.stdout.write(json.dumps(status_payload, ensure_ascii=False, indent=2) + "\n")
        return 0

    except Exception as e:
        print(f"\n程序执行异常: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
