"""联网搜索适配层：为【联网补充信息】提供外部资料。

约束（需求 14.4 / 14.5）：
- 仅当用户显式启用、且全局开关 `WEB_SEARCH_ENABLED` 打开时才发起联网请求；
- 只返回**真实抓取到**的结果，并保留真实 URL；
- 抓取失败或未配置时返回空结果并给出原因，绝不伪造结果。

三种后端：
- bing      ：免密钥，抓取 cn.bing.com（**默认**，国内可直连）
- duckduckgo：免密钥，抓取 html.duckduckgo.com（需要能访问外网）
- custom    ：用户自备搜索 API，返回 JSON（见 _search_custom 的兼容格式）
"""
from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

TIMEOUT = 15
MAX_RESULTS = 8
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) KnowledgeHub/0.1"

_TAG_RE = re.compile(r"<[^>]+>")
# 查询压缩用：英文/数字整词、中文连续片段。
# 口径与 rag/tokenize.py 一致，但词表在此自带一份——structure.md 规定
# ai/ 不能反向依赖 rag/，两者是平级模块。
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+.#-]{1,30}")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_STOP_EN = {
    "the", "and", "for", "with", "this", "that", "from", "are", "was", "were",
    "what", "why", "how", "when", "where", "which", "who", "can", "could",
    "should", "would", "does", "did", "is", "not", "but", "you", "your",
}
_ANCHOR_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.S,
)
_SNIPPET_RE = re.compile(r'class="result__snippet"[^>]*>(?P<snippet>.*?)</a>', re.S)

# Bing 结果块内的标题链接与摘要
_BING_TITLE_RE = re.compile(
    r'<h2[^>]*>\s*<a[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>', re.S
)
_BING_SNIPPET_RE = re.compile(r"<p[^>]*>(?P<snippet>.*?)</p>", re.S)


@dataclass
class WebResult:
    """一条联网结果（标题 / 真实链接 / 摘要）。"""

    title: str
    url: str
    snippet: str

    def as_dict(self) -> dict:
        return asdict(self)


# 中文疑问词 / 连接词：做搜索前需剥离，否则会污染查询
_ZH_NOISE_WORDS = (
    "什么是", "是什么", "为什么", "怎么样", "怎么", "如何", "哪些", "哪个",
    "请问", "能否", "是否", "介绍", "解释", "告诉我", "帮我", "一下",
    "什么", "以及", "还有", "或者",
)


def build_search_query(question: str, max_terms: int = 6) -> str:
    """把自然语言问句压缩成搜索引擎能理解的短查询。

    实测教训：直接把整句问句（「什么是vue3，和vue2有什么区别」）交给搜索引擎，
    会返回**完全无关**的结果（实测返回「中国铁路人才招聘网」）。因此：
    1) 优先保留英文 / 数字整词——Vue3、asyncio 这类最强的实体信号；
    2) 中文部分剥离疑问词与连接词，只留实词；
    3) 用空格拼接成短查询；若全部被剥离则回退原句，保证仍有东西可搜。
    """
    text = (question or "").strip()
    if not text:
        return ""

    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        key = term.lower()
        if key and key not in seen:
            seen.add(key)
            terms.append(term)

    # 1) 英文 / 数字整词
    for word in _WORD_RE.findall(text):
        if word.lower() not in _STOP_EN:
            add(word)

    # 2) 中文：逐段剥离疑问词与连接词
    for run in _CJK_RUN_RE.findall(text):
        cleaned = run
        for noise in _ZH_NOISE_WORDS:
            cleaned = cleaned.replace(noise, " ")
        for piece in cleaned.split():
            if len(piece) >= 2:
                add(piece)

    return " ".join(terms[:max_terms]).strip() or text


def _strip_tags(raw: str) -> str:
    """去掉 HTML 标签、反转义实体并折叠空白。"""
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub("", raw))).strip()


def _clean_ddg_url(raw: str) -> str:
    """还原 DuckDuckGo 跳转链接为真实 URL。"""
    if raw.startswith("//"):
        raw = "https:" + raw
    parsed = urlparse(raw)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        if "uddg" in qs and qs["uddg"]:
            return unquote(qs["uddg"][0])
    return raw


def _parse_duckduckgo_html(text: str, limit: int) -> list[WebResult]:
    """从 DuckDuckGo HTML 页面解析结果列表。"""
    anchors = list(_ANCHOR_RE.finditer(text))
    results: list[WebResult] = []
    for i, m in enumerate(anchors):
        if len(results) >= limit:
            break
        url = _clean_ddg_url(html.unescape(m.group("url")))
        title = _strip_tags(m.group("title"))
        if not url or not title:
            continue
        # 摘要取「本结果锚点之后、下一个结果锚点之前」的第一段
        start = m.end()
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(text)
        sm = _SNIPPET_RE.search(text[start:end])
        snippet = _strip_tags(sm.group("snippet")) if sm else ""
        results.append(WebResult(title=title, url=url, snippet=snippet))
    return results


