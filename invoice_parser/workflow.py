"""编排单个票据从 API 识别到本地结果保存的完整流程。"""

from pathlib import Path

from invoice_parser.api import (
    download_ocr_result_text,
    get_api_headers,
    submit_ocr_job,
    wait_for_ocr_result,
)
from invoice_parser.config import OUTPUT_DIR, SAVE_RAW_JSONL, SAVE_RESULT_FILES
from invoice_parser.outputs import (
    print_and_save_invoice_data,
    save_parsed_ocr_results,
    save_raw_jsonl,
)


def process_invoice(
    file_path: str,
    *,
    output_dir: Path = OUTPUT_DIR,
    print_json: bool = True,
    save_raw: bool | None = None,
) -> str:
    """提交一张票据识别任务，保存结果并返回原始 JSONL 文本。"""
    headers = get_api_headers()
    job_id = submit_ocr_job(file_path, headers)
    result_url = wait_for_ocr_result(job_id, headers)
    jsonl_text = download_ocr_result_text(result_url)

    should_save_raw = SAVE_RAW_JSONL if save_raw is None else save_raw
    if should_save_raw:
        save_raw_jsonl(jsonl_text, file_path, output_dir)
    print_and_save_invoice_data(jsonl_text, file_path, output_dir, print_json=print_json)

    if SAVE_RESULT_FILES:
        save_parsed_ocr_results(jsonl_text, file_path, output_dir)
    else:
        print("Markdown 和图片输出开关已关闭，未保存这三类结果文件。")
    return jsonl_text
