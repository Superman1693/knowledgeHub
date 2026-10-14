/**
 * 最小 ZIP 打包器（仅存储、不压缩）。
 *
 * ## 为什么自己写
 *
 * 静态站导出需要把几十上百个 HTML 文件打成一个 zip。项目里没有 jszip / fflate，
 * 而为一个导出功能引入压缩库并不划算——尤其是**压缩并非必需**：
 * HTML/CSS 文本打包体积下不下来，主要靠 HTTP 侧的 gzip，本地 zip 只求能装能解开。
 *
 * ## 为什么只做「存储」不做 deflate
 *
 * 换成 deflate 要接 pako 之类的库或走 `CompressionStream`（浏览器支持参差），
 * 收益有限、复杂度翻倍。**存储模式（compression=0）是完全合法的 ZIP**，
 * 任何解压工具都能打开。
 *
 * ## 正确性
 *
 * ZIP 的坑集中在三处，都已在实现里避开：
 * 1. **中文文件名**：必须置 UTF-8 标志位（0x0800），否则 Windows 资源管理器
 *    会按本地代码页解码成乱码；
 * 2. **CRC32**：每个文件都要真实计算，填 0 会让严格的解压工具报「数据损坏」；
 * 3. **中央目录的偏移量**：必须是该文件本地头的**起始**偏移，差一个字节就废。
 *
 * 输出经过 `zipfile`（Python 标准库）实测可正常解析，见 `utils/__tests__/zip.test.ts`。
 */

/** CRC32 查表（多项式 0xEDB88320，ZIP 规范使用的那张）。 */
const CRC_TABLE = (() => {
  const table = new Uint32Array(256)
  for (let i = 0; i < 256; i++) {
    let c = i
    for (let k = 0; k < 8; k++) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    }
    table[i] = c >>> 0
  }
  return table
})()

function crc32(bytes: Uint8Array): number {
  let c = 0xffffffff
  for (let i = 0; i < bytes.length; i++) {
    c = CRC_TABLE[(c ^ bytes[i]) & 0xff]! ^ (c >>> 8)
  }
  return (c ^ 0xffffffff) >>> 0
}

/** 把 Date 转成 DOS 日期/时间（ZIP 头用的老格式，1980 年起算）。 */
function dosDateTime(d: Date): { time: number; date: number } {
  const year = Math.max(1980, d.getFullYear())
  return {
    time: (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1),
    date: ((year - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate(),
  }
}

export interface ZipEntry {
  /** zip 内的路径，用 `/` 分隔（如 `notes/vue.html`） */
  path: string
  content: string
}

/** 小端写入辅助：保持各处字节序一致，避免手写偏移时出错。 */
class ByteWriter {
  private chunks: Uint8Array[] = []
  private size = 0

  get length(): number {
    return this.size
  }

  push(bytes: Uint8Array): void {
    this.chunks.push(bytes)
    this.size += bytes.length
  }

  u16(v: number): void {
    const b = new Uint8Array(2)
    new DataView(b.buffer).setUint16(0, v & 0xffff, true)
    this.push(b)
  }

  u32(v: number): void {
    const b = new Uint8Array(4)
    new DataView(b.buffer).setUint32(0, v >>> 0, true)
    this.push(b)
  }

  concat(): Uint8Array {
    const out = new Uint8Array(this.size)
    let at = 0
    for (const c of this.chunks) {
      out.set(c, at)
      at += c.length
    }
    return out
  }
}

export function createZip(entries: ZipEntry[], now = new Date()): Uint8Array {
  const encoder = new TextEncoder()
  const { time, date } = dosDateTime(now)

  const body = new ByteWriter()
  const central = new ByteWriter()
  // 每个文件在中央目录里的记录：本地头偏移量必须在这里记下来
  const offsets: { nameBytes: Uint8Array; crc: number; size: number; offset: number }[] = []

  for (const entry of entries) {
    const nameBytes = encoder.encode(entry.path)
    const dataBytes = encoder.encode(entry.content)
    const crc = crc32(dataBytes)
    const offset = body.length

    // ---- 本地文件头（30 字节 + 文件名）----
    body.u32(0x04034b50) // 签名
    body.u16(20) // 解压所需版本 2.0
    body.u16(0x0800) // 标志位：文件名为 UTF-8
    body.u16(0) // 压缩方式 0 = 存储
    body.u16(time)
    body.u16(date)
    body.u32(crc)
    body.u32(dataBytes.length) // 压缩后大小 = 原大小（存储模式）
    body.u32(dataBytes.length) // 原始大小
    body.u16(nameBytes.length)
    body.u16(0) // 扩展字段长度
    body.push(nameBytes)
    body.push(dataBytes)

    offsets.push({ nameBytes, crc, size: dataBytes.length, offset })
  }

  // ---- 中央目录 ----
  for (const o of offsets) {
    central.u32(0x02014b50) // 签名
    central.u16(20) // 创建版本
    central.u16(20) // 解压所需版本
    central.u16(0x0800)
    central.u16(0)
    central.u16(time)
    central.u16(date)
    central.u32(o.crc)
    central.u32(o.size)
    central.u32(o.size)
    central.u16(o.nameBytes.length)
    central.u16(0) // 扩展字段
    central.u16(0) // 注释
    central.u16(0) // 起始磁盘号
    central.u16(0) // 内部属性
    central.u32(0) // 外部属性
    central.u32(o.offset) // 本地头偏移
    central.push(o.nameBytes)
  }

  // ---- 中央目录结束记录（22 字节）----
  const eocd = new ByteWriter()
  eocd.u32(0x06054b50)
  eocd.u16(0) // 当前磁盘号
  eocd.u16(0) // 中央目录所在磁盘号
  eocd.u16(entries.length)
  eocd.u16(entries.length)
  eocd.u32(central.length)
  eocd.u32(body.length) // 中央目录的起始偏移 = 正文总长度
  eocd.u16(0) // 注释长度

  const bodyBytes = body.concat()
  const centralBytes = central.concat()
  const eocdBytes = eocd.concat()

  const out = new Uint8Array(bodyBytes.length + centralBytes.length + eocdBytes.length)
  out.set(bodyBytes, 0)
  out.set(centralBytes, bodyBytes.length)
  out.set(eocdBytes, bodyBytes.length + centralBytes.length)
  return out
}
