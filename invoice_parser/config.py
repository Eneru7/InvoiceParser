"""项目运行配置。按需修改输入文件、输出开关和 OCR 模型参数。"""

from pathlib import Path

JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
MODEL = "PaddleOCR-VL-1.6"
TOKEN_ENV_NAME = "PADDLEOCR_API_TOKEN"
FILE_PATH = "data/images/b0.jpg"
POLL_INTERVAL_SECONDS = 5
OUTPUT_DIR = Path("output")
SAVE_RAW_JSONL = True
SAVE_RESULT_FILES = False
OPTIONAL_PAYLOAD = {
    "useDocOrientationClassify": False,
    "useDocUnwarping": False,
    "useChartRecognition": False,
}
