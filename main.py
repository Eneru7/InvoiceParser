"""调用 PaddleOCR 云端 API 识别票据，并将解析结果保存到本地。"""

import json
import os
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

# PaddleOCR 任务 API 地址及使用的模型。
JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
MODEL = "PaddleOCR-VL-1.6"

# API Token 通过用户环境变量配置，避免将凭证直接写入项目代码。
TOKEN_ENV_NAME = "PADDLEOCR_API_TOKEN"

# 将此处改为要识别的图片路径，也可以填写可访问的图片 URL。
# 本地图片建议放在项目的 data/images/ 目录中。
FILE_PATH = "data/images/b0.jpg"

# 任务仍在排队或处理中时，两次查询之间的等待秒数。
POLL_INTERVAL_SECONDS = 5

# API 返回的 Markdown 与图片保存在项目根目录下的 output/ 中。
OUTPUT_DIR = Path("output")

# 结果文件保存总开关：默认关闭，不下载或保存 Markdown 和两类图片。
# 如需将识别结果写入 output/，请改为 True。
SAVE_RESULT_FILES = False

# JSONL 响应文本单独保存开关：默认开启，将 API 返回的原始 JSON 文本写入 output/。
SAVE_RAW_JSONL = True

# 这些可选能力在本示例中均关闭，可按需调整。
OPTIONAL_PAYLOAD = {
    "useDocOrientationClassify": False,
    "useDocUnwarping": False,
    "useChartRecognition": False,
}


def get_api_headers() -> dict[str, str]:
    """读取 API Token，并构造后续请求需要的认证请求头。"""
    token = os.getenv(TOKEN_ENV_NAME)
    if not token:
        raise RuntimeError(
            f"未设置环境变量 {TOKEN_ENV_NAME}。请设置该变量后重新启动运行程序的终端或 PyCharm。"
        )

    return {"Authorization": f"bearer {token}"}


def submit_ocr_job(file_path: str, headers: dict[str, str]) -> str:
    """提交图片识别任务，兼容本地图片文件和图片 URL。"""
    print(f"正在提交识别任务：{file_path}")

    if file_path.lower().startswith(("http://", "https://")):
        # URL 模式：把图片地址和模型参数作为 JSON 发送。
        request_headers = {**headers, "Content-Type": "application/json"}
        payload = {
            "fileUrl": file_path,
            "model": MODEL,
            "optionalPayload": OPTIONAL_PAYLOAD,
        }
        response = requests.post(JOB_URL, json=payload, headers=request_headers)
    else:
        # 本地文件模式：使用 multipart/form-data 上传图片。
        image_path = Path(file_path)
        if not image_path.is_file():
            raise FileNotFoundError(f"找不到图片文件：{image_path}")

        form_data = {
            "model": MODEL,
            "optionalPayload": json.dumps(OPTIONAL_PAYLOAD),
        }
        with image_path.open("rb") as image_file:
            response = requests.post(
                JOB_URL,
                headers=headers,
                data=form_data,
                files={"file": image_file},
            )

    # 对非成功状态码抛出异常，错误中会包含 HTTP 状态信息。
    response.raise_for_status()
    job_id = response.json().get("data", {}).get("jobId")
    if not job_id:
        raise RuntimeError("任务提交成功响应中没有找到 jobId。")

    print(f"任务提交成功，任务编号：{job_id}")
    return job_id


def wait_for_ocr_result(job_id: str, headers: dict[str, str]) -> str:
    """轮询任务状态，直到完成并返回结果 JSONL 文件的 URL。"""
    print("开始等待识别结果……")

    while True:
        response = requests.get(f"{JOB_URL}/{job_id}", headers=headers)
        response.raise_for_status()
        job_data = response.json().get("data", {})
        state = job_data.get("state")

        if state == "pending":
            print("任务正在排队等待处理。")
        elif state == "running":
            # 进度字段可能尚未返回，因此在缺少字段时显示一般状态。
            progress = job_data.get("extractProgress", {})
            total_pages = progress.get("totalPages")
            extracted_pages = progress.get("extractedPages")
            if total_pages is not None and extracted_pages is not None:
                print(f"任务处理中：已识别 {extracted_pages}/{total_pages} 页。")
            else:
                print("任务处理中……")
        elif state == "done":
            progress = job_data.get("extractProgress", {})
            extracted_pages = progress.get("extractedPages", "未知")
            print(f"任务完成，成功识别页数：{extracted_pages}。")

            result_url = job_data.get("resultUrl", {}).get("jsonUrl")
            if not result_url:
                raise RuntimeError("任务已完成，但响应中没有找到 JSONL 结果地址。")
            return result_url
        elif state == "failed":
            error_message = job_data.get("errorMsg", "未提供错误详情")
            raise RuntimeError(f"识别任务失败：{error_message}")
        else:
            raise RuntimeError(f"API 返回了无法识别的任务状态：{state!r}")

        time.sleep(POLL_INTERVAL_SECONDS)


