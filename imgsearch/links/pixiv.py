"""
Pixiv URL 生成器

从 CSV 文件中读取 pixiv_id 和 pixiv_page，
套用 URL 模板生成可直接访问的 Pixiv 图片链接，
每行一个 URL 输出到文本文件。

支持多种 URL 模板（下载源）：
  - pixiv.re:   https://pixiv.re/{pixiv_id}_p{page}.jpg
  - pixiv.cat:  https://pixiv.cat/{pixiv_id}_{page}.jpg
  - 官方:       https://www.pixiv.net/artworks/{pixiv_id}

模板可动态增删管理，存储在 config.json 中。
"""

import csv
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

from imgsearch.config import get, save_config, PROJECT_DIR


# ──────────────────────────────────────────────
#  URL 模板数据模型
# ──────────────────────────────────────────────


@dataclass
class PixivSource:
    """Pixiv URL 模板配置"""

    name: str                       # 模板名称，如 "pixiv.re"
    base_url: str                   # URL 模板，支持 {pixiv_id} 和 {page} 占位符
    enabled: bool = True            # 是否启用
    priority: int = 0               # 优先级（数字越小越优先，仅用于列表排序）

    def format_url(self, pixiv_id: str, page: int = 0) -> str:
        """根据模板生成实际 URL"""
        return self.base_url.format(pixiv_id=pixiv_id, page=page)


# ──────────────────────────────────────────────
#  默认模板
# ──────────────────────────────────────────────

_DEFAULT_SOURCES = [
    PixivSource(
        name="pixiv.re",
        base_url="https://pixiv.re/{pixiv_id}_p{page}.jpg",
        enabled=True,
        priority=1,
    ),
    PixivSource(
        name="pixiv.cat",
        base_url="https://pixiv.cat/{pixiv_id}_{page}.jpg",
        enabled=True,
        priority=2,
    ),
    PixivSource(
        name="Official",
        base_url="https://www.pixiv.net/artworks/{pixiv_id}",
        enabled=True,
        priority=3,
    ),
]

_CONFIG_KEY = "pixiv_sources"


# ──────────────────────────────────────────────
#  URL 生成器
# ──────────────────────────────────────────────


