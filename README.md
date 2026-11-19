# InvoiceParser

基于 **PaddleOCR 云端 API** 的票据识别示例工程。程序提交本地图片或图片 URL，轮询识别任务，并将 API 返回的版面解析数据整理为发票 JSON。

## 功能

- 调用 PaddleOCR `PaddleOCR-VL-1.6` API 识别票据。
- 支持上传本地图片，或提交可访问的图片 URL。
- 从 `layoutParsingResults[].prunedResult.parsing_res_list` 提取发票字段，包括发票类型、号码、日期、购销双方、商品明细、合计金额和开票相关人员。
- 保留 OCR 原始块作为 `source_blocks`，便于追溯字段来源；未能识别归类的内容放在 `unclassified`。
- 根据输入图片文件名生成独立结果文件，避免多张图片的输出互相覆盖。

## 环境要求

- Python 3.12 或更高版本（项目当前固定为 Python 3.12）。
- [uv](https://github.com/astral-sh/uv) 项目与依赖管理工具。
- PaddleOCR API Token，以及可访问 PaddleOCR API 的网络。

## 安装

在项目根目录运行：

```powershell
uv sync
```

`uv sync` 会根据 `pyproject.toml` 和 `uv.lock` 安装项目依赖，并使用项目虚拟环境 `.venv`。

## 配置 API Token

程序从当前进程环境变量 `PADDLEOCR_API_TOKEN` 读取凭证，不要将真实 Token 写入代码或提交到版本库。

Windows 中可在“编辑账户的环境变量”里新增用户变量：

- 变量名：`PADDLEOCR_API_TOKEN`
- 变量值：你的 PaddleOCR API Token

设置后重新启动 PyCharm，使其运行配置继承更新后的环境变量。也可以在当前 PowerShell 会话临时设置：

```powershell
$env:PADDLEOCR_API_TOKEN = "你的 API Token"
```

## 配置输入图片

将图片放入 `data/images/`，然后修改 `invoice_parser/config.py` 中的 `FILE_PATH`：

```python
FILE_PATH = "data/images/b0.jpg"
```

`FILE_PATH` 也可以填写以 `http://` 或 `https://` 开头的图片 URL。当前程序一次处理一个输入文件。

## 数据集

本项目使用的数据集：[百度 AI Studio 票据数据集](https://aistudio.baidu.com/datasetdetail/125158)。将需要识别的图片放入 `data/images/` 后，通过 `FILE_PATH` 指定要处理的图片。

## 运行

```powershell
uv run python main.py
```

也可以在 PyCharm 中将项目解释器设置为：

```text
<项目目录>\.venv\Scripts\python.exe
```

## 输出文件

输出写入项目根目录的 `output/`，文件名由输入图片的文件名主干生成。例如输入 `data/images/b0.jpg`：

- `ocr_result_b0.jsonl`：API 返回的原始 JSONL 文本。由 `SAVE_RAW_JSONL` 控制，默认开启。
- `invoice_data_b0.json`：从版面解析块整理出的发票 JSON。每页包含来源信息、已识别字段、未分类文本和原始来源块。
- Markdown 文件、Markdown 引用的图片和布局解析图像：由 `invoice_parser/config.py` 中的 `SAVE_RESULT_FILES` 控制，默认关闭。需要这些文件时，将该值改为 `True`。

字段提取按当前样本中的票据标签与表格结构进行解析。识别结果应结合 `source_blocks` 核对；遇到不同票据版式时，可能需要扩展字段映射规则。

## 项目结构

```text
InvoiceParser/
├── data/
│   └── images/       # 输入票据图片
├── output/           # OCR 与结构化结果
├── invoice_parser/
│   ├── api.py        # API 认证、任务提交、轮询和结果下载
│   ├── config.py     # 输入路径、模型、输出目录与功能开关
│   ├── extractor.py # 从 OCR 结果提取发票字段
│   ├── outputs.py    # 保存 JSONL、结构化 JSON 和可选图像结果
│   └── workflow.py   # 编排完整的票据识别流程
├── main.py           # 程序入口
├── pyproject.toml    # 项目元数据与依赖
├── uv.lock           # 锁定的依赖版本
└── README.md
```

## 使用的开源项目

| 项目 | 用途 | 项目地址 |
| --- | --- | --- |
| PaddleOCR | 提供票据 OCR 与版面解析能力；本项目通过云端 API 调用，不在本地安装或运行 PaddleOCR 推理包。 | [PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) |
| Requests | Python HTTP 客户端，用于提交任务、轮询状态和下载结果。 | [psf/requests](https://github.com/psf/requests) |
| uv | Python 项目、依赖和虚拟环境管理。 | [astral-sh/uv](https://github.com/astral-sh/uv) |

表格 HTML 的处理使用 Python 标准库 `html.parser`，不需要额外安装解析依赖。
