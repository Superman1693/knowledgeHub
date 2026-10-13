"""拼音检索支持：让「记不起来汉字、只打得出来拼音」的查询也能命中。

**为什么需要它**：中文用户经常遇到「知道怎么读、想不起怎么写」的情况，
或者输入法切成英文时不自觉打了拼音（`xiangying` / `xjbsj`）。
现有检索只对 `chunks.content` 做子串匹配，纯拼音查询必然 0 命中。

**实现方式**：给片段额外存两份拼音——
- `pinyin`：全拼，不加分隔符（「响应式布局」→ `xiangyingshibuju`）
- `pinyin_initials`：首字母（→ `xjsbj`）

查询端把「看起来是拼音」的词项挑出来，改去匹配这两列。
存的是无分隔符全拼，所以查询 `xiangying` 能作为子串命中。

**怎么防止英文被误判成拼音**（关键）：`go`、`vue`、`docker` 这些英文词
如果也拿去匹配拼音列，`go` 会命中 `gong` 的全拼，造成一堆假阳性。
所以词项必须先通过校验：
1. **全拼**：整串能切分成合法的拼音音节（`xiangying` → `xiang`+`ying`）；
2. **首字母**：每个字符都是合法的声母（`bpmfdtnlgkhjqxrzcsyw`）。

`pypinyin` 未安装时本模块整体降级：`pinyin_of` 返回空串、
`is_pinyin_*` 恒为 False，检索退回原有行为（不影响任何现有功能）。
"""
from __future__ import annotations

import re
import unicodedata

# 尝试导入 pypinyin（可选依赖，pip install pypinyin）
try:
    from pypinyin import Style, lazy_pinyin, pinyin_dict

    _HAS_PYPINYIN = True
except ImportError:  # pragma: no cover - 取决于安装环境
    _HAS_PYPINYIN = False

# 纯 ASCII 字母串（查询端用来识别「可能是拼音」的词项）
_ASCII_ALPHA_RE = re.compile(r"^[a-z]+$")

# 中文连续片段
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")

# 合法声母（单字母）。注意不含 a/e/o/i/u/v —— 所以 "go" 的 'o' 不是声母，
# 整个串会被判为「不是首字母串」，不会拿去匹配拼音列。
PINYIN_INITIALS = set("bpmfdtnlgkhjqxrzcsyw")

# 词项长度下限：太短的拼音串噪声远大于收益
_MIN_PINYIN_LEN = 2
_MIN_INITIALS_LEN = 2


def _strip_tone(syllable: str) -> str:
    """去掉拼音里的声调符号（`xiǎng` → `xiang`）。"""
    nfd = unicodedata.normalize("NFD", syllable)
    return "".join(c for c in nfd if not unicodedata.combining(c))


_syllables: frozenset[str] | None = None


def _valid_syllables() -> frozenset[str]:
    """合法拼音音节表（无声调），从 pypinyin 自带的字典派生。

    延迟构建 + 缓存：字典有 4 万多条，导入时就算一遍太浪费。
    """
    global _syllables
    if _syllables is None:
        if not _HAS_PYPINYIN:
            _syllables = frozenset()
        else:
            found: set[str] = set()
            for value in pinyin_dict.pinyin_dict.values():
                for raw in str(value).split(","):
                    syl = _strip_tone(raw.strip())
                    if syl and syl.isascii() and syl.isalpha():
                        found.add(syl)
            _syllables = frozenset(found)
    return _syllables


def _splits_into_syllables(text: str) -> bool:
    """整串是否能切成若干合法音节（动态规划，短串成本可忽略）。

    用 DP 而不是贪心：贪心在 `xi`+`an` vs `xian` 这类地方可能走错分支，
    虽然本例中两者都合法，但没必要赌。
    """
    syllables = _valid_syllables()
    if not syllables:
        return False
    n = len(text)
    ok = [False] * (n + 1)
    ok[0] = True
    for i in range(1, n + 1):
        # 最长音节 6 个字母（zhuang/chuang），从长到短试
        for j in range(max(0, i - 6), i):
            if ok[j] and text[j:i] in syllables:
                ok[i] = True
                break
    return ok[n]


def is_pinyin_full(term: str) -> bool:
    """是否是「全拼」串，如 `xiangying`。

    要求整串能切成合法音节，因此 `go` / `vue` / `docker` 都会被拒绝。
    """
    if not _HAS_PYPINYIN:
        return False
    t = (term or "").strip().lower()
    if len(t) < _MIN_PINYIN_LEN or not _ASCII_ALPHA_RE.match(t):
        return False
    return _splits_into_syllables(t)


def is_pinyin_initials(term: str) -> bool:
    """是否是「首字母」串，如 `xjbsj`。

    每个字符都必须是合法声母，所以 `go`（含 `o`）会被拒绝。
    """
    t = (term or "").strip().lower()
    if len(t) < _MIN_INITIALS_LEN or not _ASCII_ALPHA_RE.match(t):
        return False
    return all(ch in PINYIN_INITIALS for ch in t)


def pinyin_of(text: str) -> tuple[str, str]:
    """返回 (全拼, 首字母)，都只含小写字母、不加分隔符。

    **只取中文部分的拼音**，非中文字符（英文、数字、标点、空格）全部丢掉。
    两个理由：
    1. 标点会切断拼音的连续性 —— 「响。应」若保留句点会变成 `xiang。ying`，
       查询 `xiangying` 就命中不了；
    2. 纯英文文本不该进拼音列 —— 否则英文 `shining` 会被当成拼音 `shi`+`ning`，
       用户搜 `shi` 时凭空多出一堆假阳性。

    代价：混合文本（「Vue3 响应式」）的拼音列只有 `xiangyingshi`，
    跨中英文的连续拼音查不到。但英文部分本来就由 content 列覆盖，
    这个代价换来的是更干净的拼音列。
    """
    if not _HAS_PYPINYIN or not text:
        return "", ""
    cjk = "".join(_CJK_RUN_RE.findall(text))
    if not cjk:
        return "", ""
    full = "".join(lazy_pinyin(cjk, style=Style.NORMAL, errors="default"))
    initials = "".join(
        p[0] for p in lazy_pinyin(cjk, style=Style.FIRST_LETTER, errors="default")
    )
    # 兜底：词典里没有的罕见字会被原样返回，过滤掉非 ASCII 字母
    keep = lambda s: "".join(ch for ch in s.lower() if ch.isascii() and ch.isalpha())  # noqa: E731
    return keep(full), keep(initials)


def pinyin_available() -> bool:
    """拼音检索是否可用（用于健康检查 / 设置页展示）。"""
    return _HAS_PYPINYIN
