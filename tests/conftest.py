"""
pytest 配置：将项目根目录加入 sys.path，使测试能直接 import 各模块
"""
import sys
from pathlib import Path

# 项目根目录 = tests/ 的父目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