def download_ocr_result_text(jsonl_url: str) -> str:
    """下载并返回 API 的 JSONL 文本响应。"""
    response = requests.get(jsonl_url)
    response.raise_for_status()
    return response.text


def get_input_file_stem(file_path: str) -> str:
    """从本地路径或 URL 中提取文件名主干，用于区分不同输入的结果文件。"""
    if file_path.lower().startswith(("http://", "https://")):
        filename = Path(unquote(urlparse(file_path).path)).name
    else:
        filename = Path(file_path).name

    stem = Path(filename).stem
    # 清除 Windows 文件名不允许的字符，防止 URL 文件名无法作为输出名。
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .")
    return stem or "invoice"


def save_raw_jsonl(jsonl_text: str, file_path: str) -> Path:
    """按输入图片名保存 API 返回的原始 JSONL 文本。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename_stem = get_input_file_stem(file_path)
    jsonl_path = OUTPUT_DIR / f"ocr_result_{filename_stem}.jsonl"
    jsonl_path.write_text(jsonl_text, encoding="utf-8")
    print(f"原始 JSONL 结果已保存：{jsonl_path}")
    return jsonl_path


class _InvoiceTableParser(HTMLParser):
    """将 OCR 返回的简单 HTML 表格转换成二维单元格数组。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _parse_table_rows(table_html: str) -> list[list[str]]:
    """解析表格 HTML，并将 OCR 字符串中的字面量换行符还原为换行。"""
    parser = _InvoiceTableParser()
    parser.feed(table_html.replace("\\n", "\n"))
    parser.close()
    return parser.rows


def _parse_labeled_lines(text: str) -> dict[str, str]:
    """把“字段名：字段值”形式的多行文字解析为字典。"""
    field_names = {
        "名称": "name",
        "纳税人识别号": "taxpayer_id",
        "地址、电话": "address_and_phone",
        "开户行及账号": "bank_and_account",
    }
    fields = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        separator = "：" if "：" in line else ":" if ":" in line else None
        if separator:
            key, value = line.split(separator, 1)
            if key.strip() and value.strip():
                source_key = key.strip()
                fields[field_names.get(source_key, source_key)] = value.strip()
    return fields


def _parse_invoice_table(table_html: str) -> dict:
    """从发票表格中提取买卖双方、密码区、商品明细、金额和备注。"""
    rows = _parse_table_rows(table_html)
    table_data = {
        "buyer": {},
        "seller": {},
        "items": [],
        "totals": {},
        "password_area": None,
        "remarks": None,
    }
    item_header = None

    for row in rows:
        if not row:
            continue
        first_cell = row[0].replace(" ", "")

        if first_cell == "购买方" and len(row) >= 2:
            table_data["buyer"] = _parse_labeled_lines(row[1])
            if len(row) >= 4 and row[2].strip() == "密码区":
                table_data["password_area"] = row[3].strip() or None
        elif first_cell == "销售方" and len(row) >= 2:
            table_data["seller"] = _parse_labeled_lines(row[1])
            if len(row) >= 4 and row[2].strip() == "备注":
                table_data["remarks"] = row[3].strip() or None

        if any("货物或应税劳务" in cell or "商品名称" in cell for cell in row):
            item_header = row
            continue

        if item_header:
            headers = [cell.replace("\n", "").strip() for cell in item_header]
            item_field_names = {
                "货物或应税劳务、服务名称": "name",
                "商品名称": "name",
                "规格型号": "specification",
                "单位": "unit",
                "数量": "quantity",
                "单价": "unit_price",
                "金额": "amount",
                "税率": "tax_rate",
                "税额": "tax_amount",
            }
            normalized_first = "".join(first_cell.split())
            if normalized_first.startswith("合计"):
                for header, value in zip(headers, row):
                    if value.strip():
                        if header == "金额":
                            table_data["totals"]["amount"] = value.strip()
                        elif header == "税额":
                            table_data["totals"]["tax_amount"] = value.strip()
                item_header = None
                continue

            if "价税合计" in first_cell:
                combined = " ".join(cell.strip() for cell in row if cell.strip())
                upper_match = re.search(r"价税合计（大写）\s*(.*?)\s*\(小写\)", combined)
                lower_match = re.search(r"\(小写\)\s*[¥￥]?\s*([\d,.]+)", combined)
                if upper_match:
                    table_data["totals"]["amount_in_words"] = upper_match.group(1).strip()
                if lower_match:
                    table_data["totals"]["total_amount"] = lower_match.group(1)
                item_header = None
                continue

            # 商品数据行按表头列名映射；合计、价税合计等行不会进入商品列表。
            if len(row) >= 2 and row[0].strip():
                item = {
                    item_field_names.get(header, header): value.strip()
                    for header, value in zip(headers, row)
                    if header and value.strip()
                }
                if item:
                    table_data["items"].append(item)

    return table_data


