"""PaddleOCR 云端 API 的认证、任务提交、轮询和结果下载。"""

import json
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from collections.abc import Callable

import requests

from invoice_parser.config import (
    JOB_URL,
    MODEL,
    OPTIONAL_PAYLOAD,
    POLL_INTERVAL_SECONDS,
    JOB_TIMEOUT_SECONDS,
    REQUEST_MAX_RETRIES,
    REQUEST_TIMEOUT_SECONDS,
    TOKEN_ENV_NAME,
)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _request_with_retries(
    send_request: Callable[[], requests.Response],
    *,
    retry_network_errors: bool = True,
    retry_status_codes: set[int] | None = None,
) -> requests.Response:
    """对限流、临时服务错误及可安全重试的网络请求进行有限重试。"""
    status_codes = RETRYABLE_STATUS_CODES if retry_status_codes is None else retry_status_codes
    for attempt in range(REQUEST_MAX_RETRIES):
        try:
            response = send_request()
        except (requests.Timeout, requests.ConnectionError):
            if not retry_network_errors or attempt + 1 >= REQUEST_MAX_RETRIES:
                raise
            delay = min(2**attempt, 30)
            print(f"网络暂时不可用，{delay} 秒后重试（{attempt + 1}/{REQUEST_MAX_RETRIES - 1}）。")
            time.sleep(delay)
            continue

        if response.status_code in status_codes and attempt + 1 < REQUEST_MAX_RETRIES:
            retry_after = response.headers.get("Retry-After")
            try:
                if retry_after:
                    try:
                        delay = max(0.0, float(retry_after))
                    except ValueError:
                        retry_at = parsedate_to_datetime(retry_after)
                        if retry_at.tzinfo is None:
                            retry_at = retry_at.replace(tzinfo=timezone.utc)
                        delay = max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
                else:
                    delay = min(2**attempt, 30)
            except ValueError:
                delay = min(2**attempt, 30)
            print(f"API 返回 HTTP {response.status_code}，{delay:g} 秒后重试。")
            response.close()
            time.sleep(delay)
            continue

        response.raise_for_status()
        return response

    raise RuntimeError("API 请求超过最大重试次数。")


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
        request_headers = {**headers, "Content-Type": "application/json"}
        payload = {
            "fileUrl": file_path,
            "model": MODEL,
            "optionalPayload": OPTIONAL_PAYLOAD,
        }
        response = _request_with_retries(
            lambda: requests.post(
                JOB_URL,
                json=payload,
                headers=request_headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            ),
            retry_network_errors=False,
            # 创建任务的 POST 不自动重试 5xx，避免服务端已受理但响应丢失时重复计费。
            retry_status_codes={429},
        )
    else:
        image_path = Path(file_path)
        if not image_path.is_file():
            raise FileNotFoundError(f"找不到图片文件：{image_path}")

        form_data = {
            "model": MODEL,
            "optionalPayload": json.dumps(OPTIONAL_PAYLOAD),
        }
        def send_upload() -> requests.Response:
            # 每次重试都重新打开文件，避免上传流在第一次请求后已到达末尾。
            with image_path.open("rb") as image_file:
                return requests.post(
                    JOB_URL,
                    headers=headers,
                    data=form_data,
                    files={"file": image_file},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )

        response = _request_with_retries(
            send_upload,
            retry_network_errors=False,
            retry_status_codes={429},
        )

    job_id = response.json().get("data", {}).get("jobId")
    if not job_id:
        raise RuntimeError("任务提交成功响应中没有找到 jobId。")

    print(f"任务提交成功，任务编号：{job_id}")
    return job_id


def wait_for_ocr_result(job_id: str, headers: dict[str, str]) -> str:
    """轮询任务状态，直到完成并返回结果 JSONL 文件的 URL。"""
    deadline = time.monotonic() + JOB_TIMEOUT_SECONDS
    print("开始等待识别结果……")
    while True:
        if time.monotonic() >= deadline:
            raise RuntimeError(f"任务 {job_id} 等待超过 {JOB_TIMEOUT_SECONDS} 秒，已超时。")
        response = _request_with_retries(
            lambda: requests.get(
                f"{JOB_URL}/{job_id}",
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        )
        job_data = response.json().get("data", {})
        state = job_data.get("state")

        if state == "pending":
            print("任务正在排队等待处理。")
        elif state == "running":
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

        time.sleep(min(POLL_INTERVAL_SECONDS, max(0, deadline - time.monotonic())))


def download_ocr_result_text(jsonl_url: str) -> str:
    """下载并返回 API 的 JSONL 文本响应。"""
    response = _request_with_retries(
        lambda: requests.get(jsonl_url, timeout=REQUEST_TIMEOUT_SECONDS)
    )
    return response.text
