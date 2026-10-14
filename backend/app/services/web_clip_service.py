"""网页剪藏：把 URL 抓成 Markdown 存进知识库。

这是「输入漏斗」的最后一个缺口——此前只能上传文件或手写，
看到好文章除了复制粘贴没有别的办法（格式乱、元数据丢、且脱离知识库）。

## 为什么这个模块的安全代码比功能代码还多

`POST /api/documents/from-url` 让**服务端替用户去访问一个外部 URL**。
如果不管制目标地址，它就成了一个 SSRF 跳板：

- `http://127.0.0.1:5432` → 探本机 PostgreSQL
- `http://169.254.169.254/latest/meta-data/` → 云厂商元数据端点（可拿到临时凭据）
- `http://192.168.1.1/` → 路由器管理页

局域网内网地址、回环地址、链路本地地址都必须拒绝。而且**每一跳重定向都要重新校验**——
`https://evil.com → 302 → http://127.0.0.1:5432` 是标准绕过手法，
只校验初始 URL 等于没校验。

因此 `fetch()` 里手动跟随重定向（httpx 的 `follow_redirects=True` 会跳过中间校验）。

## 已知限制（有意为之）

- **图片不落地**：正文里的图片保留为远程链接，不下载到本地附件。
  下载需要处理相对路径、防盗链、体积限制、失败降级，复杂度高；
  且多数文章配图不影响检索与复习。代价是原站删图后链接失效。
- **正文提取是启发式的**：没有引入 readability / trafilatura（当前环境没装），
  用「去噪 + 找最大文本块」的规则实现。对结构规范的站点效果好，
  对强交互式页面（SPA）只能拿到服务端渲染的那部分。
"""
from __future__ import annotations

import copy
import ipaddress
import re
import socket
import uuid
from urllib.parse import urljoin, urlparse

import httpx
from lxml import etree, html as lxml_html

from app.core.exceptions import ValidationError
from app.core.logging import get_logger

logger = get_logger(__name__)

# ---------------- 抓取限制 ----------------
# 超时按「连接 / 读取」分开设：连接慢说明站点不可达，读取慢说明内容太大
TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
MAX_BYTES = 5 * 1024 * 1024  # 5MB：正常文章页远小于此，超过的多半是二进制或异常
MAX_REDIRECTS = 5
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 KnowledgeHub/1.0"
)

# 只允许这两种协议。刻意不放行 file:// / ftp:// / gopher:// 等
ALLOWED_SCHEMES = {"http", "https"}

# 这些标签是「页面装饰」而不是正文，整棵子树丢掉
DROP_TAGS = {
    "script", "style", "noscript", "iframe", "svg", "canvas", "form",
    "nav", "header", "footer", "aside", "button", "select", "option",
    "input", "textarea", "template", "object", "embed",
}
# 这些 class/id 关键词命中的容器通常是导航/评论/侧栏，丢弃
BOILERPLATE_HINTS = re.compile(
    r"(^|[-_])(nav|navbar|menu|sidebar|side-bar|footer|header|comment|comments"
    r"|related|recommend|share|social|advert|ads?|banner|breadcrumb|pagination"
    r"|cookie|subscribe|newsletter|popup|modal|toolbar|tags?-list)([-_]|$)",
    re.I,
)


# ---------------- SSRF 防护 ----------------
def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """该地址是否可安全访问（公网单播）。"""
    return not (
        ip.is_private          # 10/8、172.16/12、192.168/16、fc00::/7 …
        or ip.is_loopback      # 127/8、::1
        or ip.is_link_local    # 169.254/16（含云元数据 169.254.169.254）、fe80::/10
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        # IPv4-mapped IPv6（::ffff:127.0.0.1）会绕过上面部分判断，单独拦
        or (isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None
            and not _is_public_ip(ip.ipv4_mapped))
    )


