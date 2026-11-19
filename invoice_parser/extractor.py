"""从 PaddleOCR 的 JSONL 响应中提取字段化发票数据。"""

import json
import re
from html.parser import HTMLParser


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
            if self._row is not None:
                self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _parse_table_rows(table_html: str) -> list[list[str]]:
    """解析表格 HTML，并还原 OCR 字符串中的字面量换行符。"""
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
            staff_key = {
                "复核": "reviewer",
                "收款人": "payee",
                "开票人": "issuer",
            }[staff_match.group(1)]
            invoice["staff"][staff_key] = staff_match.group(2).strip()
            continue

        invoice["unclassified"].append(
            {"block_label": label, "block_content": content}
        )

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