def _extract_invoice_page(
    page_result: dict,
    page_number: int,
    log_id: str | None,
) -> dict:
    """将单页 OCR 布局块转换为字段化发票对象，并保留来源块。"""
    pruned_result = page_result.get("prunedResult") or {}
    parsing_res_list = pruned_result.get("parsing_res_list") or []
    invoice = {
        "source": {
            "log_id": log_id,
            "page_number": page_number,
            "page_count": pruned_result.get("page_count"),
            "width": pruned_result.get("width"),
            "height": pruned_result.get("height"),
        },
        "invoice_type": None,
        "invoice_code": None,
        "invoice_number": None,
        "issue_date": None,
        "buyer": {},
        "seller": {},
        "items": [],
        "totals": {},
        "staff": {},
        "password_area": None,
        "remarks": None,
        "unclassified": [],
        "source_blocks": [],
    }
    code_candidates: list[str] = []
    number_candidates: list[str] = []

    for block in parsing_res_list:
        label = block.get("block_label")
        content = (block.get("block_content") or "").strip()
        # 原始块保留用于核对抽取结果；空的印章/图像块仍可由 label 识别。
        invoice["source_blocks"].append(
            {
                "block_id": block.get("block_id"),
                "block_label": label,
                "block_content": content,
                "block_bbox": block.get("block_bbox"),
            }
        )

        if not content:
            continue
        if label == "doc_title" and not invoice["invoice_type"]:
            invoice["invoice_type"] = content
            continue
        if label == "table":
            table_data = _parse_invoice_table(content)
            for key in ("buyer", "seller", "items", "totals", "password_area", "remarks"):
                if table_data.get(key):
                    if key in ("buyer", "seller", "totals"):
                        invoice[key].update(table_data[key])
                    else:
                        invoice[key] = table_data[key]
            continue

        date_match = re.search(r"开票日期\s*[：:]\s*(.+)", content)
        if date_match:
            invoice["issue_date"] = date_match.group(1).strip()
            continue

        number_match = re.search(r"\bNo\s*(\d+)\s+(\d+)\b", content, re.IGNORECASE)
        if number_match:
            number_candidates.append(number_match.group(1))
            code_candidates.append(number_match.group(2))
            continue

        if label == "text" and re.fullmatch(r"\d{8,20}", content):
            if len(content) == 10:
                code_candidates.append(content)
            else:
                number_candidates.append(content)
            continue

        staff_match = re.match(r"^(复核|收款人|开票人)\s*[：:]\s*(.+)$", content)
        if staff_match:
            staff_key = {"复核": "reviewer", "收款人": "payee", "开票人": "issuer"}[staff_match.group(1)]
            invoice["staff"][staff_key] = staff_match.group(2).strip()
            continue

        invoice["unclassified"].append(
            {"block_label": label, "block_content": content}
        )

    # No 行中相邻的两组数字比散落的重复文本更有上下文，优先作为号码来源。
    if number_candidates:
        invoice["invoice_number"] = number_candidates[0]
    if code_candidates:
        invoice["invoice_code"] = code_candidates[0]

    return invoice


