"""OCR 可选模块：识别扫描型 PDF / 图片中的文字。

LocalMind 限制项「PDF 扫描件：无文本层的扫描件无法解析，需先 OCR」。

**引擎选择**（按可用性自动降级，都无需 Tesseract 系统依赖）：
1. **RapidOCR**（推荐）：`pip install rapidocr_onnxruntime`
   基于 ONNX Runtime，内置中文模型，纯 pip 安装、不需要 GPU、不需要系统引擎。
2. **pytesseract**（兜底）：需要系统安装 Tesseract 引擎，仅在 RapidOCR 不可用时尝试。
3. **均不可用**：扫描页保持原有行为（跳过并给出明确提示），不影响普通 PDF 解析。

**渲染**：用 PyMuPDF（`pymupdf`）把 PDF 页面渲染为图片，再交给 OCR 引擎。
PyMuPDF 也是纯 pip 安装，无需 poppler 等系统依赖。
"""
from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger(__name__)

# ---- 可选依赖探测 ----
try:
    from rapidocr_onnxruntime import RapidOCR

    _RAPIDOCR = True
except ImportError:
    _RAPIDOCR = False

try:
    import pymupdf

    _PYMUPDF = True
except ImportError:
    _PYMUPDF = False

try:
    import pytesseract  # noqa: F401

    _TESSERACT = True
except ImportError:
    _TESSERACT = False

# OCR 引擎实例（懒加载，避免每次调用都初始化模型）
_engine = None
_engine_loaded = False


def ocr_status() -> dict:
    """返回 OCR 能力状态（用于健康检查 / 设置页展示）。"""
    if _RAPIDOCR:
        engine = "rapidocr（ONNX Runtime，内置中文）"
    elif _TESSERACT:
        engine = "tesseract（需系统引擎）"
    else:
        engine = None
    return {
        "available": _RAPIDOCR or _TESSERACT,
        "engine": engine,
        "rapidocr_installed": _RAPIDOCR,
        "tesseract_installed": _TESSERACT,
        "renderer_installed": _PYMUPDF,
        "hint": (
            ""
            if (_RAPIDOCR or _TESSERACT) and _PYMUPDF
            else "扫描型 PDF 需要 OCR：pip install rapidocr_onnxruntime pymupdf"
        ),
    }


def _get_engine():
    """懒加载 RapidOCR 引擎（首次调用会加载 ONNX 模型，较慢）。"""
    global _engine, _engine_loaded
    if _engine_loaded:
        return _engine
    _engine_loaded = True
    if _RAPIDOCR:
        try:
            _engine = RapidOCR()
            logger.info("RapidOCR 引擎已加载")
        except Exception as exc:  # noqa: BLE001
            logger.warning("RapidOCR 加载失败：%s", exc)
            _engine = None
    return _engine


def ocr_image_bytes(data: bytes) -> str:
    """对图片字节做 OCR，返回识别出的文本。

    优先 RapidOCR；不可用时尝试 pytesseract；都失败返回空串。
    """
    if not data:
        return ""

    # 1) RapidOCR
    engine = _get_engine()
    if engine is not None:
        try:
            result, _ = engine(data)
            if result:
                # result 是 [[box, text, score], ...]
                lines = [str(item[1]) for item in result if len(item) >= 2]
                return "\n".join(lines).strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("RapidOCR 识别失败：%s", exc)

    # 2) pytesseract 兜底
    if _TESSERACT:
        try:
            import io

            from PIL import Image
            import pytesseract as tess

            img = Image.open(io.BytesIO(data))
            return str(tess.image_to_string(img)).strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tesseract 识别失败：%s", exc)

    return ""


def render_pdf_pages(path: str, dpi: int = 200, max_pages: int = 50) -> list[tuple[int, bytes]]:
    """把 PDF 的每一页渲染成 PNG 字节。

    返回 [(页码, png_bytes), ...]。PyMuPDF 不可用或渲染失败时返回空列表。
    """
    if not _PYMUPDF:
        return []
    pages: list[tuple[int, bytes]] = []
    try:
        doc = pymupdf.open(path)
        try:
            total = min(doc.page_count, max_pages)
            for i in range(total):
                try:
                    # 200 DPI 足够 OCR，再高只会变慢
                    pix = doc[i].get_pixmap(dpi=dpi)
                    pages.append((i + 1, pix.tobytes("png")))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("渲染第 %d 页失败：%s", i + 1, exc)
        finally:
            doc.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("打开 PDF 渲染失败：%s", exc)
    return pages
