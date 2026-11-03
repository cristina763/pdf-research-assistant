# 交付檔案清單

白名單共 60 個檔案。測試不被網站匯入。

| 路徑 | 白話用途 | 為什麼必須或建議交付 |
| --- | --- | --- |
| `.env.example` | 設定範例，不含有效金鑰 | 正式程式／啟動設定 |
| `.gitignore` | 排除金鑰、快取、模型與測試輸出 | 正式程式／啟動設定 |
| `DELIVERY_FILES.md` | 完整白名單用途與交付邊界 | 安裝、核對與說明限制 |
| `DELIVERY_MANIFEST.json` | 逐檔大小與 SHA-256；不對自身雜湊 | 安裝、核對與說明限制 |
| `README.md` | 繁體中文安裝、操作、隱私及限制說明 | 安裝、核對與說明限制 |
| `backend/app/__init__.py` | 後端套件入口 | 正式程式／啟動設定 |
| `backend/app/assessment.py` | 仍被匯入的舊回答合約；不是外部 Judge | 正式程式／啟動設定 |
| `backend/app/config.py` | 環境設定與相對路徑 | 正式程式／啟動設定 |
| `backend/app/failed_answer.py` | 失敗回應的來源處理 | 正式程式／啟動設定 |
| `backend/app/intent.py` | 區分摘要與一般問答 | 正式程式／啟動設定 |
| `backend/app/main.py` | FastAPI 上傳、健康檢查、問答與錯誤處理 | 正式程式／啟動設定 |
| `backend/app/manual_review.py` | 正式生成 Schema、來源選擇與人工核對顯示 | 正式程式／啟動設定 |
| `backend/app/numeric_context.py` | 組裝數值及方法比較證據 | 正式程式／啟動設定 |
| `backend/app/parser.py` | Docling 解析、結構化 Chunk 與來源映射 | 正式程式／啟動設定 |
| `backend/app/partial_summary.py` | 舊合約部分摘要的呈現 | 正式程式／啟動設定 |
| `backend/app/presentation.py` | 舊合約回答及來源顯示 | 正式程式／啟動設定 |
| `backend/app/rag/__init__.py` | RAG 套件入口 | 正式程式／啟動設定 |
| `backend/app/rag/comparison.py` | 比較問題證據組裝 | 正式程式／啟動設定 |
| `backend/app/rag/comparison_validation.py` | 舊合約有限數值比較檢查 | 正式程式／啟動設定 |
| `backend/app/rag/context.py` | 可追溯 Context 組裝 | 正式程式／啟動設定 |
| `backend/app/rag/core.py` | 模型、Schema、Token／費用及來源驗證 | 正式程式／啟動設定 |
| `backend/app/rag/data.py` | 文件轉成檢索與摘要證據 | 正式程式／啟動設定 |
| `backend/app/rag/engine.py` | 問答及 Map／Reduce 引擎；網站停用磁碟記錄 | 正式程式／啟動設定 |
| `backend/app/rag/enhanced_context.py` | 補充同章節或鄰近來源 | 正式程式／啟動設定 |
| `backend/app/rag/preprocess.py` | 表格／段落結構轉換 | 正式程式／啟動設定 |
| `backend/app/rag/provider.py` | 純文字 API、Timeout、Token 計數與預算 | 正式程式／啟動設定 |
| `backend/app/rag/quality_contract.py` | 仍被匯入的舊 Schema 與合約 | 正式程式／啟動設定 |
| `backend/app/rag/retrieval.py` | BM25 檢索與索引快取 | 正式程式／啟動設定 |
| `backend/app/service.py` | 串接問答與全文摘要；關閉問答檔案保存與重播 | 正式程式／啟動設定 |
| `backend/app/store.py` | 文件雜湊及 PDF、解析、Chunk、索引快取 | 正式程式／啟動設定 |
| `backend/app/summary_diagnostics.py` | 摘要 Token 與涵蓋診斷；網站使用記憶體資料 | 正式程式／啟動設定 |
| `backend/app/summary_evidence.py` | 代表性原文與表格證據 | 正式程式／啟動設定 |
| `backend/app/summary_notes.py` | 摘要筆記、分類及合併 | 正式程式／啟動設定 |
| `backend/app/table_comparisons.py` | 確定性數值比較與排序 | 正式程式／啟動設定 |
| `backend/app/table_results.py` | 按原文表格呈現數值及來源 | 正式程式／啟動設定 |
| `backend/requirements-dev-lock.txt` | 完整基本測試依賴版本 | 可獨立執行的基本測試，無研發驗收資料 |
| `backend/requirements-dev.txt` | 基本測試直接依賴 | 可獨立執行的基本測試，無研發驗收資料 |
| `backend/requirements-lock.txt` | 獨立驗證的完整正式 Python 版本 | 可重現安裝 |
| `backend/requirements.txt` | 正式直接 Python 依賴 | 可重現安裝 |
| `backend/tests/conftest.py` | 隔離設定與禁止外部網路 | 可獨立執行的基本測試，無研發驗收資料 |
| `backend/tests/helpers.py` | 合成文件／Mock 文字供應器；只供測試 | 可獨立執行的基本測試，無研發驗收資料 |
| `backend/tests/test_basic.py` | 獨立基本測試，無標準答案或歷史依賴 | 可獨立執行的基本測試，無研發驗收資料 |
| `frontend/index.html` | 網頁入口 | 正式程式／啟動設定 |
| `frontend/package-lock.json` | 完整 npm 依賴鎖定 | 可重現安裝 |
| `frontend/package.json` | 前端依賴與操作指令 | 正式程式／啟動設定 |
| `frontend/playwright.config.ts` | 自包含瀏覽器測試設定 | 可獨立執行的基本測試，無研發驗收資料 |
| `frontend/src/App.tsx` | 上傳、提問、回答與引用介面 | 正式程式／啟動設定 |
| `frontend/src/api.ts` | HTTP 型別與呼叫 | 正式程式／啟動設定 |
| `frontend/src/main.tsx` | React 入口 | 正式程式／啟動設定 |
| `frontend/src/reviewExport.ts` | 使用者主動複製核對內容；不自動保存 | 正式程式／啟動設定 |
| `frontend/src/styles.css` | 網頁樣式 | 正式程式／啟動設定 |
| `frontend/tests/smoke.spec.ts` | Mock 網頁生成、引用與清空測試 | 可獨立執行的基本測試，無研發驗收資料 |
| `frontend/tsconfig.json` | TypeScript 編譯設定 | 正式程式／啟動設定 |
| `frontend/vite.config.ts` | React 建置及本機代理 | 正式程式／啟動設定 |
| `scripts/download_models.py` | 透過 Docling 官方函式下載公開模型 | 正式程式／啟動設定 |
| `scripts/run_backend.py` | 可攜啟動與非敏感設定檢查 | 正式程式／啟動設定 |
| `scripts/runtime_env.py` | 載入根目錄 .env；不輸出設定值 | 正式程式／啟動設定 |