async def _search_duckduckgo(query: str, limit: int) -> list[WebResult]:
    """免密钥搜索：抓取 DuckDuckGo HTML 版（需要能访问外网）。"""
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        resp = await client.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        return _parse_duckduckgo_html(resp.text, limit)


def _clean_bing_url(raw: str) -> str:
    """Bing 部分结果使用 `bing.com/ck/a?...&u=a1<base64>` 跳转链接，还原真实 URL。"""
    if "bing.com/ck/a" not in raw:
        return raw
    u = (parse_qs(urlparse(raw).query).get("u") or [""])[0]
    if not u.startswith("a1"):
        return raw
    payload = u[2:]
    payload += "=" * (-len(payload) % 4)
    try:
        from base64 import urlsafe_b64decode

        decoded = urlsafe_b64decode(payload).decode("utf-8", "ignore")
        return decoded if decoded.startswith("http") else raw
    except Exception:  # noqa: BLE001
        return raw


def _parse_bing_html(text: str, limit: int) -> list[WebResult]:
    """从 Bing 结果页解析（每个结果包在 `<li class="b_algo">` 内）。"""
    blocks = re.split(r'<li class="b_algo"', text)[1:]
    results: list[WebResult] = []
    for block in blocks:
        if len(results) >= limit:
            break
        tm = _BING_TITLE_RE.search(block)
        if not tm:
            continue
        url = _clean_bing_url(html.unescape(tm.group("url")).strip())
        title = _strip_tags(tm.group("title"))
        if not url.startswith("http") or not title:
            continue
        sm = _BING_SNIPPET_RE.search(block)
        snippet = _strip_tags(sm.group("snippet")) if sm else ""
        results.append(WebResult(title=title, url=url, snippet=snippet))
    return results


async def _search_bing(query: str, limit: int) -> list[WebResult]:
    """免密钥搜索：抓取 Bing 结果页（默认走 cn.bing.com，国内可直连）。"""
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(
            "https://cn.bing.com/search",
            params={"q": query},
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        resp.raise_for_status()
        return _parse_bing_html(resp.text, limit)


def _normalize_items(payload: object, limit: int) -> list[WebResult]:
    """把自定义搜索 API 的多种返回形态归一化为结果列表。

    兼容：{"results": [...]} / {"items": [...]} / {"data": [...]} / 顶层数组。
    每项取 title/name、url/link、snippet/description/content 字段。
    """
    items: list = []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        for key in ("results", "items", "data", "organic"):
            value = payload.get(key)
            if isinstance(value, list):
                items = value
                break

    results: list[WebResult] = []
    for item in items:
        if not isinstance(item, dict) or len(results) >= limit:
            continue
        url = str(item.get("url") or item.get("link") or "").strip()
        title = str(item.get("title") or item.get("name") or url).strip()
        snippet = str(
            item.get("snippet") or item.get("description") or item.get("content") or ""
        ).strip()
        if url:
            results.append(WebResult(title=title, url=url, snippet=snippet))
    return results


async def _search_custom(query: str, limit: int) -> list[WebResult]:
    """用户自备搜索 API：GET 带 q 参数，可选 Bearer 鉴权。"""
    base = (settings.web_search_api_url or "").strip()
    if not base:
        raise ValueError("未配置 WEB_SEARCH_API_URL")
    headers = {"User-Agent": USER_AGENT}
    if settings.web_search_api_key:
        headers["Authorization"] = f"Bearer {settings.web_search_api_key}"
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(base, params={"q": query}, headers=headers)
        resp.raise_for_status()
        return _normalize_items(resp.json(), limit)


async def search_web(query: str, top_k: int | None = None) -> tuple[list[WebResult], str]:
    """执行联网搜索。

    返回 (结果列表, 说明)。说明用于前端提示与提示词上下文；
    未启用、未配置或抓取失败时结果为空，且说明中给出真实原因——
    上层据此**不标注**联网来源，而不是伪称已联网。
    """
    if not settings.web_search_enabled:
        return [], "联网搜索未启用"

    limit = min(top_k or settings.web_search_top_k, MAX_RESULTS)
    provider = (settings.web_search_provider or "bing").lower()

    # 整句问句直接检索会返回无关结果（见 build_search_query 注释），先压缩成关键词
    keywords = build_search_query(query)
    if keywords != query:
        logger.info("联网检索：问句「%s」→ 关键词「%s」", query[:40], keywords[:60])

    try:
        if provider == "custom":
            results = await _search_custom(keywords, limit)
        elif provider == "duckduckgo":
            results = await _search_duckduckgo(keywords, limit)
        else:  # bing（默认，国内可直连）
            results = await _search_bing(keywords, limit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("联网搜索失败（本次不使用联网信息）：%s", exc)
        return [], f"联网搜索失败：{exc}"

    if not results:
        return [], "联网搜索未返回可用结果"
    return results[:limit], f"已获取 {len(results)} 条联网结果"
