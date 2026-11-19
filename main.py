"""命令行入口：单文件识别、目录并发识别和显式性能基准。"""

import argparse
import sys
from pathlib import Path
from time import perf_counter

import requests

from invoice_parser.batch import discover_images, run_batch
from invoice_parser.benchmark import run_benchmark
from invoice_parser.config import (
    DATASET_DIR,
    FILE_PATH,
    MAX_WORKERS,
    OUTPUT_DIR,
    SAVE_RAW_JSONL,
    SAVE_RESULT_FILES,
)
from invoice_parser.workflow import process_invoice


def _parse_worker_counts(value: str) -> tuple[int, ...]:
    """解析逗号分隔的并发档位，例如 1,2,4。"""
    try:
        counts = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as error:
        raise argparse.ArgumentTypeError("并发档位必须是逗号分隔的正整数，例如 1,2,4。") from error
    if not counts or any(count < 1 for count in counts):
        raise argparse.ArgumentTypeError("并发档位必须包含一个或多个正整数。")
    return counts


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="使用 PaddleOCR API 识别票据并提取发票数据。")
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--input", help="处理单张本地图片或图片 URL；默认使用 config.py 中的 FILE_PATH。")
    input_group.add_argument("--input-dir", type=Path, help="并发处理目录中的所有支持格式图片。")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help=f"批处理最大并发数，默认 {MAX_WORKERS}。")
    parser.add_argument("--benchmark", action="store_true", help="显式运行 API 并发和本地解析基准，会调用 OCR API。")
    parser.add_argument("--sample-size", type=int, default=10, help="基准测试图片数量，默认 10。")
    parser.add_argument("--worker-counts", type=_parse_worker_counts, default=(1, 2, 4), help="基准并发档位，如 1,2,4。")
    parser.add_argument("--benchmark-dir", type=Path, default=DATASET_DIR, help="基准样本图片目录。")
    return parser


def main() -> int:
    """解析命令行参数并启动单文件、批量或基准流程。"""
    parser = _build_argument_parser()
    args = parser.parse_args()

    if args.benchmark and (args.input or args.input_dir):
        parser.error("--benchmark 不能与 --input 或 --input-dir 同时使用。")

    try:
        if args.benchmark:
            run_benchmark(
                input_dir=args.benchmark_dir,
                sample_size=args.sample_size,
                worker_counts=args.worker_counts,
            )
            return 0

        if args.input_dir:
            image_paths = discover_images(args.input_dir)
            batch_started = perf_counter()
            results = run_batch(image_paths, workers=args.workers)
            wall_elapsed = perf_counter() - batch_started
            successes = sum(result["success"] for result in results)
            failures = len(results) - successes
            print(
                f"批处理完成：成功 {successes}，失败 {failures}，"
                f"墙钟耗时 {wall_elapsed:.2f} 秒。"
            )
            return 1 if failures else 0

        file_path = args.input or FILE_PATH
        process_invoice(file_path)
        if SAVE_RESULT_FILES:
            print(f"全部结果已保存到：{OUTPUT_DIR}")
        elif SAVE_RAW_JSONL:
            print(f"JSONL 文本已保存到：{OUTPUT_DIR}（文件名带输入图片名）")
        return 0
    except (OSError, ValueError, RuntimeError, requests.RequestException) as error:
        print(f"处理失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