def extract_invoice_data(jsonl_text: str) -> list[dict]:
    """从 JSONL 响应逐记录、逐页提取发票字段。"""
    invoices = []
    global_page_number = 0
    for line_number, line in enumerate(jsonl_text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue

        try:
            record = json.loads(line)
            page_results = record["result"]["layoutParsingResults"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise RuntimeError(f"第 {line_number} 行缺少有效的 layoutParsingResults。") from error

        for page_result in page_results:
            global_page_number += 1
            invoices.append(
                _extract_invoice_page(
                    page_result,
                    page_number=global_page_number,
                    log_id=record.get("logId"),
                )
            )

    return invoices


def print_and_save_invoice_data(jsonl_text: str, file_path: str) -> Path:
    """将字段化发票数据输出到控制台，并按输入图片名保存为 JSON。"""
    invoice_data = extract_invoice_data(jsonl_text)
    json_text = json.dumps(invoice_data, ensure_ascii=False, indent=2)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename_stem = get_input_file_stem(file_path)
    invoice_json_path = OUTPUT_DIR / f"invoice_data_{filename_stem}.json"
    invoice_json_path.write_text(json_text + "\n", encoding="utf-8")

    # Windows 控制台可能使用 GBK，切换 UTF-8 以正确输出中文和特殊符号。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("提取到的发票结构数据：")
    print(json_text)
    print(f"纯净版发票 JSON 已保存：{invoice_json_path}")
    return invoice_json_path


def save_parsed_ocr_results(jsonl_text: str) -> None:
    """解析 JSONL 文本，并将 Markdown 和相关图片写入 output/。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    page_number = 0
    for line_number, line in enumerate(jsonl_text.splitlines(), start=1):
        # JSONL 每一行都是一个独立 JSON 对象，跳过空行以兼容末尾换行。
        line = line.strip()
        if not line:
            continue

        try:
            result_data = json.loads(line)["result"]
        except (json.JSONDecodeError, KeyError) as error:
            raise RuntimeError(f"第 {line_number} 行结果格式无效。") from error

        for page_result in result_data.get("layoutParsingResults", []):
            markdown_data = page_result.get("markdown", {})
            markdown_path = OUTPUT_DIR / f"doc_{page_number}.md"
            markdown_path.write_text(
                markdown_data.get("text", ""),
                encoding="utf-8",
            )
            print(f"Markdown 结果已保存：{markdown_path}")

            # 保存 Markdown 中引用的图片，并按 API 返回的相对路径保留目录结构。
            for image_path, image_url in markdown_data.get("images", {}).items():
                local_image_path = OUTPUT_DIR / image_path
                local_image_path.parent.mkdir(parents=True, exist_ok=True)
                image_response = requests.get(image_url)
                image_response.raise_for_status()
                local_image_path.write_bytes(image_response.content)
                print(f"图片已保存：{local_image_path}")

            # 保存布局解析接口单独返回的图像，例如表格或版面区域截图。
            for image_name, image_url in page_result.get("outputImages", {}).items():
                image_response = requests.get(image_url)
                image_response.raise_for_status()
                local_image_path = OUTPUT_DIR / f"{image_name}_{page_number}.jpg"
                local_image_path.write_bytes(image_response.content)
                print(f"解析图像已保存：{local_image_path}")

            page_number += 1


def process_invoice(file_path: str) -> None:
    """完整执行一张票据的提交、轮询流程，并按开关保存结果文件。"""
    headers = get_api_headers()
    job_id = submit_ocr_job(file_path, headers)
    result_url = wait_for_ocr_result(job_id, headers)
    jsonl_text = download_ocr_result_text(result_url)

    if SAVE_RAW_JSONL:
        save_raw_jsonl(jsonl_text, file_path)

    # 输出并保存 prunedResult.parsing_res_list 中的结构化发票数据。
    print_and_save_invoice_data(jsonl_text, file_path)

    if SAVE_RESULT_FILES:
        # 开启开关后，下载并保存 Markdown、Markdown 引用图片及布局解析图像。
        save_parsed_ocr_results(jsonl_text)
    else:
        print("Markdown 和图片输出开关已关闭，未保存这三类结果文件。")


def main() -> int:
    """命令行程序入口：处理配置的票据图片并返回退出码。"""
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


# 只有直接运行本文件时才启动识别流程；作为模块导入时不会发起 API 请求。
if __name__ == "__main__":
    sys.exit(main())
