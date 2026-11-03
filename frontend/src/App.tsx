import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowUpRight, BookOpen, Check, CheckCircle2, ChevronDown, CircleAlert, FileText, LoaderCircle, Plus, RefreshCw, Upload, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { reviewExport } from './reviewExport'
import { ApiError, askDocument, getHealth, uploadDocument } from './api'
import type { AnswerResult, DocumentResult, Health, Source, SupportingTable } from './api'

type ActiveDocument = DocumentResult & { name: string }
type Exchange = { question: string; result: AnswerResult }
const seconds = (value: number) => Number.isFinite(value) ? `${value.toFixed(1)} 秒` : '—'
const errorText = (error: unknown) => error instanceof Error ? error.message : '發生未預期的錯誤，請檢查後端服務。'

// Remove only the known generated envelope, never arbitrary PDF lines.
function originalText(text: string) {
  const lines = text.split(/\r?\n/)
  if (/^\[(?:C|S)\d+ \| PDF pages \[.*\] \| chunks .*\]$/.test(lines[0] ?? '')) {
    lines.shift()
    if (lines[0]?.startsWith('Section: ')) lines.shift()
  }
  return lines.join('\n')
}
function uniqueSources(sources: Source[]) {
  const groups = new Map<string, Source>()
  for (const source of sources) {
    const text = originalText(source.text)
    const key = JSON.stringify([text, [...source.pages].sort((a,b) => a-b)])
    const existing = groups.get(key)
    if (existing) {
      existing.evidence_id = [...new Set([...existing.evidence_id.split('、'), source.evidence_id])].join('、')
      existing.quotes = [...new Set([...(existing.quotes ?? []), ...(source.quotes ?? [])].map(originalText))]
    } else groups.set(key, { ...source, text, quotes: source.quotes?.map(originalText) })
  }
  return [...groups.values()]
}
function uniqueTables(tables: SupportingTable[]) {
  const seen = new Set<string>()
  return tables.filter(table => {
    const key = JSON.stringify([table.table_number, table.pages, table.rows, table.native_grid])
    if (seen.has(key)) return false
    seen.add(key); return true
  })
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState('')
  const [checking, setChecking] = useState(true)
  const [document, setDocument] = useState<ActiveDocument | null>(null)
  const [question, setQuestion] = useState('')
  const [exchange, setExchange] = useState<Exchange | null>(null)
  const [busy, setBusy] = useState<'upload' | 'ask' | null>(null)
  const [error, setError] = useState('')
  const [copyStatus, setCopyStatus] = useState('')
  const [copying, setCopying] = useState(false)
  const [uploadName, setUploadName] = useState('')
  const [dragging, setDragging] = useState(false)
  const actionLock = useRef(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const answerRegion = useRef<HTMLElement>(null)
  const mounted = useRef(true)
  const maxBytes = health?.max_upload_bytes ?? 30 * 1024 * 1024
  const ready = !!health?.generation_enabled && health.api_key_configured !== false

  useEffect(() => {
    mounted.current = true
    const controller = new AbortController()
    getHealth(controller.signal).then(data => { if (mounted.current) { setHealth(data); setHealthError('') } })
      .catch(error => { if (mounted.current && !controller.signal.aborted) setHealthError(errorText(error)) })
      .finally(() => { if (mounted.current && !controller.signal.aborted) setChecking(false) })
    return () => { mounted.current = false; controller.abort() }
  }, [])

  async function refreshHealth() {
    if (checking) return
    setChecking(true)
    try { setHealth(await getHealth()); setHealthError('') }
    catch (error) { setHealth(null); setHealthError(errorText(error)) }
    finally { setChecking(false) }
  }

  async function upload(file?: File) {
    if (!file || actionLock.current) return
    if (!file.name.toLowerCase().endsWith('.pdf') || (file.type && file.type !== 'application/pdf')) { setError('請選擇 PDF 檔案。'); return }
    if (file.size > maxBytes) { setError(`PDF 超過 ${Math.round(maxBytes / 1024 / 1024)} MB 上傳上限。`); return }
    actionLock.current = true; setBusy('upload'); setError(''); setUploadName(file.name)
    try {
      const result = await uploadDocument(file)
      if (!mounted.current) return
      setDocument({ ...result, name: file.name }); setQuestion(''); setExchange(null); setCopyStatus('')
    } catch (error) { if (mounted.current) setError(errorText(error)) }
    finally { actionLock.current = false; if (mounted.current) setBusy(null); if (fileInput.current) fileInput.current.value = '' }
  }

  async function ask(event: FormEvent) {
    event.preventDefault()
    const submitted = question.trim()
    if (actionLock.current || !document || !submitted || !ready) return
    actionLock.current = true; setBusy('ask'); setError(''); setExchange(null)
    try {
      const result = await askDocument(document.document_id, submitted)
      if (mounted.current) { setExchange({ question: submitted, result }); setCopyStatus(''); requestAnimationFrame(() => answerRegion.current?.focus({ preventScroll: true })) }
    } catch (error) {
      if (mounted.current) {
        setError(errorText(error))
        if (error instanceof ApiError && error.status === 404) { setDocument(null); setExchange(null) }
        if (error instanceof ApiError && error.status === 503) void refreshHealth()
      }
    } finally { actionLock.current = false; if (mounted.current) setBusy(null) }
  }

  async function copyAnswer() {
    if (!exchange || copying) return
    setCopying(true); setCopyStatus('')
    try { await navigator.clipboard.writeText(reviewExport(exchange.question, exchange.result)); setCopyStatus('已複製回答與來源') }
    catch { setCopyStatus('無法存取剪貼簿，請允許瀏覽器複製權限後再試。') }
    finally { setCopying(false) }
  }

  const confirmedSources = uniqueSources(exchange?.result.sources ?? [])
  const unverifiedSources = uniqueSources(exchange?.result.unverified_sources ?? [])
  const supportingTables = uniqueTables(exchange?.result.supporting_tables ?? [])

  const displayedAnswer = exchange?.result.answer.answer_markdown ?? ''

  const serviceMessage = checking ? '正在確認服務狀態…' : healthError ? '後端尚未連線' : !health?.generation_enabled ? '回答生成尚未啟用' : health.api_key_configured === false ? '尚未設定 API Key' : '後端已連線，回答生成可用'

  return <div className="app-shell">
    <header className="topbar">
      <h1 className="app-title">PDF RAG Assistant</h1>
    </header>
    <main className="workspace">
      <aside className="sidebar">
        <h2>文件</h2>
        <input ref={fileInput} id="pdf-upload" type="file" accept=".pdf,application/pdf" className="visually-hidden" aria-label="選擇 PDF 檔案" disabled={!!busy} onChange={e => void upload(e.target.files?.[0])}/>
        <button type="button" className={`upload-zone ${dragging ? 'dragging' : ''}`} disabled={!!busy || !health}
          onClick={() => fileInput.current?.click()} onDragOver={e => { e.preventDefault(); if (!busy) setDragging(true) }} onDragLeave={() => setDragging(false)}
          onDrop={e => { e.preventDefault(); setDragging(false); if (!busy && health) void upload(e.dataTransfer.files[0]) }}>
          <span className="upload-icon">{busy === 'upload' ? <LoaderCircle className="spin" size={24}/> : <Upload size={24} strokeWidth={1.6}/>}</span>
          <strong>{busy === 'upload' ? '解析並建立索引中…' : document ? '上傳另一份 PDF' : '上傳 PDF'}</strong>
          <span>{busy === 'upload' ? uploadName : '點擊選擇，或拖曳檔案至此'}</span><small>PDF · 最大 {Math.round(maxBytes / 1024 / 1024)} MB</small>
        </button>
        {document && <section className="document-card" aria-label="目前文件">
          <div className="document-top"><FileText size={21}/><span className="ready-tag"><Check size={12}/>已建立索引</span></div>
          <h3 title={document.name}>{document.name}</h3><div className="document-stats"><span>{document.pages} 頁</span><span>{document.chunks} Chunks</span></div>
          <div className="document-foot"><CheckCircle2 size={13}/>PDF 處理時間：{seconds(document.elapsed_seconds)}</div>
          <details className="document-details"><summary>詳細資訊 <ChevronDown size={13}/></summary><div className="detail-content"><span>文件識別碼</span><code>{document.document_id}</code><p>快取：{document.cache_hit ? '已重用本機快取' : '本次新建'}</p></div></details>
        </section>}
        <section className="service-card" aria-label="後端狀態">
          <div className="service-title"><span className={`status-dot ${ready ? 'online' : ''}`}/><strong>{serviceMessage}</strong><button type="button" className="icon-button" aria-label="重新檢查服務" onClick={() => void refreshHealth()} disabled={checking || !!busy}><RefreshCw size={14} className={checking ? 'spin' : ''}/></button></div>
          {!ready && !checking && <details className="service-details"><summary>詳細資訊 <ChevronDown size={13}/></summary><p>{healthError || (!health?.generation_enabled ? '產生回答前，請在後端啟用生成並設定 API Key。' : '請在後端環境變數設定 OPENAI_API_KEY，然後重新檢查服務。')}</p></details>}
        </section>
      </aside>
      <div className="research-panel">
        <div aria-live="polite" className="status-announcer">{busy === 'upload' ? 'PDF 解析與索引建立中，請稍候。' : busy === 'ask' ? '正在根據文件產生回答，請勿重複提交。' : ''}</div>
        {error && <div className="error-banner" role="alert"><CircleAlert size={19}/><div><strong>目前無法完成操作</strong><p>{error}</p></div><button className="icon-button" type="button" aria-label="關閉錯誤訊息" onClick={() => setError('')}><X size={16}/></button></div>}
        {!exchange && busy !== 'ask' && <section className="empty-state"><p>{document ? '請輸入問題' : '請先上傳 PDF'}</p></section>}
        {exchange && <section className="answer-region" ref={answerRegion} tabIndex={-1} aria-label="回答">
          <div className="question-block"><span className="section-label">問題</span><h2>{exchange.question}</h2></div>
          <article className="answer-card"><div className="answer-toolbar"><span>{exchange.result.summary_status === 'partial' ? '部分摘要' : '回答'}</span><button type="button" className="copy-answer" onClick={() => void copyAnswer()} disabled={copying}>{copying ? '複製中…' : '複製回答與來源'}</button><small>回答時間：{seconds(exchange.result.elapsed_seconds)}</small></div>
            {copyStatus && <p className="copy-status" role="status">{copyStatus}</p>}
            {exchange.result.citation_warnings?.some(warning => warning.code === 'unmapped_citation') && <p className="citation-notice" role="status">部分引用無法對應原文，請在技術詳細資訊核對。</p>}
            <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={{a: ({href, children}) => <a href={href} target="_blank" rel="noopener noreferrer">{children}<ArrowUpRight size={12}/></a>, img: () => <span>［來源內含圖片，請至 PDF 檢視］</span>}}>{displayedAnswer}</ReactMarkdown></div>
          </article>
          <section className="sources-section" aria-label="引用來源"><div className="section-title"><h3><BookOpen size={17}/>引用來源</h3><span>{confirmedSources.length} 段原文</span></div>
            {confirmedSources.length === 0 ? <p className="muted">目前沒有可對應的引用來源。</p> : <div className="sources-grid">{confirmedSources.map(source => <details className="source-card" key={source.evidence_id}><summary><span className="source-label">[{source.evidence_id}]</span><strong>第 {source.pages.join('、')} 頁</strong><ChevronDown size={15}/></summary>{source.quotes && source.quotes.some(quote => !source.text.includes(quote)) && <div className="selected-quotes"><strong>引用片段</strong>{[...new Set(source.quotes)].filter(quote => !source.text.includes(quote)).map((quote, index) => <blockquote key={index}>{quote}</blockquote>)}</div>}<p>{source.text}</p></details>)}</div>}
          </section>
          {!!supportingTables.length && <section className="tables-section" aria-label="詳細表格與數值"><details className="supporting-tables"><summary>詳細表格與數值 <span>{supportingTables.length} 組</span><ChevronDown size={15}/></summary>{supportingTables.map(table => <div className="supporting-table" key={table.table_id}><h3>{table.table_number === null ? '結構化數值' : `Table ${table.table_number}`}</h3><p>{table.rows.length ? '以下為回答使用的完整結構化數值。' : '此表僅保留原始解析資料，尚無可靠的結構化數值對應。'}</p>{table.rows.length > 0 && <div className="table-scroll"><table><thead><tr><th>方法</th><th>資料集</th><th>指標</th><th>比較組</th><th>數值</th><th>來源</th></tr></thead><tbody>{table.rows.map((row, index) => <tr key={`${row.fact_id}-${index}`}><td>{row.method}</td><td>{row.dataset}</td><td>{row.metric}</td><td>{row.comparison_methods.join(' vs ')}</td><td>{row.value}</td><td>[{row.evidence_id}] · 第 {row.pages.join('、')} 頁</td></tr>)}</tbody></table></div>}{!!table.native_grid?.length && <details className="native-table"><summary>原始表格（解析結果）</summary><p>未經逐格人工確認，請搭配 PDF 核對。</p><div className="table-scroll"><table><tbody>{table.native_grid.map((row, index) => <tr key={index}>{row.map((cell, col) => <td key={col}>{cell}</td>)}</tr>)}</tbody></table></div></details>}</div>)}</details></section>}
          {exchange.result.supporting_evidence?.numeric_markdown && <section className="tables-section" aria-label="Supporting Evidence"><details className="supporting-evidence"><summary>Supporting Evidence · 數值與比較（展開核對）<ChevronDown size={15}/></summary><div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>{exchange.result.supporting_evidence.numeric_markdown}</ReactMarkdown></div></details></section>}
          <details className="answer-details technical-details" key={`${exchange.question}-${exchange.result.elapsed_seconds}`} >
            <summary>技術詳細資訊 <ChevronDown size={13}/></summary>
            <div className="diagnostic-summary"><p>快取：{(exchange.result.cache_hit || exchange.result.generation?.recovered_existing_response) ? '重用已保存回答' : exchange.result.generation?.new_paid_generation ? '本次重新生成，未使用答案快取' : '本次僅保留階段成果'}</p>{exchange.result.generation && <p>生成狀態：{exchange.result.generation.status === 'stages_completed' ? '已保留階段成果，未完成最終整合' : 'API 已完成'} · {exchange.result.generation.model} · 輸入 {exchange.result.generation.usage.input_tokens}／輸出 {exchange.result.generation.usage.output_tokens}／合計 {exchange.result.generation.usage.total_tokens} Tokens{exchange.result.generation.generation_latency_seconds !== null ? ` · 生成耗時 ${seconds(exchange.result.generation.generation_latency_seconds)}` : ' · 歷史生成耗時未記錄'}</p>}{!!exchange.result.citation_warnings?.length && <ul>{exchange.result.citation_warnings.map((warning, index) => <li key={index}>{warning.message}</li>)}</ul>}{exchange.result.summary_notes && <p>部分摘要原因：{exchange.result.summary_notes.reason}；缺少類別：{exchange.result.summary_notes.missing_categories.join('、') || '未列出缺漏'}</p>}</div>
          {exchange.result.summary_diagnostics && <details className="summary-stages"><summary>Segment 與模型呼叫紀錄 <ChevronDown size={13}/></summary><p>{exchange.result.summary_diagnostics.segment_count} 個 Segment；已記錄生成 {seconds(exchange.result.summary_diagnostics.recorded_generation_seconds)}、計數 {seconds(exchange.result.summary_diagnostics.recorded_count_seconds)}。歷史紀錄未完整量測規劃、驗證及傳輸耗時。</p><div className="table-scroll"><table><thead><tr><th>階段</th><th>處理結果</th><th>正式輸入</th><th>輸出預留</th><th>安全額度</th><th>完整預算／10K</th><th>生成／計數秒數</th><th>原因</th></tr></thead><tbody>{exchange.result.summary_diagnostics.stages.map(stage => <tr key={stage.stage}><td>{stage.stage}</td><td>{stage.status}{stage.fallback ? ' · 原文 fallback' : ''}</td><td>{stage.official_input_tokens ?? '未呼叫'}</td><td>{stage.output_reserve ?? '—'}</td><td>{stage.safety ?? '—'}</td><td>{stage.budget_total === null ? '—' : `${stage.budget_total} · ${stage.within_10k ? '符合' : '未確認'}`}</td><td>{stage.generation_seconds === null ? '—' : stage.generation_seconds.toFixed(2)}／{stage.count_seconds === null ? '—' : stage.count_seconds.toFixed(2)}</td><td>{[...stage.reasons, ...(stage.coverage_carried_categories?.length ? [`保留子筆記類別：${stage.coverage_carried_categories.join('、')}`] : [])].join('；') || '—'}</td></tr>)}</tbody></table></div>{!!exchange.result.summary_diagnostics.reduction_rounds?.length && <details className="validation-record"><summary>各輪縮減明細 <ChevronDown size={13}/></summary><pre>{JSON.stringify(exchange.result.summary_diagnostics.reduction_rounds, null, 2)}</pre></details>}{exchange.result.summary_diagnostics.partial_summary?.reason && <p>終止原因：{exchange.result.summary_diagnostics.partial_summary.reason}</p>}</details>}
          {!!unverifiedSources.length && <section className="unverified-section" aria-label="原始來源，待核對"><div className="section-title"><h3><CircleAlert size={17}/>原始來源，待核對</h3></div><p className="muted">以下只供查閱，尚未確認支持相應陳述。</p><div className="sources-grid">{unverifiedSources.map(source => <details className="source-card unverified-source" key={source.evidence_id}><summary><span className="source-label">[{source.evidence_id}]</span><strong>第 {source.pages.join('、')} 頁 · 待核對</strong><ChevronDown size={15}/></summary><p>{source.text}</p></details>)}</div></section>}

          </details>
        </section>}
        {busy === 'ask' && <div className="generating" role="status"><LoaderCircle className="spin" size={22}/><div><strong>正在產生回答…</strong></div></div>}
        <form className="question-form" onSubmit={event => void ask(event)}>
          <label htmlFor="question">問題</label><div className="composer"><textarea id="question" value={question} onChange={e => setQuestion(e.target.value)} placeholder={document ? '請輸入問題' : '請先上傳 PDF'} maxLength={4000} rows={2} disabled={!document || !!busy} aria-describedby="question-help"/>
            <div className="composer-bottom"><span><FileText size={13}/>{document ? document.name : '尚未選擇文件'}</span><button className="ask-button" type="submit" disabled={!document || !question.trim() || !ready || !!busy}>{busy === 'ask' ? <LoaderCircle size={16} className="spin"/> : <Plus size={17}/>}<span>{busy === 'ask' ? '正在處理' : '送出問題'}</span></button></div>
          </div><div className="composer-help" id="question-help"><span>{!ready ? '回答生成尚未就緒。' : ''}</span><span>{question.length} / 4000</span></div>
        </form>
      </div>
    </main>
  </div>
}
