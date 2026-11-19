"""PaddleOCR 云端 API 的认证、任务提交、轮询和结果下载。"""

import json
import os
import time
from pathlib import Path

import requests

from invoice_parser.config import (
    JOB_URL,
    MODEL,
    OPTIONAL_PAYLOAD,
    POLL_INTERVAL_SECONDS,
    TOKEN_ENV_NAME,
)


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
        response = requests.post(JOB_URL, json=payload, headers=request_headers)
    else:
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
