import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// element-plus 只用于全局错误提示，单测里替换掉，避免加载整库
vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

import { askStream, regenerateStream, type SseHandlers } from '@/api'

/**
 * SSE 解析的回归测试。
 *
 * 背景：`streamSse` 曾有两个真实缺陷——
 * ① 流在 `done`/`error` 之前断开时不回调任何终态事件 → 页面永久卡在「生成中」；
 * ② 结尾处被切开的 UTF-8 多字节字符会丢失（没有冲刷解码器）。
 * 这里把 fetch stub 成可控的字节流来覆盖这些边界。
 */

const encoder = new TextEncoder()

function streamResponse(chunks: (string | Uint8Array)[], init: { ok?: boolean; status?: number } = {}) {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) {
        controller.enqueue(typeof c === 'string' ? encoder.encode(c) : c)
      }
      controller.close()
    },
  })
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    body: stream,
  } as unknown as Response
}

function collecting() {
  const calls = {
    sources: [] as unknown[],
    deltas: [] as string[],
    done: [] as unknown[],
    errors: [] as string[],
    aborts: 0,
  }
  const handlers: SseHandlers = {
    onSources: (s) => calls.sources.push(s),
    onDelta: (t) => calls.deltas.push(t),
    onDone: (d) => calls.done.push(d),
    onError: (m) => calls.errors.push(m),
    onAbort: () => {
      calls.aborts += 1
    },
  }
  return { calls, handlers }
}

function stubFetch(resp: Response | (() => never)) {
  // 显式声明入参，否则 vi.fn 会推断成零参数函数，取不出 mock.calls[0][0]
  const fn = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => {
    if (typeof resp === 'function') resp()
    return resp as Response
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

beforeEach(() => {
  vi.unstubAllGlobals()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('askStream 正常路径', () => {
  it('依次派发 sources / delta / done', async () => {
    stubFetch(
      streamResponse([
        'event: sources\ndata: [{"document_title":"A"}]\n\n',
        'event: delta\ndata: {"text":"你好"}\n\n',
        'event: delta\ndata: {"text":"世界"}\n\n',
        'event: done\ndata: {"message_id":"m1","sources":[],"source_type":"kb"}\n\n',
      ]),
    )
    const { calls, handlers } = collecting()
    await askStream('c1', { question: 'q' }, handlers)

    expect(calls.sources).toHaveLength(1)
    expect(calls.deltas).toEqual(['你好', '世界'])
    expect(calls.done).toHaveLength(1)
    expect(calls.errors).toEqual([])
  })

  it('跨 chunk 切断的单个事件也能正确重组', async () => {
    // 把同一个事件拆到三个 chunk 里，其中最后一个 data 行被拦腰截断
    stubFetch(
      streamResponse([
        'event: del',
        'ta\ndata: {"te',
        'xt":"拼接成功"}\n\n',
        'event: done\ndata: {"message_id":"m2","sources":[]}\n\n',
      ]),
    )
    const { calls, handlers } = collecting()
    await askStream('c1', { question: 'q' }, handlers)

    expect(calls.deltas).toEqual(['拼接成功'])
    expect(calls.done).toHaveLength(1)
  })

  it('把 data: 行按换行连接：在 JSON 词法边界切分时仍能解析', async () => {
    stubFetch(
      streamResponse([
        // 同一个 JSON 被拆到两行 data:，跨行处是合法的 JSON 词法边界
        'event: done\ndata: {"message_id":"m3",\ndata: "sources":[]}\n\n',
      ]),
    )
    const { calls, handlers } = collecting()
    await askStream('c1', { question: 'q' }, handlers)
    expect(calls.done).toHaveLength(1)
    expect((calls.done[0] as { message_id: string }).message_id).toBe('m3')
  })

  it('在字符串内部被切开时宁可丢弃该事件，也不静默拼出错误内容', async () => {
    // 旧实现用 `data += line.slice(5).trim()` 直接首尾相接，会得到
    // {"text":"abcdef"} —— 一个**静默的错误内容**。按 \n 连接后 JSON 解析失败，
    // 该事件被丢弃（失败是安全的，错误内容不是）。
    stubFetch(
      streamResponse([
        'event: delta\ndata: {"text":"abc\ndata: def"}\n\n',
        'event: done\ndata: {"message_id":"m4","sources":[]}\n\n',
      ]),
    )
    const { calls, handlers } = collecting()
    await askStream('c1', { question: 'q' }, handlers)
    expect(calls.deltas).not.toContain('abcdef')
    expect(calls.done).toHaveLength(1)
  })
})

describe('askStream 异常路径', () => {
  it('流提前结束（没有 done/error）必须报「连接中断」', async () => {
    // 这正是「页面永久卡在生成中」的成因：此前这里什么都不回调
    stubFetch(
      streamResponse(['event: delta\ndata: {"text":"半截"}\n\n']),
    )
    const { calls, handlers } = collecting()
    await askStream('c1', { question: 'q' }, handlers)

    expect(calls.deltas).toEqual(['半截'])
    expect(calls.done).toEqual([])
    expect(calls.errors).toHaveLength(1)
    expect(calls.errors[0]).toContain('连接中断')
  })

  it('后端显式下发 error 事件时透出该消息', async () => {
    stubFetch(
      streamResponse(['event: error\ndata: {"message":"模型不可用"}\n\n']),
    )
    const { calls, handlers } = collecting()
    await askStream('c1', { question: 'q' }, handlers)
    expect(calls.errors).toEqual(['模型不可用'])
  })

  it('HTTP 非 2xx 时回调错误', async () => {
    stubFetch(streamResponse([], { ok: false, status: 503 }))
    const { calls, handlers } = collecting()
    await askStream('c1', { question: 'q' }, handlers)
    expect(calls.errors[0]).toContain('503')
  })

  it('请求被中止（signal 已 abort）回调 onAbort 而不是 onError', async () => {
    const controller = new AbortController()
    stubFetch(() => {
      controller.abort()
      throw new Error('aborted')
    })
    const { calls, handlers } = collecting()
    await askStream('c1', { question: 'q' }, handlers, controller.signal)
    expect(calls.aborts).toBe(1)
    expect(calls.errors).toEqual([])
  })
})

describe('regenerateStream', () => {
  it('use_web 会带进查询串', async () => {
    const fn = stubFetch(
      streamResponse(['event: done\ndata: {"message_id":"m4","sources":[]}\n\n']),
    )
    const { handlers } = collecting()
    await regenerateStream('msg1', handlers, undefined, true)
    expect(fn.mock.calls[0][0]).toBe('/api/messages/msg1/regenerate?use_web=true')
  })
})