class PixivUrlGenerator:
    """Pixiv URL 生成管理器"""

    def __init__(self):
        self._sources: List[PixivSource] = []
        self._load_sources()

    # ── 源管理 ──────────────────────────────────

    # PixivSource 期望的字段集合（用于兼容旧配置）
    _SOURCE_FIELDS = {f.name for f in PixivSource.__dataclass_fields__.values()}

    def _load_sources(self):
        """从配置加载所有 URL 模板"""
        raw_sources = get(_CONFIG_KEY, None)
        if raw_sources is None:
            self._sources = list(_DEFAULT_SOURCES)
            self._save_sources()
        else:
            # 过滤掉旧配置中不存在的字段（如 referer, need_cookie）
            self._sources = [
                PixivSource(**{k: v for k, v in s.items() if k in self._SOURCE_FIELDS})
                for s in raw_sources
            ]

    def _save_sources(self):
        """将模板列表保存到配置"""
        raw = [asdict(s) for s in self._sources]
        save_config(_CONFIG_KEY, raw)

    def list_sources(self) -> List[PixivSource]:
        """获取所有模板（按优先级排序）"""
        return sorted(self._sources, key=lambda s: s.priority)

    def get_enabled_sources(self) -> List[PixivSource]:
        """获取所有启用的模板（按优先级排序）"""
        return sorted(
            [s for s in self._sources if s.enabled],
            key=lambda s: s.priority,
        )

    def add_source(self, name: str, base_url: str, priority: int = None) -> bool:
        """添加新的 URL 模板"""
        if any(s.name.lower() == name.lower() for s in self._sources):
            return False
        if priority is None:
            priority = max((s.priority for s in self._sources), default=0) + 1
        self._sources.append(PixivSource(
            name=name, base_url=base_url, priority=priority,
        ))
        self._save_sources()
        return True

    def remove_source(self, name: str) -> bool:
        """删除指定模板"""
        for i, s in enumerate(self._sources):
            if s.name.lower() == name.lower():
                self._sources.pop(i)
                self._save_sources()
                return True
        return False

    def toggle_source(self, name: str) -> Optional[bool]:
        """切换模板启用/禁用状态"""
        for s in self._sources:
            if s.name.lower() == name.lower():
                s.enabled = not s.enabled
                self._save_sources()
                return s.enabled
        return None

    def update_source(self, name: str, **kwargs) -> bool:
        """更新模板属性"""
        for s in self._sources:
            if s.name.lower() == name.lower():
                for k, v in kwargs.items():
                    if hasattr(s, k):
                        setattr(s, k, v)
                self._save_sources()
                return True
        return False

    @staticmethod
    def get_default_sources() -> List[dict]:
        """获取默认模板列表（用于恢复初始设置）"""
        return [asdict(s) for s in _DEFAULT_SOURCES]

    # ── URL 生成核心 ─────────────────────────────

    def generate_urls(
        self,
        pixiv_ids: List[str],
        pages: List[int] = None,
        source_name: str = None,
    ) -> List[str]:
        """
        根据 Pixiv ID 列表生成 URL

        Args:
            pixiv_ids: Pixiv 作品 ID 列表
            pages: 页码列表，与 pixiv_ids 一一对应；None 则全部为 0
            source_name: 指定使用的模板名，None 则使用优先级最高的启用模板

        Returns:
            URL 列表，与输入顺序一一对应
        """
        # 确定使用的模板
        if source_name:
            source = next(
                (s for s in self._sources
                 if s.name.lower() == source_name.lower() and s.enabled),
                None,
            )
            if not source:
                raise ValueError(
                    f"未找到启用的模板: {source_name}"
                )
        else:
            enabled = self.get_enabled_sources()
            if not enabled:
                raise ValueError("没有启用的 URL 模板，请先启用至少一个模板")
            source = enabled[0]

        # 生成 URL
        urls = []
        for i, pixiv_id in enumerate(pixiv_ids):
            page = pages[i] if pages else 0
            urls.append(source.format_url(pixiv_id, page))

        return urls

    def generate_from_csv(
        self,
        csv_path: str,
        output_path: str = None,
        source_name: str = None,
        id_column: str = "pixiv_id",
        page_column: str = "pixiv_page",
    ) -> List[str]:
        """
        从 CSV 文件中读取 Pixiv ID 并生成 URL

        CSV 文件格式参考 search_results.csv，必须包含 pixiv_id 列，
        pixiv_page 可选（默认 0）。

        Args:
            csv_path: CSV 文件路径
            output_path: 输出 txt 文件路径，None 则不保存文件
            source_name: 指定模板名
            id_column: CSV 中 Pixiv ID 的列名
            page_column: CSV 中页码的列名

        Returns:
            生成的 URL 列表
        """
        csv_path = Path(csv_path)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV 文件不存在: {csv_path}")

        pixiv_ids = []
        pages = []

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)

            if id_column not in reader.fieldnames:
                raise ValueError(
                    f"CSV 文件缺少 '{id_column}' 列。\n"
                    f"可用列: {', '.join(reader.fieldnames)}"
                )

            has_page = page_column in reader.fieldnames

            for row in reader:
                pid = row.get(id_column, "").strip()
                if not pid:
                    continue
                pixiv_ids.append(pid)

                if has_page:
                    try:
                        p = int(row.get(page_column, "0").strip() or "0")
                    except (ValueError, AttributeError):
                        p = 0
                    pages.append(p)
                else:
                    pages.append(0)

        if not pixiv_ids:
            raise ValueError(f"CSV 文件中没有有效的 Pixiv ID")

        # 生成 URL
        urls = self.generate_urls(pixiv_ids, pages, source_name)

        # 输出到文件
        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("\n".join(urls) + "\n")

        return urls

    def generate_from_results(
        self,
        results: List,
        source_name: str = None,
    ) -> List[str]:
        """
        从 SearchResult 对象列表生成 URL

        Args:
            results: SearchResult 对象列表
            source_name: 指定模板名

        Returns:
            URL 列表
        """
        pixiv_ids = []
        pages = []
        for r in results:
            if r.pixiv_id:
                pixiv_ids.append(r.pixiv_id)
                pages.append(r.pixiv_page)

        if not pixiv_ids:
            return []

        return self.generate_urls(pixiv_ids, pages, source_name)
