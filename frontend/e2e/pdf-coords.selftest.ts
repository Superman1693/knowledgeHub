import * as pdfjsLib from 'pdfjs-dist'
      import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
      import { rangeToNormalizedRects, locateQuoteInLayer } from '/src/utils/pdfAnchor.ts'
      import '@/styles/pdfTextLayer.css'

      // ?worker=1 走真实 worker（验 R2）；默认让 pdf.js 在主线程跑，
      // 因为 Chrome 的 --virtual-time-budget 不推进 worker 的时间线
      const useWorker = new URLSearchParams(location.search).has('worker')
      if (useWorker) pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl
      const WORKER_MODE = useWorker ? '真实 worker' : '主线程'

      const lines = []
      let failures = 0
      const log = (ok, label, detail = '') => {
        if (!ok) failures++
        lines.push(`${ok ? '✓' : '✗'} ${label}${detail ? '  ' + detail : ''}`)
        document.getElementById('result').innerHTML = lines
          .map((l) =>
            l.startsWith('✓') ? `<span class="ok">${l}</span>` : `<span class="bad">${l}</span>`,
          )
          .join('\n')
      }

      const MAX_DRIFT_PX = 1.5

      async function renderPage(pdf, pageNo, scale, host) {
        host.innerHTML = ''
        const pdfPage = await pdf.getPage(pageNo)
        const viewport = pdfPage.getViewport({ scale })
        const pageEl = document.createElement('div')
        pageEl.className = 'pdf-page'
        pageEl.dataset.page = String(pageNo)
        pageEl.style.position = 'relative'
        pageEl.style.width = `${Math.round(viewport.width)}px`
        pageEl.style.height = `${Math.round(viewport.height)}px`
        pageEl.style.setProperty('--scale-factor', String(scale))

        const canvas = document.createElement('canvas')
        canvas.width = Math.floor(viewport.width)
        canvas.height = Math.floor(viewport.height)
        canvas.style.width = canvas.width + 'px'
        canvas.style.height = canvas.height + 'px'
        pageEl.appendChild(canvas)

        const hl = document.createElement('div')
        hl.className = 'kh-hl'
        hl.style.cssText = 'position:absolute;inset:0;z-index:1;pointer-events:none'
        pageEl.appendChild(hl)

        const textLayerEl = document.createElement('div')
        textLayerEl.className = 'textLayer'
        pageEl.appendChild(textLayerEl)
        host.appendChild(pageEl)

        await pdfPage.render({ canvasContext: canvas.getContext('2d'), viewport }).promise
        const textContent = await pdfPage.getTextContent()
        const layer = new pdfjsLib.TextLayer({
          textContentSource: textContent,
          container: textLayerEl,
          viewport,
        })
        await layer.render()
        return { pageEl, textLayerEl, hl, viewport, rotation: pdfPage.rotate }
      }

      /**
       * 在文本层里定位 needle。
       *
       * ⚠️ 不能只在单个文本节点里 indexOf：pdf.js 会把一行按文本项拆成多个 span，
       * 「Proxy replaces」往往跨两个节点。这里直接用生产代码里的跨节点定位，
       * 顺带把「坐标丢失后靠引文重定位」这条路径也验了。
       */
      function selectText(textLayerEl, needle) {
        const hit = locateQuoteInLayer(textLayerEl, { quote: needle, prefix: null, suffix: null })
        return hit ? hit.range : null
      }

      function paint(hl, rects) {
        hl.innerHTML = ''
        for (const r of rects) {
          const d = document.createElement('div')
          d.style.cssText = `position:absolute;left:${r.x * 100}%;top:${r.y * 100}%;width:${
            r.w * 100
          }%;height:${r.h * 100}%;background:rgba(242,201,76,.55)`
          hl.appendChild(d)
        }
        return [...hl.children]
      }

      /**
       * 高亮与原文的对齐程度。
       *
       * ⚠️ 必须比**并集包围盒**，不能比「第 1 个矩形」：
       * pdf.js 会把一行按文本项拆成多个碎片矩形（实测选中 4 个，因为跨行 + 跨 span），
       * 而 `normalizeRects` 会把同一行内相邻的碎片合并成 1 个。
       * 数量本就不同，逐个比大小会把「合并得正确」误判成「对不齐」。
       * 语义上要断言的是：**高亮覆盖的像素范围 == 所选文字覆盖的像素范围**。
       */
      function union(rects) {
        const left = Math.min(...rects.map((r) => r.left))
        const top = Math.min(...rects.map((r) => r.top))
        const right = Math.max(...rects.map((r) => r.left + r.width))
        const bottom = Math.max(...rects.map((r) => r.top + r.height))
        return { left, top, width: right - left, height: bottom - top }
      }

      function drift(hlRects, range) {
        const painted = union(hlRects.map((el) => el.getBoundingClientRect()))
        const target = union([...range.getClientRects()])
        const parts = {
          dL: painted.left - target.left,
          dT: painted.top - target.top,
          dW: painted.width - target.width,
          dH: painted.height - target.height,
        }
        const f = (n) => n.toFixed(2)
        const detail =
          `ΔL=${f(parts.dL)} ΔT=${f(parts.dT)} ΔW=${f(parts.dW)} ΔH=${f(parts.dH)} | ` +
          `并集 高亮=${f(painted.left)},${f(painted.top)} ${f(painted.width)}x${f(painted.height)} | ` +
          `原文=${f(target.left)},${f(target.top)} ${f(target.width)}x${f(target.height)}`
        return {
          max: Math.max(
            Math.abs(parts.dL),
            Math.abs(parts.dT),
            Math.abs(parts.dW),
            Math.abs(parts.dH),
          ),
          detail,
        }
      }

      async function run() {
        let pdf
        try {
          pdf = await pdfjsLib.getDocument({
            url: '/e2e/fixtures/rotated.pdf',
            cMapUrl: '/pdfjs/cmaps/',
            cMapPacked: true,
            standardFontDataUrl: '/pdfjs/standard_fonts/',
          }).promise
        } catch (e) {
          log(false, 'PDF 加载失败', String(e))
          document.title = 'DONE FAIL'
          return
        }
        log(true, `PDF 已加载（${WORKER_MODE}），共 ${pdf.numPages} 页`)

        const host = document.getElementById('pages')
        const NEEDLE = 'Proxy replaces'

        // ---------- 第 1 页（rotation 0）----------
        const scale1 = 1
        const r1 = await renderPage(pdf, 1, scale1, host)
        log(r1.rotation === 0, '第 1 页 rotation=0')

        const layerText = r1.textLayerEl.textContent || ''
        const spans = r1.textLayerEl.querySelectorAll('span').length
        log(layerText.length > 0, `文本层非空：${spans} 个 span，${layerText.length} 字`, layerText.slice(0, 60))

        const probe = selectText(r1.textLayerEl, NEEDLE)
        if (!probe) {
          log(false, '在文本层里找不到目标文字（cMap 未生效？）')
          document.title = 'DONE FAIL'
          return
        }
        log(true, `文本层可划词："${probe.toString()}"`)

        const stored = rangeToNormalizedRects(probe, r1.pageEl)
        log(stored.length > 0, `归一化矩形数 ${stored.length}`)
        log(
          stored.every((r) => r.x >= 0 && r.y >= 0 && r.x + r.w <= 1.001 && r.y + r.h <= 1.001),
          '归一化矩形全部落在 [0,1]',
        )

        const painted1 = paint(r1.hl, stored)
        const d1 = drift(painted1, probe)
        log(d1.max < MAX_DRIFT_PX, `scale=1 高亮与原文对齐`, d1.detail)

        // ---------- 同一页换成 scale=2，用**同一份归一化矩形**重绘 ----------
        const scale2 = 2
        const r2 = await renderPage(pdf, 1, scale2, host)
        const painted2 = paint(r2.hl, stored)
        const probe2 = selectText(r2.textLayerEl, NEEDLE)
        const d2 = drift(painted2, probe2)
        log(d2.max < MAX_DRIFT_PX, `⭐ scale=2 用同一份归一化矩形重绘，仍对齐原文`, d2.detail)

        // ---------- 第 2 页（rotation 90）----------
        const r3 = await renderPage(pdf, 2, 1, host)
        log(r3.rotation === 90, '第 2 页 rotation=90')
        const probe3 = selectText(r3.textLayerEl, NEEDLE)
        if (!probe3) {
          log(false, '旋转页文本层里找不到目标文字')
        } else {
          const stored3 = rangeToNormalizedRects(probe3, r3.pageEl)
          log(stored3.length > 0, '旋转页可划词并归一化')
          log(
            stored3.every((r) => r.x + r.w <= 1.001 && r.y + r.h <= 1.001),
            '旋转页归一化矩形未越界',
          )
          const painted3 = paint(r3.hl, stored3)
          const d3 = drift(painted3, probe3)
          log(d3.max < MAX_DRIFT_PX, '⭐ 旋转页高亮与原文对齐', d3.detail)

          // 旋转页换成 scale=1.7 再验一次
          const r4 = await renderPage(pdf, 2, 1.7, host)
          const painted4 = paint(r4.hl, stored3)
          const probe4 = selectText(r4.textLayerEl, NEEDLE)
          const d4 = drift(painted4, probe4)
          log(d4.max < MAX_DRIFT_PX, '⭐ 旋转页 scale=1.7 仍对齐', d4.detail)
        }

        lines.push('')
        lines.push(failures === 0 ? '✅ 全部通过' : `❌ ${failures} 项未通过`)
        document.getElementById('result').innerHTML = lines
          .map((l) =>
            l.startsWith('✓') || l.startsWith('✅')
              ? `<span class="ok">${l}</span>`
              : `<span class="bad">${l}</span>`,
          )
          .join('\n')
        document.title = failures === 0 ? 'DONE PASS' : 'DONE FAIL'
      }

      run().catch((e) => {
        log(false, '自检异常', String(e && e.stack ? e.stack : e))
        document.title = 'DONE FAIL'
      })
