"""OCR 原始结果、结构化 JSON 及可选 Markdown/图像的本地输出。"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from invoice_parser.config import OUTPUT_DIR
from invoice_parser.extractor import extract_invoice_data


def get_input_file_stem(file_path: str) -> str:
    """从本地路径或 URL 中提取文件名主干，用于区分不同输入的结果文件。"""
    if file_path.lower().startswith(("http://", "https://")):
        filename = Path(unquote(urlparse(file_path).path)).name
    else:
        filename = Path(file_path).name
    stem = Path(filename).stem
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .")
    return stem or "invoice"


def save_raw_jsonl(
    jsonl_text: str,
    file_path: str,
    output_dir: Path = OUTPUT_DIR,
) -> Path:
    """按输入图片名保存 API 返回的原始 JSONL 文本。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / f"ocr_result_{get_input_file_stem(file_path)}.jsonl"
    jsonl_path.write_text(jsonl_text, encoding="utf-8")
    print(f"原始 JSONL 结果已保存：{jsonl_path}")
    return jsonl_path


def print_and_save_invoice_data(
    jsonl_text: str,
    file_path: str,
    output_dir: Path = OUTPUT_DIR,
    *,
    print_json: bool = True,
) -> Path:
    """将字段化发票数据输出到控制台，并按输入图片名保存为 JSON。"""
    invoice_data = extract_invoice_data(jsonl_text)
    json_text = json.dumps(invoice_data, ensure_ascii=False, indent=2)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"invoice_data_{get_input_file_stem(file_path)}.json"
    json_path.write_text(json_text + "\n", encoding="utf-8")

    if print_json:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print("提取到的发票结构数据：")
        print(json_text)
    print(f"纯净版发票 JSON 已保存：{json_path}")
    return json_path


def save_parsed_ocr_results(
    jsonl_text: str,
    file_path: str,
    output_dir: Path = OUTPUT_DIR,
) -> None:
    """解析 JSONL 文本，并将 Markdown 和相关图片写入 output/。"""
    # 每个输入文件使用独立子目录，避免批处理中 doc_0.md 和图片相互覆盖。
    document_dir = output_dir / get_input_file_stem(file_path)
    document_dir.mkdir(parents=True, exist_ok=True)
    page_number = 0
    for line_number, line in enumerate(jsonl_text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            result_data = json.loads(line)["result"]
        except (json.JSONDecodeError, KeyError) as error:
            raise RuntimeError(f"第 {line_number} 行结果格式无效。") from error

        for page_result in result_data.get("layoutParsingResults", []):
            markdown_data = page_result.get("markdown", {})
            markdown_path = document_dir / f"doc_{page_number}.md"
            markdown_path.write_text(markdown_data.get("text", ""), encoding="utf-8")
            print(f"Markdown 结果已保存：{markdown_path}")

            for image_path, image_url in markdown_data.get("images", {}).items():
                local_image_path = document_dir / image_path
                local_image_path.parent.mkdir(parents=True, exist_ok=True)
                image_response = requests.get(image_url)
                image_response.raise_for_status()
                local_image_path.write_bytes(image_response.content)
                print(f"图片已保存：{local_image_path}")

            for image_name, image_url in page_result.get("outputImages", {}).items():
                image_response = requests.get(image_url)
                image_response.raise_for_status()
                local_image_path = document_dir / f"{image_name}_{page_number}.jpg"
                local_image_path.write_bytes(image_response.content)
                print(f"解析图像已保存：{local_image_path}")
            page_number += 1
