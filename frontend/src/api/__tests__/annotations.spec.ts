/**
 * 批注接口的客户端行为。
 *
 * 只测两件容易退化、且退化了会**静默出错**的事：
 * 1. PDF 原始文件的 URL 是否带上访问口令（局域网模式下不带就打不开文件）；
 * 2. 导出的幂等语义有没有被前端改写（`created` 决定提示语，不能想当然）。
 */
import { afterEach, describe, expect, it } from 'vitest'
import { annotationsApi } from '@/api'
import { setAccessToken } from '@/api/client'

const DOC = '11111111-2222-3333-4444-555555555555'

afterEach(() => {
  setAccessToken('')
})

describe('annotationsApi.fileUrl', () => {
  it('未设口令时是干净的路径（本机默认场景）', () => {
    setAccessToken('')
    expect(annotationsApi.fileUrl(DOC)).toBe(`/api/documents/${DOC}/file`)
  })

  it('⭐ 设了口令时把口令放进查询串', () => {
    // pdf.js 为分片加载会自行发起请求（带 Range 头），不一定经过 axios 实例，
    // 所以口令必须进 URL —— 只放在请求头里的话局域网模式下 PDF 打不开。
    setAccessToken('s3cret token/&=')
    const url = annotationsApi.fileUrl(DOC)
    expect(url).toContain(`/api/documents/${DOC}/file?token=`)
    // 口令可能含特殊字符，必须编码，否则查询串会被截断
    expect(url).toContain(encodeURIComponent('s3cret token/&='))
    expect(url.endsWith(encodeURIComponent('s3cret token/&='))).toBe(true)
  })

  it('口令变化后 URL 跟着变（不缓存旧值）', () => {
    setAccessToken('first')
    const a = annotationsApi.fileUrl(DOC)
    setAccessToken('second')
    const b = annotationsApi.fileUrl(DOC)
    expect(a).not.toBe(b)
    expect(b).toContain('second')
  })
})

describe('批注接口的路径与契约', () => {
  it('导出走 /documents/{id}/annotations/export（静态段在后，不是 /{annotation_id}）', async () => {
    const { default: client } = await import('@/api/client')
    const calls: string[] = []
    const original = client.post
    // @ts-expect-error 测试替身
    client.post = (url: string) => {
      calls.push(url)
      return Promise.resolve({ data: { document_id: 'x', title: 't', annotation_count: 0, created: true } })
    }
    try {
      await annotationsApi.exportNote(DOC)
    } finally {
      client.post = original
    }
    expect(calls[0]).toBe(`/documents/${DOC}/annotations/export`)
  })
})
