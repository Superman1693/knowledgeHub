"""pytest 公共配置。"""
from __future__ import annotations

import sys
from pathlib import Path

# 保证能 import app 包
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
