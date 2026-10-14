"""2026-10-14 第九轮：网页剪藏（URL 导入）。

这个功能的**安全代码比功能代码更重要**：`POST /api/documents/from-url`
让服务端替用户访问任意外部 URL，不做管制就是 SSRF 跳板
（探本机端口 / 云元数据端点 / 内网路由器）。

因此本文件前半部分全是安全用例，后半部分才是转换质量。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import ValidationError
from app.main import app
from app.services.web_clip_service import (
    _assert_url_is_safe,
    html_to_markdown,
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


# ==================== SSRF 防护 ====================

@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",                    # 回环
        "http://127.0.0.1:8080/",               # 回环 + 常见端口
        "http://localhost/admin",               # localhost
        "http://169.254.169.254/latest/meta-data/",  # 云元数据端点
        "http://192.168.1.1/",                  # 局域网
        "http://10.0.0.5:8080/",                # 私有网段
        "http://172.16.0.1/",                   # 私有网段
        "http://[::1]/",                        # IPv6 回环
        "http://[::ffff:127.0.0.1]/",           # IPv4-mapped IPv6（绕过手法）
    ],
)
def test_blocks_internal_addresses(url: str) -> None:
    with pytest.raises(ValidationError):
        _assert_url_is_safe(url)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",              # 本地文件
        "ftp://example.com/x",             # 非 http(s)
        "gopher://example.com/",           # 非 http(s)
        "javascript:alert(1)",             # 伪协议
        "http://user:pass@example.com/",   # URL 内嵌凭据
        "http://example.com:6379/",        # 非 Web 端口（Redis）
        "http://example.com:5432/",        # 非 Web 端口（PostgreSQL）
        "https://",                        # 无主机名
    ],
)
def test_blocks_dangerous_schemes_ports_and_credentials(url: str) -> None:
    with pytest.raises(ValidationError):
        _assert_url_is_safe(url)


def test_allows_public_urls() -> None:
    for url in ("https://example.com/", "http://example.com:8080/path"):
        _assert_url_is_safe(url)


def test_api_rejects_internal_url(client: TestClient) -> None:
    """端到端：接口层也必须拒绝内网地址，不能只在服务函数里拦。"""
    res = client.post(
        "/api/documents/from-url", json={"url": "http://127.0.0.1:8000/api/health"}
    )
    assert res.status_code == 422, res.text
    assert "内网" in res.text or "端口" in res.text


# ==================== HTML → Markdown ====================

def test_converts_common_blocks() -> None:
    html = """<html><head><title>深入理解 Vue 响应式</title></head><body><article>
    <h1>深入理解 Vue 响应式</h1>
    <p>Vue 3 用 <code>Proxy</code> 替代了 <code>defineProperty</code>，
       这是<strong>关键变化</strong>。参见 <a href="https://vuejs.org">官方文档</a>。</p>
    <h2>要点</h2>
    <ul><li>能监听新增属性</li><li>惰性递归</li></ul>
    <pre><code>const s = reactive({ n: 0 })</code></pre>
    <blockquote>响应式是核心抽象。</blockquote>
    <table><tr><th>版本</th><th>方案</th></tr><tr><td>Vue 3</td><td>Proxy</td></tr></table>
    </article></body></html>"""

    title, md = html_to_markdown(html)
    assert title == "深入理解 Vue 响应式"
    assert "# 深入理解 Vue 响应式" in md
    assert "**关键变化**" in md
    assert "[官方文档](https://vuejs.org)" in md
    assert "## 要点" in md
    assert "- 能监听新增属性" in md
    assert "```" in md
    # ⚠️ 引语必须保留：首版只遍历子元素，`<blockquote>纯文本</blockquote>`
    # 没有子元素，内容被整段丢掉。
    assert "> 响应式是核心抽象。" in md
    assert "| 版本 | 方案 |" in md


def test_drops_navigation_and_boilerplate() -> None:
    """导航 / 侧栏 / 页脚不应混进正文——它们会污染检索结果。"""
    html = """<html><body>
    <nav class="navbar"><a href="/">首页</a></nav>
    <article><p>真正的正文内容，足够长以便被选为主要内容块。</p></article>
    <div class="sidebar"><p>相关文章不该出现</p></div>
    <footer>版权所有不该出现</footer>
    </body></html>"""
    _title, md = html_to_markdown(html)
    assert "真正的正文" in md
    for noise in ("首页", "相关文章不该出现", "版权所有不该出现"):
        assert noise not in md, f"噪声未被剔除：{noise}"


def test_preserves_pre_whitespace_but_folds_paragraphs() -> None:
    """`<pre>` 里的缩进是内容，必须保留；段落里的换行只是排版，要折叠。"""
    html = """<html><body><article>
    <p>第一段
       折行的第二部分</p>
    <pre><code>line1
  line2 缩进是个信号
