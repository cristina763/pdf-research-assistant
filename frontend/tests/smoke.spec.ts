import { test, expect } from '@playwright/test'

test('upload, repeated questions, citations and reload without stored conversation', async ({ page }) => {
  let calls = 0
  await page.route(/^https?:\/\/(?!127\.0\.0\.1|localhost)/, route => route.abort())
  await page.route('**/api/health', route => route.fulfill({ json: { status: 'ok', generation_enabled: true, api_key_configured: true, max_upload_bytes: 30000000 } }))
  await page.route('**/api/documents', route => route.fulfill({ json: { document_id: 'a'.repeat(64), pages: 1, chunks: 2, cache_hit: false, elapsed_seconds: 0.01 } }))
  await page.route('**/api/ask', async route => {
    calls++
    const body = route.request().postDataJSON()
    expect(body.task).toBe('auto')
    await route.fulfill({ headers: { 'Cache-Control': 'no-store' }, json: {
      document_id: 'a'.repeat(64), answer: { answer_markdown: `Mock flow response ${calls}. [C1]`, evidence_status: 'manual_review', limitations: [] },
      sources: [{ evidence_id: 'C1', pages: [1], source_refs: ['#/texts/0'], text: 'Synthetic original document evidence.', quotes: [], support_status: 'mapped' }],
      supporting_tables: [], review_policy: 'manual', citation_warnings: [], input_tokens: 100, cache_hit: false, elapsed_seconds: 0.01,
      answer_status: 'answered', supporting_evidence: { numeric_markdown: 'Separate evidence marker: original values.', citations: [{ evidence_id: 'C1', pages: [1] }], numeric_claims: [] },
      generation: { status: 'completed', model: 'mock-only', usage: { input_tokens: 100, output_tokens: 50, total_tokens: 150 }, generation_latency_seconds: 0.01, recovered_existing_response: false, new_paid_generation: true },
    } })
  })
  await page.goto('/')
  await expect(page.getByRole('region', { name: '後端狀態' })).toContainText('後端已連線')
  await page.getByLabel('選擇 PDF 檔案').setInputFiles({ name: 'sample.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-synthetic') })
  for (let i = 1; i <= 2; i++) {
    await page.getByRole('textbox', { name: '問題', exact: true }).fill('retrieval evidence')
    await page.getByRole('button', { name: '送出問題' }).click()
    await expect(page.getByRole('region', { name: '回答', exact: true })).toContainText(`Mock flow response ${i}`)
    await expect(page.getByRole('button', { name: '送出問題' })).toBeEnabled()
  }
  expect(calls).toBe(2)
  await expect(page.locator('.answer-card .markdown')).toHaveText('Mock flow response 2. [C1]')
  await expect(page.locator('.answer-card')).not.toContainText('Separate evidence marker')
  const evidence = page.getByRole('region', { name: 'Supporting Evidence', exact: true })
  await expect(evidence.locator('details')).toHaveJSProperty('open', false)
  await evidence.locator('summary').click()
  await expect(evidence.locator('.markdown')).toBeVisible()
  await expect(evidence).toContainText('Separate evidence marker')
  await expect(page.getByRole('region', { name: '引用來源' })).toContainText('Synthetic original document evidence.')
  expect(await page.evaluate(async () => ({ local: localStorage.length, session: sessionStorage.length, db: (await indexedDB.databases()).length }))).toEqual({ local: 0, session: 0, db: 0 })
  await page.route('**/api/ask', route => route.fulfill({ json: {
    document_id: 'a'.repeat(64), answer: { answer_markdown: 'Complete generated analysis survives auxiliary failure. [C1]', evidence_status: 'manual_review', limitations: [] },
    sources: 'invalid auxiliary sources', supporting_tables: 'invalid auxiliary tables', supporting_evidence: null,
    cache_hit: false, elapsed_seconds: 0.01,
  } }))
  await page.locator('#question').fill('retrieval evidence auxiliary failure')
  await page.locator('form button[type="submit"]').click()
  await expect(page.locator('.answer-card .markdown')).toHaveText('Complete generated analysis survives auxiliary failure. [C1]')
  await expect(page.getByRole('alert')).toHaveCount(0)
  await page.route('**/api/ask', route => route.fulfill({ status: 422, json: { detail: 'Answer generation failed: no prose.', validation_status: 'rejected' } }))
  await page.locator('#question').fill('retrieval evidence failure')
  await page.locator('form button[type="submit"]').click()
  await expect(page.getByRole('alert')).toContainText('Answer generation failed')
  await expect(page.locator('.answer-card')).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Supporting Evidence', exact: true })).toHaveCount(0)
  await page.reload()
  await expect(page.getByRole('region', { name: '回答', exact: true })).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: '問題', exact: true })).toHaveValue('')
})