def _assert_url_is_safe(url: str) -> None:
    """校验协议与目标地址，不通过则抛 ValidationError。

    **每次请求和每次重定向都要调用**——只校验首个 URL 会被重定向绕过。
    """
    parsed = urlparse(url)

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise ValidationError(
            f"只支持 http / https 链接（收到 {parsed.scheme or '空'}）"
        )
    if not parsed.hostname:
        raise ValidationError("链接缺少有效的域名")
    if parsed.username or parsed.password:
        raise ValidationError("链接中不应包含用户名或密码")

    host = parsed.hostname
    # 端口只放行常见 Web 端口，避免用高位端口探测内网服务
    if parsed.port not in (None, 80, 443, 8080, 8443):
        raise ValidationError(f"不支持的端口：{parsed.port}")

    # 域名解析出的**每一个**地址都要是公网地址。
    # 只看第一个会被 DNS 轮询 / 多 A 记录绕过。
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ValidationError(f"无法解析域名：{host}") from exc

    if not infos:
        raise ValidationError(f"域名没有解析到任何地址：{host}")

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            raise ValidationError(f"无法识别的地址：{addr}") from None
        if not _is_public_ip(ip):
            raise ValidationError(
                "拒绝访问内网 / 本机地址。该功能只用于抓取公开网页，"
                "不允许指向局域网或本机服务（防止被当作访问内网的跳板）。"
            )


def fetch(url: str) -> tuple[str, str]:
    """抓取网页，返回 (最终 URL, HTML 文本)。

    手动跟随重定向，**每一跳都重新做安全检查**——
    `httpx(follow_redirects=True)` 会在内部跳转，跳过校验。
    """
    current = url.strip()
    if not current:
        raise ValidationError("链接不能为空")
    if not current.lower().startswith(("http://", "https://")):
        # 容忍用户只粘贴 `example.com/xxx`
        current = "https://" + current.lstrip("/")

    with httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            _assert_url_is_safe(current)

            try:
                resp = client.get(current, follow_redirects=False)
            except httpx.TimeoutException as exc:
                raise ValidationError("抓取超时，目标站点无响应") from exc
            except httpx.HTTPError as exc:
                raise ValidationError(f"抓取失败：{exc.__class__.__name__}") from exc

            if resp.is_redirect:
                location = resp.headers.get("location")
                if not location:
                    raise ValidationError("站点返回了无目标的重定向")
                current = urljoin(current, location)
                continue

            if resp.status_code >= 400:
                raise ValidationError(f"目标站点返回 {resp.status_code}")

            # 体积上限：读原始字节再解码，避免超长响应打爆内存
            raw = resp.content
            if len(raw) > MAX_BYTES:
                raise ValidationError(
                    f"页面过大（超过 {MAX_BYTES // 1024 // 1024}MB），已放弃抓取"
                )

            ctype = (resp.headers.get("content-type") or "").lower()
            if ctype and not any(t in ctype for t in ("text/html", "text/plain", "xml")):
                raise ValidationError(f"该链接不是网页（Content-Type: {ctype}）")

            # 编码：优先站点声明，其次 httpx 的推断，最后兜底 utf-8
            encoding = resp.encoding or resp.charset_encoding or "utf-8"
            try:
                text = raw.decode(encoding, errors="replace")
            except (LookupError, UnicodeDecodeError):
                text = raw.decode("utf-8", errors="replace")
            return current, text

    raise ValidationError(f"重定向次数过多（超过 {MAX_REDIRECTS} 次）")


# ---------------- HTML → Markdown ----------------
def _clean_tree(root: etree._Element) -> None:
    """原地删除装饰性标签与明显的非正文容器。"""
    for tag in DROP_TAGS:
        for el in root.iter(tag):
            el.drop_tree()

    for el in list(root.iter("div", "section", "ul", "ol")):
        if not isinstance(el.tag, str):
            continue
        ident = f"{el.get('id') or ''} {el.get('class') or ''}"
        if ident.strip() and BOILERPLATE_HINTS.search(ident.replace(" ", "-")):
            el.drop_tree()


def _text_len(el: etree._Element) -> int:
    return len(" ".join(el.itertext()).strip())


