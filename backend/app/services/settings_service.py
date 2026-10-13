"""系统设置服务：DB 覆盖层 + .env 密钥写入 + 模型检测。"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.factory import embedding_configured, get_embedding_provider, get_provider
from app.core.config import settings
from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.models import AppSetting
from app.schemas.settings import ModelTestResult, SettingsOut, SettingsUpdate

logger = get_logger(__name__)

# 允许写入 DB 覆盖层的非敏感配置项
OVERRIDE_KEYS = [
    "ai_mode",
    "chat_model",
    "embedding_model",
    "embedding_dim",
    "embedding_base_url",
    "local_model_base_url",
    "external_api_base_url",
    "request_timeout",
    "hybrid_alpha",
    "hybrid_beta",
    "search_top_k",
    "max_upload_mb",
    "default_answer_mode",
    "chunk_mode",
    "parent_child_enabled",
    # 重排序开关（此前只在 .env 里，界面改不了）
    "rerank_enabled",
    "rerank_candidates",
    # 数据目录（此前 SettingsUpdate 与设置页都有这一项，但不在本清单里 →
    # 保存后被静默丢弃，界面却提示"已保存"）
    "data_dir",
    # 回收站保留天数（0 = 永不自动清理）
    "trash_retention_days",
    # 联网补充（非敏感项；密钥单独写 .env）
    "web_search_enabled",
    "web_search_provider",
    "web_search_api_url",
    "web_search_top_k",
]

# 项目根目录下的 .env（backend/app/services/settings_service.py → 上溯 3 级）
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


# ---------------- 覆盖层 ----------------
def load_overrides(db: Session) -> dict:
    """从 DB 读取覆盖配置并应用到 settings 单例（启动时调用）。"""
    rows = db.execute(select(AppSetting)).scalars().all()
    data = {r.key: r.value for r in rows}
    for key, value in data.items():
        if key in OVERRIDE_KEYS and value is not None:
            try:
                setattr(settings, key, value.get("v") if isinstance(value, dict) else value)
            except Exception:  # noqa: BLE001
                logger.warning("无法应用配置覆盖：%s", key)
    return data


def _save_override(db: Session, key: str, value) -> None:
    row = db.get(AppSetting, key)
    payload = {"v": value}
    if row:
        row.value = payload
    else:
        db.add(AppSetting(key=key, value=payload))


def to_out(db: Session) -> SettingsOut:
    return SettingsOut(
        ai_mode=settings.ai_mode,
        local_model_base_url=settings.local_model_base_url,
        external_api_base_url=settings.external_api_base_url,
        has_external_key=bool(settings.external_api_key),
        chat_model=settings.chat_model,
        embedding_model=settings.embedding_model,
        embedding_dim=settings.embedding_dim,
        embedding_base_url=settings.embedding_base_url,
        has_embedding_key=bool(settings.embedding_api_key),
        request_timeout=settings.request_timeout,
        data_dir=str(settings.data_path),
        max_upload_mb=settings.max_upload_mb,
        hybrid_alpha=settings.hybrid_alpha,
        hybrid_beta=settings.hybrid_beta,
        search_top_k=settings.search_top_k,
        chunk_mode=settings.chunk_mode,
        parent_child_enabled=settings.parent_child_enabled,
        rerank_enabled=settings.rerank_enabled,
        rerank_candidates=settings.rerank_candidates,
        trash_retention_days=settings.trash_retention_days,
        storage_mode=settings.storage_mode,
        default_answer_mode=getattr(settings, "default_answer_mode", "detail"),
        web_search_enabled=settings.web_search_enabled,
        web_search_provider=settings.web_search_provider,
        web_search_api_url=settings.web_search_api_url,
        web_search_top_k=settings.web_search_top_k,
        has_web_search_key=bool(settings.web_search_api_key),
    )


def update(db: Session, payload: SettingsUpdate) -> SettingsOut:
    """更新配置：非敏感项入 DB 覆盖层，密钥写入 .env。"""
    data = payload.model_dump(exclude_none=True)

    # 密钥单独处理：写入 .env，不落 DB
    if "external_api_key" in data:
        _write_env("EXTERNAL_API_KEY", str(data.pop("external_api_key")))
        settings.external_api_key = str(payload.external_api_key)
    if "embedding_api_key" in data:
        _write_env("EMBEDDING_API_KEY", str(data.pop("embedding_api_key")))
        settings.embedding_api_key = str(payload.embedding_api_key)
    if "web_search_api_key" in data:
        _write_env("WEB_SEARCH_API_KEY", str(data.pop("web_search_api_key")))
        settings.web_search_api_key = str(payload.web_search_api_key)

    for key, value in data.items():
        if key not in OVERRIDE_KEYS:
            continue
        if key == "data_dir":
            value = _normalize_data_dir(db, str(value))
            if value is None:
                # 指向的还是同一个目录（只是写法不同）→ 不写覆盖层，
                # 避免把 "./data" 漂移成绝对路径后再也回不去
                continue
        setattr(settings, key, value)
        _save_override(db, key, value)

    db.commit()
    return to_out(db)


def _normalize_data_dir(db: Session, new_dir: str) -> str | None:
    """校验「切换数据目录」，返回应写入的值；`None` 表示无需改动。

    两个坑都要处理：
    1. 设置页回传的是**已解析的绝对路径**，而 `settings.data_dir` 可能是 `./data`
       这种相对写法——两者指向同一目录时必须视为"没改"，否则每次保存都会误报冲突；
    2. 库中 `documents.file_path` 存的是**相对数据目录**的路径，直接换目录会让
       已有文档全部指向空气，所以库里有文档时拒绝直接切换并说明正确做法。
    """
    from pathlib import Path

    from sqlalchemy import func, select

    from app.core.config import PROJECT_ROOT
    from app.models import Document

    candidate = Path(new_dir).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    if candidate.resolve() == settings.data_path.resolve():
        return None

    count = db.execute(select(func.count()).select_from(Document)).scalar_one()
    if count:
        raise ValidationError(
            f"库中已有 {count} 篇文档，直接切换数据目录会让它们的文件路径全部失效。"
            "请先用「数据与备份」备份，把文件迁到新目录后，在 .env 里修改 DATA_DIR 并重启。"
        )
    return new_dir


def _write_env(key: str, value: str) -> None:
    """把键值写入 .env（存在则替换，不存在则追加）。"""
    lines: list[str] = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------- 模型检测 ----------------
async def test_model(db: Session) -> ModelTestResult:
    """检测对话服务与嵌入服务。"""
    provider = get_provider()
    ok, message = await provider.health()
    models = await provider.list_models() if ok else []

    # 嵌入服务单独检测（可能与对话服务不是同一家）
    embedding_ok = False
    if not embedding_configured():
        embedding_message = "未配置嵌入模型（EMBEDDING_MODEL 为空）"
    else:
        try:
            vecs = await get_embedding_provider().embed(["连通性测试"])
            if vecs and vecs[0]:
                dim = len(vecs[0])
                embedding_ok = True
                embedding_message = f"嵌入服务可用，维度 {dim}"
                if dim != settings.embedding_dim:
                    embedding_ok = False
                    embedding_message = (
                        f"嵌入维度不匹配：服务返回 {dim} 维，"
                        f"配置为 {settings.embedding_dim} 维，请修改「嵌入维度」后重建索引"
                    )
            else:
                embedding_message = "嵌入服务返回为空"
        except Exception as exc:  # noqa: BLE001
            embedding_message = f"嵌入服务不可用：{exc}"

    return ModelTestResult(
        ok=ok,
        message=message,
        models=models,
        embedding_ok=embedding_ok,
        embedding_message=embedding_message,
    )
