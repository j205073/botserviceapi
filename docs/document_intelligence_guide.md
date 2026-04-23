# Azure Document Intelligence 整合指南

> 供 KB-Vector-Service 參考，說明 TR GPT Bot 如何串接 Document Intelligence 進行 OCR。

---

## 服務資訊

| 項目 | 值 |
|------|-----|
| 資源名稱 | `rinnai-doc-intelligence` |
| 區域 | East Asia |
| SKU | F0（免費方案，每月 500 頁） |
| Endpoint | `https://rinnai-doc-intelligence-52166.cognitiveservices.azure.com/` |
| Resource Group | `RinnaiResource` |

## 費用

| 方案 | 費用 |
|------|------|
| F0 (Free) | 每月 500 頁免費 |
| S0 (Standard) | ~$1 USD / 1000 頁 |

如果 KB 大量 ingest 文件超過 500 頁/月，建議升級為 S0：
```bash
az cognitiveservices account update --name rinnai-doc-intelligence --resource-group RinnaiResource --sku S0
```

---

## 安裝

```bash
pip install azure-ai-documentintelligence==1.0.2
```

## 環境變數

```env
DOC_INTELLIGENCE_ENDPOINT=https://rinnai-doc-intelligence-52166.cognitiveservices.azure.com/
DOC_INTELLIGENCE_KEY=<key>
```

取得 Key：
```bash
az cognitiveservices account keys list --name rinnai-doc-intelligence --resource-group RinnaiResource -o json
```

---

## 基本用法

### 從 bytes 分析文件

```python
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from azure.core.credentials import AzureKeyCredential

client = DocumentIntelligenceClient(
    endpoint="https://rinnai-doc-intelligence-52166.cognitiveservices.azure.com/",
    credential=AzureKeyCredential("<key>"),
)

# 讀取檔案
with open("example.pdf", "rb") as f:
    pdf_bytes = f.read()

# 分析文件（prebuilt-read = 通用 OCR）
poller = client.begin_analyze_document(
    "prebuilt-read",
    AnalyzeDocumentRequest(bytes_source=pdf_bytes),
)
result = poller.result()

# 取得全文
full_text = result.content  # str，完整文字內容
print(full_text)
```

### 從 URL 分析文件

```python
poller = client.begin_analyze_document(
    "prebuilt-read",
    AnalyzeDocumentRequest(url_source="https://example.com/file.pdf"),
)
result = poller.result()
```

---

## 可用模型

| 模型 ID | 用途 | 建議場景 |
|---------|------|---------|
| `prebuilt-read` | 通用 OCR（文字擷取） | **KB ingest 首選**，適合大部分文件 |
| `prebuilt-layout` | 版面分析（含表格、段落結構） | 需要保留表格結構時使用 |
| `prebuilt-document` | 通用文件（key-value pairs） | 表單類文件 |
| `prebuilt-invoice` | 發票辨識 | 發票 |
| `prebuilt-receipt` | 收據辨識 | 收據 |

### KB 建議用法

```python
# 一般文件 → prebuilt-read（快、便宜）
poller = client.begin_analyze_document("prebuilt-read", ...)

# 含表格的文件 → prebuilt-layout（保留表格結構）
poller = client.begin_analyze_document("prebuilt-layout", ...)
```

---

## 回傳結構

```python
result = poller.result()

# 完整文字（最常用）
result.content  # str

# 逐頁資訊
for page in result.pages:
    print(f"Page {page.page_number}: {len(page.lines)} lines")
    for line in page.lines:
        print(f"  {line.content}")  # 每行文字
        # line.polygon → 文字位置座標（bounding box）

# 表格（僅 prebuilt-layout）
for table in (result.tables or []):
    print(f"Table: {table.row_count} rows x {table.column_count} cols")
    for cell in table.cells:
        print(f"  [{cell.row_index},{cell.column_index}] {cell.content}")
```

---

## 判斷 PDF 是文字型還是圖片型

TR GPT Bot 的做法：先用 PyPDF2 擷取文字，擷取不到再 fallback OCR。

```python
from PyPDF2 import PdfReader
import io

def extract_pdf_text(pdf_bytes: bytes) -> tuple[str, str]:
    """
    回傳 (text, pdf_type)
    pdf_type: "text" 或 "scanned"
    """
    # 1. 先嘗試直接擷取文字
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = [p.extract_text() or "" for p in reader.pages[:20]]
    text = "\n".join(pages).strip()

    if text:
        return text, "text"

    # 2. 文字為空 → 掃描型，用 Document Intelligence OCR
    client = DocumentIntelligenceClient(endpoint, credential)
    poller = client.begin_analyze_document(
        "prebuilt-read",
        AnalyzeDocumentRequest(bytes_source=pdf_bytes),
    )
    result = poller.result()
    ocr_text = (result.content or "").strip()

    return ocr_text, "scanned"
```