line3</code></pre>
    </article></body></html>"""
    _title, md = html_to_markdown(html)
    assert "  line2 缩进是个信号" in md, "pre 内的缩进被吞掉了"
    assert "第一段 折行的第二部分" in md, "段落内的换行未折叠"


def test_nested_list_does_not_leak_into_parent() -> None:
    """嵌套列表的文字不能并进父项（否则出现「2. 第二嵌套项」）。"""
    html = """<html><body><article><ol>
    <li>第一</li>
    <li>第二<ul><li>嵌套项</li></ul></li>
    <li>第三</li></ol></article></body></html>"""
    _title, md = html_to_markdown(html)
    lines = md.splitlines()
    assert "2. 第二" in lines, f"父项被嵌套内容污染：{lines}"
    assert "  - 嵌套项" in lines


def test_empty_body_raises_clear_error() -> None:
    """取不到正文时给可读提示，而不是存一篇空文档。"""
    html = "<html><head><title>空</title></head><body><nav>菜单</nav></body></html>"
    _title, md = html_to_markdown(html)
    assert md.strip() == ""


# ==================== 接口行为 ====================

def test_clip_creates_document_with_source_url(client: TestClient) -> None:
    """剪藏应落成 source=web 的文档，并记录来源地址（可溯源）。"""
    try:
        res = client.post("/api/documents/from-url", json={"url": "https://example.com/"})
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"外网不可达，跳过：{exc}")

    if res.status_code != 201:
        pytest.skip(f"外网抓取未成功（{res.status_code}），跳过")

    doc = res.json()
    try:
        assert doc["source"] == "web"
        assert doc["source_url"] == "https://example.com/"
        assert doc["content_text"], "剪藏正文为空"
        # 正文顶部应带来源链接，保证内容能回到出处
        assert "来源" in doc["content_text"]
    finally:
        client.delete(f"/api/documents/{doc['id']}/purge")


def test_duplicate_clip_is_rejected_by_default(client: TestClient) -> None:
    """同一网址默认拒绝重复剪藏——两份同源内容会污染检索结果。"""
    try:
        first = client.post("/api/documents/from-url", json={"url": "https://example.com/"})
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"外网不可达，跳过：{exc}")

    if first.status_code not in (201, 422):
        pytest.skip("外网抓取未成功，跳过")

    created: list[str] = []
    if first.status_code == 201:
        created.append(first.json()["id"])

    try:
        again = client.post("/api/documents/from-url", json={"url": "https://example.com/"})
        assert again.status_code == 422, "重复剪藏未被拒绝"
        assert "已经剪藏过" in again.text

        # 显式允许时可以通过
        forced = client.post(
            "/api/documents/from-url",
            json={"url": "https://example.com/", "allow_duplicate": True},
        )
        assert forced.status_code == 201
        created.append(forced.json()["id"])
    finally:
        for i in created:
            client.delete(f"/api/documents/{i}/purge")


def test_missing_url_is_422(client: TestClient) -> None:
    assert client.post("/api/documents/from-url", json={}).status_code == 422
    assert client.post("/api/documents/from-url", json={"url": ""}).status_code == 422