def _pick_main(root: etree._Element) -> etree._Element:
    """挑出正文容器。

    没有引入 readability（环境未装），用启发式：
    优先语义标签 `<article>` / `<main>`，否则在所有 div/section 里选
    「文本量最大且不是整页」的那个。整页 div 通常是 wrapper，选了等于没选。
    """
    for tag in ("article", "main"):
        candidates = list(root.iter(tag))
        if candidates:
            best = max(candidates, key=_text_len)
            if _text_len(best) > 200:
                return best

    body = root.find(".//body")
    base = body if body is not None else root
    total = _text_len(base)

    best, best_len = base, 0
    for el in base.iter("div", "section"):
        n = _text_len(el)
        # 排除「几乎就是整页」的 wrapper：选它等于没做提取
        if n > best_len and n <= total * 0.95:
            best, best_len = el, n
    return best if best_len > 200 else base


def _inline_md(el: etree._Element) -> str:
    """把行内子节点拼成 Markdown 片段。"""
    out: list[str] = []
    if el.text:
        out.append(el.text)

    for child in el:
        if not isinstance(child.tag, str):
            if child.tail:
                out.append(child.tail)
            continue

        tag = child.tag.lower()
        inner = _inline_md(child).strip()

        if tag in ("strong", "b"):
            out.append(f"**{inner}**" if inner else "")
        elif tag in ("em", "i"):
            out.append(f"*{inner}*" if inner else "")
        elif tag == "code":
            out.append(f"`{inner}`" if inner else "")
        elif tag == "a":
            href = child.get("href") or ""
            if inner and href and not href.startswith("javascript:"):
                out.append(f"[{inner}]({href})")
            else:
                out.append(inner)
        elif tag == "img":
            src = child.get("src") or ""
            if src:
                out.append(f"![{child.get('alt') or ''}]({src})")
        elif tag == "br":
            out.append("\n")
        else:
            out.append(inner)

        if child.tail:
            out.append(child.tail)

    return "".join(out)


def _list_md(el: etree._Element, depth: int = 0) -> str:
    """有序/无序列表 → Markdown（两级缩进）。"""
    ordered = el.tag.lower() == "ol"
    lines: list[str] = []
    for i, li in enumerate(el.findall("li"), start=1):
        # 取本项文字时要**排除嵌套列表**：否则 `_inline_md` 会把子列表的文字
        # 也拼进来，出现「2. 第二嵌套项」这种父项被污染的结果。
        # 用深拷贝剥离嵌套列表再取文本，比手工遍历各种子节点组合更稳。
        own = copy.deepcopy(li)
        for sub in own.findall("ul") + own.findall("ol"):
            sub.getparent().remove(sub)

        text = _flow_text(own).strip()
        bullet = f"{i}." if ordered else "-"
        lines.append(f"{'  ' * depth}{bullet} {text}")

        # 嵌套列表递归（用原节点，不受上面拷贝的影响）
        for sub in li.findall("ul") + li.findall("ol"):
            lines.append(_list_md(sub, depth + 1))
    return "\n".join(x for x in lines if x.strip())


def _flow_text(el: etree._Element) -> str:
    """行内文本 + 折叠空白。

    用于段落 / 标题 / 列表项这类「按流排布」的元素：HTML 源码里的换行与缩进
    （如 `<p>第一行\\n     第二行</p>`）在 Markdown 里会造成难看的悬挂缩进，
    折叠成单个空格即可。
    **不要**对 `<pre>` 用——那里空白是内容本身。
    """
    return " ".join(_inline_md(el).split())


def _block_md(el: etree._Element) -> list[str]:
    """块级元素 → Markdown 行。"""
    tag = el.tag.lower() if isinstance(el.tag, str) else ""

    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        text = _flow_text(el)
        return [f"{'#' * int(tag[1])} {text}"] if text else []
    if tag == "p":
        text = _flow_text(el)
        return [text] if text else []
    if tag in ("ul", "ol"):
        return [_list_md(el)]
    if tag == "blockquote":
        # ⚠️ 不能只遍历子元素：`<blockquote>纯文本</blockquote>` 没有子元素，
        # 只遍历 child 会把内容整段丢掉（引语是高频块，不能丢）。
        inner: list[str] = []
        for child in el:
            if isinstance(child.tag, str):
                inner.extend(_block_md(child))
        if not inner:
            text = _flow_text(el)
            if text:
                inner = [text]
        return [f"> {ln}" for ln in inner]
    if tag == "pre":
        code = "".join(el.itertext()).rstrip("\n")
        return [f"```\n{code}\n```"] if code else []
    if tag == "hr":
        return ["---"]
    if tag == "table":
        return [_table_md(el)]
    if tag in ("div", "section", "article", "main", "body", "span"):
        out: list[str] = []
        for child in el:
            if isinstance(child.tag, str):
                out.extend(_block_md(child))
        if not out:
            text = _flow_text(el)
            if text:
                out.append(text)
        return out
    if tag == "br":
        return []
    # 其它标签：取纯文本
    text = _flow_text(el)
    return [text] if text else []


