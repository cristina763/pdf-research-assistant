import type { AnswerResult } from './api'

export function reviewExport(question: string, result: AnswerResult): string {
  const lines = ['問題', question, '', '模型回答（供人工核對，未作自動品質驗收）', result.answer.answer_markdown, '', '本次回答引用的 PDF 原文']
  if (result.supporting_evidence?.numeric_markdown) {
    lines.push('', 'Supporting Evidence (source values and computed comparisons)', result.supporting_evidence.numeric_markdown)
  }
  const seen = new Set<string>()
  for (const source of result.sources) {
    const key = JSON.stringify([source.evidence_id, source.pages, source.text])
    if (seen.has(key)) continue
    seen.add(key)
    lines.push('', `[${source.evidence_id}] 第 ${source.pages.join('、')} 頁`, source.text)
  }
  if (!result.sources.length) lines.push('沒有可對應的引用來源。')
  const warnings = result.citation_warnings ?? []
  if (warnings.length) lines.push('', '來源映射注意事項', ...warnings.map(warning => `${warning.source_ids.join('、')} ${warning.message}`))
  const ids = new Set(result.sources.map(source => source.evidence_id))
  const tables = new Set<string>()
  for (const table of result.supporting_tables ?? []) {
    if (!table.evidence_ids.some(id => ids.has(id))) continue
    const key = JSON.stringify([table.pages, table.native_grid])
    if (tables.has(key)) continue
    tables.add(key)
    lines.push('', `原生表格 ${table.table_number ?? table.table_id} · 第 ${table.pages.join('、')} 頁 · ${table.evidence_ids.join('、')}`)
    if (table.native_grid?.length) lines.push(...table.native_grid.map(row => row.join('\t')))
    else lines.push('未提供原生表格資料；沒有推算或補造數據。')
  }
  return lines.join('\n')
}
