export interface Health {
  status: string
  generation_enabled: boolean
  api_key_configured?: boolean
  max_upload_bytes?: number
}
export interface DocumentResult {
  document_id: string
  pages: number
  chunks: number
  cache_hit: boolean
  elapsed_seconds: number
}
export interface Source {
  evidence_id: string
  pages: number[]
  source_refs: string[]
  text: string
  trust?: string
  quotes?: string[]
  support_status?: 'confirmed' | 'review_required' | 'mapped'
}
export interface SupportingTable {
  table_id: string
  table_number: number | null
  pages: number[]
  evidence_ids: string[]
  rows: { fact_id: string; method: string; dataset: string; metric: string; comparison_methods: string[]; value: string; evidence_id: string; pages: number[] }[]
  native_grid?: string[][]
  scope: string
}
export interface ValidationWarning {
  code: string
  message: string
  source_ids: string[]
  path?: string
  stage?: string
  severity: 'review' | 'rejected'
}
export interface SummaryDiagnostics {
  reduction_rounds?: unknown[]
  partial_summary?: { reason?: string }
  segment_count: number
  recorded_generation_seconds: number
  recorded_count_seconds: number
  stages: { stage: string; status: string; fallback: boolean; reasons: string[]; official_input_tokens: number | null; output_reserve: number | null; safety: number | null; budget_total: number | null; within_10k: boolean | null; generation_seconds: number | null; count_seconds: number | null; coverage_carried_categories?: string[] }[]
}
export interface AnswerResult {
  answer_integrity?: { model_statement_count: number; preserved_statement_count: number }
  answer_status?: 'answered' | 'insufficient_evidence'
  supporting_evidence?: { numeric_markdown: string; citations: { evidence_id: string; pages: number[] }[]; numeric_claims: unknown[] }
  review_policy?: 'manual'
  citation_warnings?: { code: string; message: string; source_ids: string[] }[]
  summary_notes?: { reason: string; missing_categories: string[] }
  document_id: string
  answer: { answer_markdown: string; evidence_status: string; limitations: string[] }
  sources: Source[]
  unverified_sources?: Source[]
  validation_status?: 'passed' | 'review_required' | 'failed'
  validation_warnings?: ValidationWarning[]
  generation?: { status: 'completed' | 'stages_completed'; model: string; usage: { input_tokens: number; output_tokens: number; total_tokens: number }; generation_latency_seconds: number | null; recovered_existing_response: boolean; new_paid_generation: boolean }
  summary_status?: 'complete' | 'partial'
  summary_diagnostics?: SummaryDiagnostics
  supporting_tables?: SupportingTable[]
  validation?: { comparison_directions?: { checked: number; unverified: number; semantic_fidelity: string } }
  elapsed_seconds: number
  cache_hit: boolean
}
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}
async function request(path: string, init?: RequestInit): Promise<unknown> {
  let response: Response
  try { response = await fetch(`/api${path}`, init) }
  catch { throw new ApiError(0, '無法連線至後端。請確認 FastAPI 已啟動。若問題已送出，請先檢查後端狀態，避免重複生成。') }
  let data: unknown
  try { data = await response.json() }
  catch { throw new ApiError(response.status, '後端回傳了無法讀取的資料，請檢查服務狀態。') }
  if (!response.ok) {
    const detail = data && typeof data === 'object' && 'detail' in data ? (data as { detail: unknown }).detail : ''
    const original = typeof detail === 'string' ? detail : ''
    const messages: Record<number, string> = {
      404: '找不到這份文件，可能已被移除。請重新上傳 PDF。',
      413: 'PDF 超過後端允許的上傳大小，請選擇較小的檔案。',
      415: '檔案不是有效的 PDF，請確認格式後重新選擇。',
      422: '無法完成此請求。PDF、問題或來源驗證未通過，請查看下方後端訊息。',
      501: '所要求的功能目前尚未提供。',
      502: '回答生成未成功，沒有接受此回答。請查看後端紀錄；系統不會自動重試。',
      503: '目前無法產生回答。請確認後端已啟用生成、設定 API Key，且未達呼叫或費用上限。',
    }
    throw new ApiError(response.status, (messages[response.status] || '後端處理失敗，請檢查服務與本機模型。') + (original ? `
後端訊息：${original}` : ''))
  }
  return data
}
export async function getHealth(signal?: AbortSignal): Promise<Health> {
  const data = await request('/health', { signal }) as Health
  if (data?.status !== 'ok' || typeof data.generation_enabled !== 'boolean') throw new ApiError(0, '後端健康檢查格式不正確。')
  return data
}
export async function uploadDocument(file: File): Promise<DocumentResult> {
  const form = new FormData()
  form.append('file', file.type ? file : new File([file], file.name, { type: 'application/pdf' }), file.name)
  const data = await request('/documents', { method: 'POST', body: form }) as DocumentResult
  if (!data || !/^[a-f0-9]{64}$/.test(data.document_id) || !Number.isInteger(data.pages) || !Number.isInteger(data.chunks)) throw new ApiError(0, '上傳回應缺少有效文件資訊，請檢查後端。')
  return data
}
export async function askDocument(documentId: string, question: string): Promise<AnswerResult> {
  const data = await request('/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ document_id: documentId, question, context_mode: 'baseline', task: 'auto' }) }) as AnswerResult
  if (!data || data.document_id !== documentId || typeof data.answer?.answer_markdown !== 'string' || !data.answer.answer_markdown.trim()) {
    throw new ApiError(0, 'Answer generation failed: no valid answer for this document.')
  }
  // Supporting metadata cannot veto an independently valid generated Answer.
  if (!Array.isArray(data.citation_warnings) || !data.citation_warnings.every(w => w && typeof w.code === 'string' && typeof w.message === 'string' && Array.isArray(w.source_ids))) data.citation_warnings = []
  const warn = (message: string) => data.citation_warnings!.push({ code: 'auxiliary_metadata_invalid', message, source_ids: [] })
  const sourceValid = (s: Source) => s && typeof s.evidence_id === 'string' && Array.isArray(s.pages) && s.pages.every(Number.isInteger) && typeof s.text === 'string' && (s.quotes === undefined || (Array.isArray(s.quotes) && s.quotes.every(q => typeof q === 'string')))
  if (!Array.isArray(data.sources)) { data.sources = []; warn('Sources unavailable; generated answer retained.') }
  else {
    const valid = data.sources.filter(sourceValid)
    if (valid.length !== data.sources.length) warn('Some sources unavailable; generated answer retained.')
    data.sources = valid
  }
  if (data.unverified_sources !== undefined) data.unverified_sources = Array.isArray(data.unverified_sources) ? data.unverified_sources.filter(sourceValid) : []
  if (data.supporting_evidence !== undefined && (!data.supporting_evidence || typeof data.supporting_evidence.numeric_markdown !== 'string' || !Array.isArray(data.supporting_evidence.citations) || !Array.isArray(data.supporting_evidence.numeric_claims))) {
    data.supporting_evidence = undefined
    warn('Supporting evidence unavailable; generated answer retained.')
  }
  if (data.supporting_tables !== undefined && (!Array.isArray(data.supporting_tables) || !data.supporting_tables.every(table =>
    table && typeof table.table_id === 'string' && Array.isArray(table.rows) && table.rows.every(row =>
      row && ['method', 'dataset', 'metric', 'value', 'evidence_id'].every(key => typeof row[key as keyof typeof row] === 'string') &&
      Array.isArray(row.comparison_methods) && row.comparison_methods.every(method => typeof method === 'string') && Array.isArray(row.pages)) &&
    (table.native_grid === undefined || (Array.isArray(table.native_grid) && table.native_grid.every(row => Array.isArray(row) && row.every(cell => typeof cell === 'string'))))))) {
    data.supporting_tables = undefined
    warn('Supporting tables unavailable; generated answer retained.')
  }
  return data
}