def _table_md(el: etree._Element) -> str:
    """表格 → Markdown 表格（第一行作表头，这是最常见的约定）。"""
    rows: list[list[str]] = []
    for tr in el.iter("tr"):
        cells = [
            " ".join(_inline_md(td).split()) for td in tr if isinstance(td.tag, str)
            and td.tag.lower() in ("td", "th")
        ]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    head, *body = rows
    lines = [
        "| " + " | ".join(head) + " |",
        "| " + " | ".join("---" for _ in range(width)) + " |",
    ]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


def html_to_markdown(html_text: str) -> tuple[str, str]:
    """HTML → (标题, Markdown 正文)。"""
    try:
        root = lxml_html.fromstring(html_text)
    except (etree.ParserError, ValueError) as exc:
        raise ValidationError("页面内容无法解析为 HTML") from exc

    # 标题要在清理前取：<title> 常在被丢掉的 <head> 里
    title = ""
    node = root.find(".//title")
    if node is not None and node.text:
        title = " ".join(node.text.split())
    if not title:
        h1 = root.find(".//h1")
        if h1 is not None:
            title = " ".join("".join(h1.itertext()).split())

    _clean_tree(root)
    main = _pick_main(root)

    blocks: list[str] = []
    for child in main:
        if isinstance(child.tag, str):
            blocks.extend(_block_md(child))

    body = "\n\n".join(b.strip() for b in blocks if b.strip())
    # 折叠 3 个以上连续空行
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return title, body


# ---------------- 剪藏入口 ----------------
def clip(url: str) -> dict:
    """抓取网页并转成 Markdown，返回待入库的字段。

    只做「抓取 + 转换」，不碰数据库——保持这个函数可单测、无副作用。
    """
    final_url, html_text = fetch(url)
    title, body = html_to_markdown(html_text)

    if not body.strip():
        raise ValidationError(
            "没能从该页面提取出正文。可能是纯前端渲染（SPA）页面，"
            "或内容需要登录后才能看到。"
        )

    host = urlparse(final_url).hostname or ""
    title = title or host or "未命名网页"
    # 标题限长，与 NoteCreate 的口径一致
    title = title[:200]

    # 正文开头记下出处：剪藏内容必须能回到原地址，
    # 否则成了无源之水——这在知识管理里是硬伤。
    header = f"> 来源：[{final_url}]({final_url})\n\n"
    return {
        "url": final_url,
        "title": title,
        "content": header + body,
    }


def find_existing(db, url: str):
    """按原始地址找已剪藏过的文档（未删除）。用于重复剪藏提示。"""
    from sqlalchemy import select

    from app.models import Document

    return (
        db.execute(
            select(Document)
            .where(Document.source_url == url, Document.deleted_at.is_(None))
            .limit(1)
        )
        .scalars()
        .first()
    )


async def clip_to_document(db, url: str, *, allow_duplicate: bool = False):
    """抓取并保存为文档，返回 (文档, 剪藏信息)。

    `allow_duplicate=False`（默认）时，同一个网址已存在则**拒绝并告知**，
    而不是默默堆一份副本——知识库里出现两份同源内容会污染检索结果，
    而且用户往往不知道自己在重复。
    """
    from app.services import document_service

    info = clip(url)

    existing = find_existing(db, info["url"])
    if existing is not None and not allow_duplicate:
        raise ValidationError(
            f"这个网址已经剪藏过了（《{existing.title}》）。"
            "如需再存一份，请勾选「允许重复」。"
        )

    doc = await document_service.create_note(
        db,
        title=info["title"],
        content_text=info["content"],
        source="web",
        source_url=info["url"],
    )
    return doc, info
