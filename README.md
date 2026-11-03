# PDF Research Assistant

可在 Windows 11 本機執行的 PDF 文件問答網站。上傳 PDF 後，系統使用 BM25 檢索文件證據，再由文字 LLM 生成答案並顯示來源與頁碼；全文摘要採用 Map／Reduce。

## 環境需求

- Windows 11 64 位元。
- Python 3.12.x。
- Node.js 22.12 以上，建議使用 24 LTS；需要附帶的 npm。
- CPU 即可，不要求 GPU。依賴與模型占用數 GB，建議預留至少 10 GB 磁碟；較長文件需要更多記憶體與處理時間。這不是已量測的最低硬體保證。
- 首次安裝及模型下載需要網路；文字生成需要有效 OpenAI API Key、模型權限及可用額度。

本輪隔離驗證使用 Python 3.12.10、Node.js 24.22.1、npm 11.19.1。以下指令使用 PowerShell，從本專案根目錄開始執行。

## 1. 建立 Python 環境

~~~powershell
python --version
node --version
npm.cmd --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-lock.txt
.\.venv\Scripts\python.exe -m pip check
~~~

requirements-lock.txt 記錄本次 Windows x64／Python 3.12 隔離安裝驗證的完整依賴版本；requirements.txt 記錄直接依賴。其他 Python 版本及作業系統未驗證。

直接呼叫虛擬環境中的 Python，不必執行 Activate，也不必調整 PowerShell ExecutionPolicy。

## 2. 設定 API Key

先確認 .env.example 的 OPENAI_API_KEY 為空白範例，不可將真實金鑰保存在範例檔。

若尚未建立 .env：

~~~powershell
Copy-Item .env.example .env
~~~

如果 .env 已存在，請直接編輯，不要覆蓋原有設定。使用文字編輯器開啟 .env，設定：

~~~dotenv
OPENAI_API_KEY=請填入你自己的有效金鑰
ENABLE_GENERATION=true
CONTEXT_MODE=baseline
GENERATION_BUDGET_USD=1
GENERATION_MAX_CALLS=40
~~~

金鑰只放在本機 .env，不能放進程式碼、前端 VITE_ 變數或對外提交的檔案。啟動腳本會先載入根目錄 .env；已存在的程序環境變數優先。

預設關閉生成。未設定金鑰仍可啟動及解析 PDF，但不能生成答案。

Set the model in `.env`:

~~~dotenv
OPENAI_MODEL=gpt-5.4-mini-2026-03-17
~~~

## 3. 下載 Docling 模型

~~~powershell
.\.venv\Scripts\python.exe -B scripts\download_models.py
.\.venv\Scripts\python.exe -B scripts\run_backend.py --check-config
~~~

模型預設下載到根目錄 models/，使用 [Docling 官方下載介面](https://docling-project.github.io/docling/usage/advanced_options/)取得公開模型。首次下載可能較久。下載完成後，文件解析主要使用本機模型；此腳本不會呼叫付費文字生成 API。

--check-config 只顯示是否設定金鑰、生成啟用狀態、模型及 Context 上限，不會顯示金鑰。

.env 中的 DOCLING_ARTIFACTS_PATH=models 與 RAG_DATA_DIR=data 均以專案根目錄解析，不依賴開發電腦的絕對路徑。

## 4. 啟動 Backend

在第一個終端機，從根目錄執行：

~~~powershell
.\.venv\Scripts\python.exe -B scripts\run_backend.py
~~~

- Backend：http://127.0.0.1:8000
- 健康檢查：http://127.0.0.1:8000/health
- API 文件：http://127.0.0.1:8000/docs

## 5. 安裝與啟動 Frontend

在第二個終端機，從根目錄執行：

~~~powershell
Set-Location frontend
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1 --port 5173 --strictPort
~~~

瀏覽器開啟 http://127.0.0.1:5173 。

Vite 將 /api 代理到 Backend 的 8000 Port。兩個終端機都需要持續執行，使用 Ctrl+C 停止。這是本機 Demo 的啟動方式，未設計成直接公開到網際網路的部署方案。

若後端改用 --port 8001，啟動前端前須在前端終端機設定：

~~~powershell
$env:BACKEND_URL='http://127.0.0.1:8001'
~~~


## 常見問題

- 找不到 Python：安裝 Python 3.12 並加入 PATH，先確認 python --version；避免誤用 Microsoft Store 捷徑或其他版本。
- 模型下載失敗：確認 PyPI／Hugging Face 網路、磁碟、公司代理與憑證。請使用合法 CA 設定，不要關閉 TLS 驗證。
- 缺少原生 DLL：檢查 Windows 更新與 Microsoft Visual C++ x64 Runtime。
- 第一次上傳較慢：Docling 初始化與 CPU 解析需要時間。掃描型 PDF 在 OCR 關閉時可能沒有可搜尋文字。
- 後端無法連線：確認兩個程序都在執行，8000／5173 沒被占用；變更 Port 時須同步調整前端代理。
- 生成未啟用：檢查 .env 的 ENABLE_GENERATION=true、有效金鑰及 --check-config。程序環境變數優先；修改設定後須重啟 Backend。
- 502 或逾時：確認網路、模型權限與額度。系統不會自動重試付費請求，重試前請先確認狀態。
- 預算不足或 10K 拒絕：摘要可能有多階段呼叫。先檢查文件長度與設定，不要直接放寬 10K 限制。
- 中文顯示異常：此 README 使用 UTF-8。若檔案中的文字已實際被替換成問號，單純切換編碼無法還原，需要恢復正確文字版本。
