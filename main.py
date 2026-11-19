"""项目命令行入口：调用 PaddleOCR API 识别配置的票据图片。"""

import sys

import requests

from invoice_parser.config import FILE_PATH, OUTPUT_DIR, SAVE_RAW_JSONL, SAVE_RESULT_FILES
from invoice_parser.workflow import process_invoice


def main() -> int:
    """运行一次票据识别流程，并返回进程退出码。"""
    try:
        process_invoice(FILE_PATH)
    except (FileNotFoundError, requests.RequestException, RuntimeError) as error:
        print(f"处理失败：{error}", file=sys.stderr)
        return 1

    if SAVE_RESULT_FILES:
        print(f"全部结果已保存到：{OUTPUT_DIR}")
    elif SAVE_RAW_JSONL:
        print(f"JSONL 文本已保存到：{OUTPUT_DIR}（文件名带输入图片名）")
    return 0


# 只有直接运行本文件时才启动识别；作为模块导入时不会请求 API。
if __name__ == "__main__":
    sys.exit(main())
