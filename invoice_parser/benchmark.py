"""显式触发的 API 并发基准和本地 JSONL 解析基准。"""

import json
import random
from datetime import datetime
from pathlib import Path
from time import perf_counter
from collections.abc import Sequence

from invoice_parser.batch import discover_images, run_batch
from invoice_parser.config import (
    BENCHMARK_RANDOM_SEED,
    BENCHMARK_SAMPLE_SIZE,
    BENCHMARK_WORKER_COUNTS,
    DATASET_DIR,
    OUTPUT_DIR,
    PARSER_BENCHMARK_REPEATS,
)
from invoice_parser.extractor import extract_invoice_data
from invoice_parser.outputs import get_input_file_stem


def benchmark_parser(jsonl_paths: Sequence[Path], repeats: int = PARSER_BENCHMARK_REPEATS) -> dict:
    """在内存中重复解析已缓存 JSONL，计时不包含文件读取和 API 调用。"""
    if repeats < 1:
        raise ValueError("解析基准 repeats 必须至少为 1。")

    cached_texts = [path.read_text(encoding="utf-8") for path in jsonl_paths]
    if not cached_texts:
        return {
            "documents": 0,
            "repeats": repeats,
            "elapsed_seconds": 0.0,
            "documents_per_second": 0.0,
            "pages_per_second": 0.0,
        }

    start = perf_counter()
    pages_per_pass = 0
    for _ in range(repeats):
        pages_per_pass = sum(len(extract_invoice_data(text)) for text in cached_texts)
    elapsed = perf_counter() - start
    document_count = len(cached_texts) * repeats
    page_count = pages_per_pass * repeats
    return {
        "documents_per_pass": len(cached_texts),
        "pages_per_pass": pages_per_pass,
        "repeats": repeats,
        "elapsed_seconds": elapsed,
        "average_seconds_per_pass": elapsed / repeats,
        "documents_per_second": document_count / elapsed if elapsed else 0.0,
        "pages_per_second": page_count / elapsed if elapsed else 0.0,
    }


def run_benchmark(
    *,
    input_dir: Path = DATASET_DIR,
    sample_size: int = BENCHMARK_SAMPLE_SIZE,
    worker_counts: Sequence[int] = BENCHMARK_WORKER_COUNTS,
) -> Path:
    """对固定样本运行 API 并发档位，并复用结果测本地解析耗时。"""
    images = discover_images(input_dir)
    if sample_size < 1 or sample_size > len(images):
        raise ValueError(f"sample_size 应在 1 到 {len(images)} 之间。")
    normalized_workers = tuple(dict.fromkeys(worker_counts))
    if not normalized_workers or any(workers < 1 for workers in normalized_workers):
        raise ValueError("worker_counts 必须是一个或多个正整数。")

    # 固定随机种子让每次手动基准使用同一组图片，便于比较不同并发档位。
    sample = sorted(
        random.Random(BENCHMARK_RANDOM_SEED).sample(images, sample_size),
        key=lambda path: path.as_posix().casefold(),
    )
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / "benchmarks" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    api_runs = []
    parser_jsonl_paths: list[Path] = []
    for workers in normalized_workers:
        worker_dir = run_dir / f"workers_{workers}"
        started = perf_counter()
        results = run_batch(sample, workers=workers, output_dir=worker_dir, save_raw=True)
        elapsed = perf_counter() - started
        successes = sum(result["success"] for result in results)
        failures = len(results) - successes
        api_runs.append(
            {
                "workers": workers,
                "image_count": len(sample),
                "success_count": successes,
                "failure_count": failures,
                "elapsed_seconds": elapsed,
                "average_seconds_per_image": elapsed / len(sample),
                "images_per_second": successes / elapsed if elapsed else 0.0,
                "results": results,
            }
        )

        # 只从第一个并发档位的缓存结果做离线解析基准，不再次请求 OCR API。
        if workers == normalized_workers[0]:
            for image in sample:
                jsonl_path = worker_dir / f"ocr_result_{get_input_file_stem(str(image))}.jsonl"
                if jsonl_path.is_file():
                    parser_jsonl_paths.append(jsonl_path)

    report = {
        "run_id": run_id,
        "sample_size": sample_size,
        "sample_files": [str(path) for path in sample],
        "worker_counts": list(normalized_workers),
        "api_runs": api_runs,
        "offline_parser": benchmark_parser(parser_jsonl_paths),
    }
    report_path = run_dir / "benchmark_summary.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"基准报告已保存：{report_path}")
    return report_path