---

## 大型 PDF 處理

大型掃描 PDF（如 65MB / 124 頁）需要截取後才能送 OCR。

### 限制條件

| 限制項目 | 值 | 說明 |
|---------|-----|------|
| 檔案大小上限 | 3.5 MB（截取後） | Free tier 單次請求上限 4MB，預留 buffer |
| 頁數上限 | 50 頁 | 次要限制，避免處理過久 |
| 附件大小上限 | 20 MB | Bot 端上傳附件的大小限制，超過給友善提示 |

### TR GPT Bot 的做法

以**檔案大小**為主要限制，逐頁累加直到接近上限：

```python
from PyPDF2 import PdfReader, PdfWriter
import io

OCR_MAX_SIZE_MB = 3.5   # Document Intelligence 檔案大小上限
OCR_MAX_PAGES = 50      # 頁數上限

max_bytes = int(OCR_MAX_SIZE_MB * 1024 * 1024)
reader = PdfReader(io.BytesIO(pdf_bytes))
total_pages = len(reader.pages)

if len(pdf_bytes) > max_bytes or total_pages > OCR_MAX_PAGES:
    writer = PdfWriter()
    for i in range(min(total_pages, OCR_MAX_PAGES)):
        writer.add_page(reader.pages[i])
        buf = io.BytesIO()
        writer.write(buf)
        if buf.tell() > max_bytes:
            # 超過大小限制，移除最後一頁
            if i > 0:
                writer = PdfWriter()
                for j in range(i):
                    writer.add_page(reader.pages[j])
                buf = io.BytesIO()
                writer.write(buf)
            break
    pdf_bytes = buf.getvalue()
```

### KB 建議

KB ingest 時可能需要完整內容，可以考慮：
- 分批處理：每次送 3.5MB，合併結果
- 或升級 S0 方案後直接送整份（S0 上限 500MB）

---

## KB-Vector-Service 整合建議

### Ingest 流程加入 OCR

```
文件上傳
  │
  ├─ .txt / .md / .csv → 直接讀文字
  ├─ .docx → python-docx 擷取
  ├─ .xlsx → openpyxl 擷取
  ├─ .pptx → python-pptx 擷取
  └─ .pdf
       ├─ PyPDF2 擷取成功 → 文字型，直接用
       └─ PyPDF2 擷取失敗 → Document Intelligence OCR
                              │
                              ▼
                         擷取到的文字
                              │
                              ▼
                     Embedding → Vector Store
```

### 程式碼範例

```python
class DocumentProcessor:
    def __init__(self, doc_intelligence_endpoint: str, doc_intelligence_key: str):
        self.ocr_client = DocumentIntelligenceClient(
            endpoint=doc_intelligence_endpoint,
            credential=AzureKeyCredential(doc_intelligence_key),
        )

    def extract_text(self, file_bytes: bytes, filename: str) -> str:
        """從任意檔案擷取文字，支援 OCR fallback"""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if ext == "pdf":
            return self._extract_pdf(file_bytes)
        elif ext == "docx":
            from docx import Document
            doc = Document(io.BytesIO(file_bytes))
            return "\n".join(p.text for p in doc.paragraphs)
        elif ext in ("txt", "md", "csv", "json"):
            return file_bytes.decode("utf-8", errors="replace")
        else:
            # 其他格式也可以丟 Document Intelligence 試試
            return self._ocr(file_bytes)

    def _extract_pdf(self, data: bytes) -> str:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(p.extract_text() or "" for p in reader.pages).strip()
        if text:
            return text
        return self._ocr(data)

    def _ocr(self, data: bytes) -> str:
        poller = self.ocr_client.begin_analyze_document(
            "prebuilt-read",
            AnalyzeDocumentRequest(bytes_source=data),
        )
        return poller.result().content or ""
```

---

## 注意事項

- **Free tier 限制**：F0 每月 500 頁，超過會回傳 429 Too Many Requests
- **檔案大小限制**：F0 單次請求最大 **4MB**（S0 為 500MB）；TR GPT Bot 設定截取上限 3.5MB
- **支援格式**：PDF、JPEG、PNG、BMP、TIFF、HEIF、DOCX、XLSX、PPTX
- **同步/非同步**：`begin_analyze_document` 回傳 poller，需要 `.result()` 等待完成
- **共用資源**：TR GPT Bot 和 KB Service 共用同一個 Document Intelligence 資源，注意頁數配額
- **Bot 附件大小限制**：超過 20MB 的附件會顯示友善提示，建議使用者拆分後重新上傳