## 白名單來源與變更邊界

複製完整 backend/app 的 30 個 Python 檔、frontend/src 的 5 個檔案，以及 8 個明確設定／依賴檔，共 43 個來源檔。
交付副本新增鎖定檔、三個啟動／模型腳本、基本測試與說明。直接依賴增加 python-dotenv；.env.example 補充載入方式；service.py 只調整不可用 expanded 模式的錯誤文字，未更換演算法或放寬 Token 限制。

## 排除項目

不含 .env／.env.txt、有效憑證、.git、虛擬環境、node_modules、原有 dist、資料快取、模型權重、PDF、開發驗收目錄、Ground Truth、外部 Judge、歷史答案、失敗紀錄或 Debug Log。測試內合成回應是 Mock 流程工具，不是指定題目答案。

## 仍保留的相容程式

assessment、presentation、partial_summary、quality_contract、comparison_validation 等舊合約仍有頂層或條件式匯入，保留以避免 Import Error。共用 Generator 仍有供顯式離線呼叫使用的記錄／重播程式；正式 RAGService 明確停用。基本測試驗證網站不讀舊答案及不寫問答。這些舊合約不是語意正確性的自動保證。

## 人工確認

有效 API Key、模型帳戶權限、真實回答品質、公司文件外送政策，以及專案／第三方授權，仍需人工確認。全新 Windows 11 電腦安裝、PPT、Git、ZIP 與正式提交不包含在本輪完成宣告。

## A1 summary presentation update (2026-11-03)

- `backend/app/summary_style.py`: generic summary depth and length policy.
- `backend/tests/test_summary_presentation.py`: offline presentation and numeric regression checks.

## QA answer and evidence separation

- `backend/tests/test_qa_answer.py`: answer/evidence separation, failed-generation rejection, numeric and citation safeguards.
- Acceptance reports and live API test artifacts are kept outside this delivery directory and are excluded from the manifest.
