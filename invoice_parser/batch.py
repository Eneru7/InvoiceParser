"""图片目录扫描及有界线程池批处理。"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from collections.abc import Sequence

from invoice_parser.config import (
    MAX_WORKERS,
    OUTPUT_DIR,
    SUPPORTED_IMAGE_EXTENSIONS,
)
from invoice_parser.outputs import get_input_file_stem
from invoice_parser.workflow import process_invoice


@dataclass
class FileResult:
    """单个输入文件的处理状态与耗时。"""

    file_path: str
    success: bool
    elapsed_seconds: float
    error: str | None = None


def discover_images(input_dir: Path) -> list[Path]:
    """递归扫描目录中的支持格式图片并按路径排序。"""
    if not input_dir.is_dir():
        raise NotADirectoryError(f"输入目录不存在：{input_dir}")
    images = sorted(
        (
            path
            for path in input_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
        ),
        key=lambda path: path.as_posix().casefold(),
    )
    if not images:
        raise FileNotFoundError(f"目录中没有支持的图片：{input_dir}")
    return images


def validate_output_names(file_paths: Sequence[str | Path]) -> None:
    """批处理开始前检查输出文件主干名，阻止同名输入互相覆盖。"""
    stems: dict[str, str] = {}
    for file_path in file_paths:
        stem = get_input_file_stem(str(file_path)).casefold()
        if stem in stems:
            raise ValueError(
                f"输出文件名冲突：{stems[stem]} 与 {file_path} 的文件主干相同（{stem}）。"
            )
        stems[stem] = str(file_path)


def _process_one(
    file_path: str,
    output_dir: Path,
    save_raw: bool | None,
) -> FileResult:
    start = perf_counter()
    try:
        process_invoice(
            file_path,
            output_dir=output_dir,
            print_json=False,
            save_raw=save_raw,
        )
        return FileResult(file_path, True, perf_counter() - start)
    except Exception as error:  # 单张失败不应取消其他 Future。
        return FileResult(file_path, False, perf_counter() - start, str(error))


def run_batch(
    file_paths: Sequence[str | Path],
    *,
    workers: int = MAX_WORKERS,
    output_dir: Path = OUTPUT_DIR,
    save_raw: bool | None = None,
) -> list[dict]:
    """使用有界线程池处理一组图片，并返回按完成顺序排列的结果摘要。"""
    if workers < 1:
        raise ValueError("并发数 workers 必须至少为 1。")
    if not file_paths:
        raise ValueError("没有可处理的输入图片。")
    validate_output_names(file_paths)

    results: list[FileResult] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="invoice-ocr") as executor:
        futures = {
            executor.submit(_process_one, str(file_path), output_dir, save_raw): str(file_path)
            for file_path in file_paths
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if result.success:
                print(f"完成：{result.file_path}（{result.elapsed_seconds:.2f} 秒）")
            else:
                print(f"失败：{result.file_path}：{result.error}")
    return [asdict(result) for result in results]
