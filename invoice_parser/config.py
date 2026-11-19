"""项目运行配置。按需修改输入文件、输出开关和 OCR 模型参数。"""

from pathlib import Path

JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
MODEL = "PaddleOCR-VL-1.6"
TOKEN_ENV_NAME = "PADDLEOCR_API_TOKEN"
FILE_PATH = "data/images/b0.jpg"
POLL_INTERVAL_SECONDS = 3
REQUEST_TIMEOUT_SECONDS = 30
JOB_TIMEOUT_SECONDS = 900
REQUEST_MAX_RETRIES = 3
OUTPUT_DIR = Path("output")
SAVE_RAW_JSONL = True
SAVE_RESULT_FILES = False
MAX_WORKERS = 4
DATASET_DIR = Path("data/images")
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
BENCHMARK_SAMPLE_SIZE = 10
BENCHMARK_WORKER_COUNTS = (1, 2, 4)
BENCHMARK_RANDOM_SEED = 42
PARSER_BENCHMARK_REPEATS = 10
OPTIONAL_PAYLOAD = {
    "useDocOrientationClassify": False,
    "useDocUnwarping": False,
    "useChartRecognition": False,
}
