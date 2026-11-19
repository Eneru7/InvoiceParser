"""编排单个票据从 API 识别到本地结果保存的完整流程。"""

from invoice_parser.api import (
    download_ocr_result_text,
    get_api_headers,
    submit_ocr_job,
    wait_for_ocr_result,
)
from invoice_parser.config import SAVE_RAW_JSONL, SAVE_RESULT_FILES
from invoice_parser.outputs import (
    print_and_save_invoice_data,
    save_parsed_ocr_results,
    save_raw_jsonl,
)


def process_invoice(file_path: str) -> None:
    """提交一张票据识别任务，等待完成并按配置保存结果。"""
    headers = get_api_headers()
    job_id = submit_ocr_job(file_path, headers)
    result_url = wait_for_ocr_result(job_id, headers)
    jsonl_text = download_ocr_result_text(result_url)

    if SAVE_RAW_JSONL:
        save_raw_jsonl(jsonl_text, file_path)
    print_and_save_invoice_data(jsonl_text, file_path)

    if SAVE_RESULT_FILES:
        save_parsed_ocr_results(jsonl_text)
    else:
        print("Markdown 和图片输出开关已关闭，未保存这三类结果文件。")
