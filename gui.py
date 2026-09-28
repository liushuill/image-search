"""
二次元图片溯源工具 - GUI 图形界面

使用:
  python gui.py

功能:
  - 单张图片搜索（拖拽或浏览）
  - 批量搜索图片目录
  - 配置管理（API Key / 代理）
  - 图片预览
  - 一键打开 Pixiv
  - 导出 CSV 结果

注意: CLI 功能完全保留，使用 python main.py 即可
"""

import sys
import csv
import json
import time
import webbrowser
import threading
from pathlib import Path
from typing import List, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk

# 将项目根目录加入 sys.path
_project_root = str(Path(__file__).parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from imgsearch.config import save_config, load_config
from main import search_image
from imgsearch.engines.base import SearchResult
from imgsearch.engines.config import EngineManager
from imgsearch.links.pixiv import PixivUrlGenerator
from imgsearch.processor.image_utils import (
    is_image_file,
    get_image_info,
    get_file_hash,
)


# ──────────────────────────────────────────────
#  界面颜色与字体常量
# ──────────────────────────────────────────────
COLOR_BG = "#f5f5f5"
COLOR_FRAME = "#ffffff"
COLOR_ACCENT = "#4a90d9"
COLOR_SUCCESS = "#27ae60"
COLOR_WARN = "#f39c12"
COLOR_ERROR = "#e74c3c"
COLOR_TEXT = "#2c3e50"
COLOR_TEXT_SECONDARY = "#7f8c8d"
COLOR_BORDER = "#dcdde1"

FONT_DEFAULT = ("Microsoft YaHei UI", 10)
FONT_TITLE = ("Microsoft YaHei UI", 14, "bold")
FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_MONO = ("Consolas", 10)

# 缩略图尺寸
THUMB_WIDTH = 240
THUMB_HEIGHT = 240


class ImageTraceGUI:
    """图片溯源工具主窗口"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("🎨 二次元图片溯源工具")
        self.root.geometry("880x720")
        self.root.minsize(700, 600)
        self.root.configure(bg=COLOR_BG)

        # 当前选中的图片路径
        self._current_image_path: Optional[str] = None
        # 当前搜索结果
        self._current_results: List[SearchResult] = []
        # 缩略图 PhotoImage 引用（防止被 GC 回收）
        self._thumb_photo = None
        # 批量搜索状态
        self._batch_running = False
        self._batch_cancel = False

        self._build_ui()
        self._center_window()

    # ── 窗口管理 ─────────────────────────────────

    def _center_window(self):
        """窗口居中显示"""
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"+{x}+{y}")

    def run(self):
        """启动 GUI 主循环"""
        self.root.mainloop()

    # ── 构建界面 ─────────────────────────────────

    def _build_ui(self):
        """构建所有 UI 组件"""
        # ── 顶部标题栏 ──
        title_frame = tk.Frame(self.root, bg=COLOR_BG)
        title_frame.pack(fill=tk.X, padx=16, pady=(12, 4))

        tk.Label(
            title_frame,
            text="🎨 二次元图片溯源工具",
            font=FONT_TITLE,
            bg=COLOR_BG,
            fg=COLOR_TEXT,
        ).pack(side=tk.LEFT)

        # 配置按钮
        self._btn_config = tk.Button(
            title_frame,
            text="⚙ 配置",
            font=FONT_DEFAULT,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT,
            relief=tk.FLAT,
            padx=12,
            cursor="hand2",
            command=self._show_config_window,
        )
        self._btn_config.pack(side=tk.RIGHT, padx=(4, 0))

        # 批量搜索按钮
        self._btn_batch = tk.Button(
            title_frame,
            text="📁 批量搜索",
            font=FONT_DEFAULT,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT,
            relief=tk.FLAT,
            padx=12,
            cursor="hand2",
            command=self._show_batch_window,
        )
        self._btn_batch.pack(side=tk.RIGHT, padx=(4, 0))

        # ── 顶部分隔线 ──
        sep = tk.Frame(self.root, height=1, bg=COLOR_BORDER)
        sep.pack(fill=tk.X, padx=16)

        # ── 搜索输入区域 ──
        self._build_search_bar()

        # ── 主内容区域（预览 + 结果） ──
        self._build_main_content()

        # ── 操作按钮区域 ──
        self._build_action_bar()

        # ── 底部分隔线 ──
        sep2 = tk.Frame(self.root, height=1, bg=COLOR_BORDER)
        sep2.pack(fill=tk.X, padx=16)

        # ── 状态日志区域 ──
        self._build_status_bar()

    def _build_search_bar(self):
        """构建搜索输入栏"""
        frame = tk.Frame(self.root, bg=COLOR_BG)
        frame.pack(fill=tk.X, padx=16, pady=(10, 6))

        tk.Label(frame, text="图片路径:", font=FONT_DEFAULT, bg=COLOR_BG, fg=COLOR_TEXT).pack(
            side=tk.LEFT
        )

        self._entry_path = tk.Entry(
            frame,
            font=FONT_DEFAULT,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT,
            relief=tk.FLAT,
            bd=1,
            highlightthickness=1,
            highlightcolor=COLOR_ACCENT,
            highlightbackground=COLOR_BORDER,
        )
        self._entry_path.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6), ipady=4)
        self._entry_path.bind("<Return>", lambda e: self._do_search())
        # 拖拽文件支持
        self._entry_path.bind("<Button-3>", lambda e: self._paste_path())

        self._btn_browse = tk.Button(
            frame,
            text="📂 浏览",
            font=FONT_DEFAULT,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT,
            relief=tk.FLAT,
            padx=12,
            cursor="hand2",
            command=self._browse_image,
        )
        self._btn_browse.pack(side=tk.LEFT, padx=(0, 6))

        self._btn_search = tk.Button(
            frame,
            text="🔍 搜索",
            font=FONT_BOLD,
            bg=COLOR_ACCENT,
            fg="white",
            relief=tk.FLAT,
            padx=20,
            cursor="hand2",
            command=self._do_search,
        )
        self._btn_search.pack(side=tk.LEFT)

    def _build_main_content(self):
        """构建主内容区域（左：预览，右：结果）"""
        main_frame = tk.Frame(self.root, bg=COLOR_BG)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(6, 6))

        # ── 左侧：图片预览 ──
        preview_frame = tk.Frame(main_frame, bg=COLOR_FRAME, bd=1, relief=tk.FLAT)
        preview_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        # 用 highlight 模拟边框
        preview_frame.configure(highlightbackground=COLOR_BORDER, highlightthickness=1)

        self._label_preview = tk.Label(
            preview_frame,
            text="拖拽或选择图片\n以预览",
            font=FONT_DEFAULT,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT_SECONDARY,
            width=32,
            height=12,
            anchor=tk.CENTER,
            justify=tk.CENTER,
        )
        self._label_preview.pack(padx=6, pady=6)

        # 图片信息标签
        self._label_info = tk.Label(
            preview_frame,
            text="",
            font=FONT_SMALL,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT_SECONDARY,
            anchor=tk.W,
            justify=tk.LEFT,
        )
        self._label_info.pack(fill=tk.X, padx=8, pady=(0, 6))

        # ── 右侧：搜索结果 ──
        result_frame = tk.Frame(main_frame, bg=COLOR_FRAME)
        result_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        result_frame.configure(highlightbackground=COLOR_BORDER, highlightthickness=1)

        # 结果标题
        tk.Label(
            result_frame,
            text="搜索结果",
            font=FONT_BOLD,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT,
            anchor=tk.W,
        ).pack(fill=tk.X, padx=10, pady=(8, 2))

        # 结果列表（带滚动条）
        list_frame = tk.Frame(result_frame, bg=COLOR_FRAME)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._listbox_results = tk.Listbox(
            list_frame,
            font=FONT_MONO,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT,
            selectbackground=COLOR_ACCENT,
            selectforeground="white",
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
            yscrollcommand=scrollbar.set,
            activestyle="none",
        )
        self._listbox_results.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self._listbox_results.yview)
        self._listbox_results.bind("<<ListboxSelect>>", self._on_result_select)

    def _build_action_bar(self):
        """构建操作按钮栏"""
        frame = tk.Frame(self.root, bg=COLOR_BG)
        frame.pack(fill=tk.X, padx=16, pady=(2, 6))

        self._btn_open = tk.Button(
            frame,
            text="🌐 打开 Pixiv",
            font=FONT_DEFAULT,
            bg=COLOR_FRAME,
            fg=COLOR_ACCENT,
            relief=tk.FLAT,
            padx=12,
            cursor="hand2",
            state=tk.DISABLED,
            command=self._open_pixiv,
        )
        self._btn_open.pack(side=tk.LEFT, padx=(0, 6))

        self._btn_url = tk.Button(
            frame,
            text="🔗 生成链接",
            font=FONT_DEFAULT,
            bg=COLOR_SUCCESS,
            fg="white",
            relief=tk.FLAT,
            padx=12,
            cursor="hand2",
            state=tk.DISABLED,
            command=self._generate_urls,
        )
        self._btn_url.pack(side=tk.LEFT, padx=(0, 6))

        self._btn_copy = tk.Button(
            frame,
            text="💾 复制信息",
            font=FONT_DEFAULT,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT,
            relief=tk.FLAT,
            padx=12,
            cursor="hand2",
            state=tk.DISABLED,
            command=self._copy_result,
        )
        self._btn_copy.pack(side=tk.LEFT, padx=(0, 6))

        self._btn_csv = tk.Button(
            frame,
            text="📊 导出 CSV",
            font=FONT_DEFAULT,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT,
            relief=tk.FLAT,
            padx=12,
            cursor="hand2",
            state=tk.DISABLED,
            command=self._save_csv,
        )
        self._btn_csv.pack(side=tk.LEFT, padx=(0, 6))

        # URL 模板管理按钮
        self._btn_sources = tk.Button(
            frame,
            text="🔧 URL 模板",
            font=FONT_SMALL,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT,
            relief=tk.FLAT,
            padx=8,
            cursor="hand2",
            command=self._show_source_window,
        )
        self._btn_sources.pack(side=tk.LEFT, padx=(0, 6))

        # 配额显示标签
        self._label_quota = tk.Label(
            frame,
            text="",
            font=FONT_SMALL,
            bg=COLOR_BG,
            fg=COLOR_TEXT_SECONDARY,
            anchor=tk.E,
        )
        self._label_quota.pack(side=tk.RIGHT, fill=tk.X, expand=True)

    def _build_status_bar(self):
        """构建底部状态日志栏"""
        frame = tk.Frame(self.root, bg=COLOR_BG)
        frame.pack(fill=tk.BOTH, padx=16, pady=(0, 10))

        tk.Label(frame, text="日志:", font=FONT_BOLD, bg=COLOR_BG, fg=COLOR_TEXT).pack(
            anchor=tk.W
        )

        # 日志文本框
        log_frame = tk.Frame(frame, bg=COLOR_FRAME)
        log_frame.pack(fill=tk.BOTH, expand=True)
        log_frame.configure(highlightbackground=COLOR_BORDER, highlightthickness=1)

        scroll_log = tk.Scrollbar(log_frame)
        scroll_log.pack(side=tk.RIGHT, fill=tk.Y)

        self._text_log = tk.Text(
            log_frame,
            font=FONT_MONO,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT,
            relief=tk.FLAT,
            bd=0,
            height=6,
            wrap=tk.WORD,
            yscrollcommand=scroll_log.set,
        )
        self._text_log.pack(fill=tk.BOTH, expand=True)
        scroll_log.config(command=self._text_log.yview)

    # ── 日志 ─────────────────────────────────────

    def _log(self, message: str, color: str = None):
        """追加日志到日志框"""
        self._text_log.insert(tk.END, message + "\n")
        if color:
            start = self._text_log.index(f"end-2l")
            end = self._text_log.index(f"end-1l")
            self._text_log.tag_add(color, start, end)
            self._text_log.tag_configure(color, foreground=color)
        self._text_log.see(tk.END)
        self.root.update_idletasks()

    def _log_error(self, message: str):
        self._log(f"❌ {message}", COLOR_ERROR)

    def _log_warn(self, message: str):
        self._log(f"⚠️ {message}", COLOR_WARN)

    def _log_success(self, message: str):
        self._log(f"✅ {message}", COLOR_SUCCESS)

    def _log_info(self, message: str):
        self._log(f"ℹ️ {message}")

    # ── 图片操作 ─────────────────────────────────

    def _browse_image(self):
        """打开文件选择对话框"""
        path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[
                ("图片文件", "*.jpg *.jpeg *.png *.webp *.bmp *.gif"),
                ("所有文件", "*.*"),
            ],
        )
        if path:
            self._entry_path.delete(0, tk.END)
            self._entry_path.insert(0, path)
            self._preview_image(path)

    def _paste_path(self):
        """右键粘贴路径"""
        try:
            path = self.root.clipboard_get()
            if Path(path).exists():
                self._entry_path.delete(0, tk.END)
                self._entry_path.insert(0, path)
                self._preview_image(path)
        except Exception:
            pass

    def _preview_image(self, path: str):
        """预览图片并显示信息"""
        file_path = Path(path)
        if not file_path.exists() or not is_image_file(str(file_path)):
            return

        self._current_image_path = str(file_path)

        try:
            img = Image.open(file_path)
            # 缩略图
            img.thumbnail((THUMB_WIDTH, THUMB_HEIGHT), Image.LANCZOS)
            self._thumb_photo = ImageTk.PhotoImage(img)
            self._label_preview.config(
                image=self._thumb_photo,
                text="",
                width=self._thumb_photo.width(),
                height=self._thumb_photo.height(),
            )

            # 图片信息
            info = get_image_info(str(file_path))
            if info:
                size_kb = info["size_bytes"] / 1024
                text = (
                    f"尺寸: {info['width']} x {info['height']}\n"
                    f"格式: {info['format']}  |  {size_kb:.1f} KB\n"
                    f"色彩: {info['mode']}"
                )
                # 计算文件哈希
                file_hash = get_file_hash(str(file_path))
                if file_hash:
                    text += f"\n哈希: {file_hash}"
                self._label_info.config(text=text)
            else:
                self._label_info.config(text="无法读取图片信息")

        except Exception as e:
            self._label_preview.config(
                text=f"预览失败\n{str(e)[:40]}",
                image="",
                width=32,
                height=12,
            )
            self._label_info.config(text="")

    # ── 搜索 ─────────────────────────────────────

    def _do_search(self):
        """执行搜索（在新线程中运行）"""
        path = self._entry_path.get().strip()
        if not path:
            self._log_warn("请先输入或浏览选择图片路径")
            return

        file_path = Path(path)
        if not file_path.exists():
            self._log_error(f"文件不存在: {path}")
            return

        if not is_image_file(path):
            self._log_error(f"不支持的图片格式: {path}")
            return

        # 预览（如果还没预览）
        if self._current_image_path != str(file_path):
            self._preview_image(str(file_path))

        # 禁用搜索按钮防止重复点击
        self._btn_search.config(text="⏳ 搜索中...", state=tk.DISABLED)
        self._listbox_results.delete(0, tk.END)
        self._listbox_results.insert(tk.END, "搜索中，请稍候...")
        self._current_results = []
        self._update_action_buttons()

        self._log_info(f"开始搜索: {file_path.name}")

        # 在新线程中执行搜索
        thread = threading.Thread(
            target=self._search_thread,
            args=(str(file_path),),
            daemon=True,
        )
        thread.start()

    def _search_thread(self, image_path: str):
        """搜索线程"""
        try:
            results = search_image(image_path)

            # 回到主线程更新 UI
            self.root.after(0, self._on_search_done, results)
        except Exception as e:
            self.root.after(0, self._on_search_error, str(e))

    def _on_search_done(self, results: List[SearchResult]):
        """搜索完成 - 主线程回调"""
        self._btn_search.config(text="🔍 搜索", state=tk.NORMAL)
        self._listbox_results.delete(0, tk.END)

        self._current_results = results

        if not results:
            self._listbox_results.insert(tk.END, "❌ 未找到匹配结果")
            self._log_warn("未找到匹配结果")
            self._update_action_buttons()
            return

        # 显示结果列表
        for i, r in enumerate(results, 1):
            line = self._format_result_line(i, r)
            self._listbox_results.insert(tk.END, line)

        # 自动选中第一个
        self._listbox_results.selection_set(0)
        self._on_result_select(None)

        best = results[0]
        self._log_success(
            f"SauceNAO: 匹配到 {len(results)} 个结果，"
            f"最高相似度 {best.similarity:.1f}%"
            + (f"，Pixiv ID: {best.pixiv_id}" if best.pixiv_id else "")
        )

        # 显示配额信息
        self._update_quota_display()

        self._update_action_buttons()

    def _on_search_error(self, error_msg: str):
        """搜索出错 - 主线程回调"""
        self._btn_search.config(text="🔍 搜索", state=tk.NORMAL)
        self._listbox_results.delete(0, tk.END)
        self._listbox_results.insert(tk.END, f"❌ 搜索失败")
        self._log_error(f"搜索失败: {error_msg}")
        self._update_action_buttons()

    # ── 结果显示 ────────────────────────────────

    def _format_result_line(self, index: int, r: SearchResult) -> str:
        """格式化搜索结果行"""
        parts = [f"[{index}]"]
        parts.append(f"<{r.source}>")

        if r.similarity > 0:
            parts.append(f"{r.similarity:.1f}%")

        if r.pixiv_id:
            parts.append(f"#{r.pixiv_image_id() or r.pixiv_id}")

        if r.artist:
            parts.append(f"@{r.artist}")

        if r.title:
            title = r.title if len(r.title) <= 20 else r.title[:17] + "..."
            parts.append(f"「{title}」")

        return "  ".join(parts)

    def _on_result_select(self, event):
        """选中结果时更新详情"""
        sel = self._listbox_results.curselection()
        if not sel or not self._current_results:
            return

        idx = sel[0]
        if idx >= len(self._current_results):
            return

        r = self._current_results[idx]

        # 在日志区域显示详情
        details = []
        if r.source:
            details.append(f"来源: {r.source}")
        if r.similarity > 0:
            details.append(f"相似度: {r.similarity:.1f}%")
        if r.pixiv_id:
            details.append(f"Pixiv: {r.pixiv_image_id() or r.pixiv_id}")
        if r.artist:
            details.append(f"画师: {r.artist}")
        if r.title:
            details.append(f"标题: {r.title}")
        if r.material:
            details.append(f"作品: {r.material}")
        if r.ext_urls:
            details.append(f"链接: {r.ext_urls[0]}")

        if details:
            self._log_info(" | ".join(details))

        self._update_action_buttons()

    # ── 操作按钮 ────────────────────────────────

    def _update_action_buttons(self):
        """更新操作按钮的可用状态"""
        has_results = bool(self._current_results)
        has_pixiv = has_results and any(r.pixiv_id for r in self._current_results)

        self._btn_open.config(state=tk.NORMAL if has_pixiv else tk.DISABLED)
        self._btn_url.config(state=tk.NORMAL if has_pixiv else tk.DISABLED)
        self._btn_copy.config(state=tk.NORMAL if has_results else tk.DISABLED)
        self._btn_csv.config(state=tk.NORMAL if has_results else tk.DISABLED)

    def _open_pixiv(self):
        """在浏览器中打开 Pixiv 作品页"""
        if not self._current_results:
            return
        # 找第一个有 pixiv_id 的结果
        for r in self._current_results:
            if r.pixiv_id:
                url = f"https://www.pixiv.net/artworks/{r.pixiv_id}"
                webbrowser.open(url)
                self._log_info(f"已打开: {url}")
                return
        self._log_warn("当前结果中没有 Pixiv ID")

    def _copy_result(self):
        """复制最佳结果信息到剪贴板"""
        if not self._current_results:
            return
        best = self._current_results[0]
        lines = []
        if best.pixiv_id:
            lines.append(f"Pixiv ID: {best.pixiv_id}")
            lines.append(f"Pixiv: https://www.pixiv.net/artworks/{best.pixiv_id}")
        if best.artist:
            lines.append(f"画师: {best.artist}")
        if best.title:
            lines.append(f"标题: {best.title}")
        if best.similarity > 0:
            lines.append(f"相似度: {best.similarity:.1f}%")
        if best.ext_urls:
            lines.append(f"来源: {best.ext_urls[0]}")

        text = "\n".join(lines)
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self._log_success("已复制到剪贴板")

    def _save_csv(self):
        """导出当前结果为 CSV"""
        if not self._current_results:
            self._log_warn("没有结果可导出")
            return

        path = filedialog.asksaveasfilename(
            title="保存 CSV",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")],
            initialfile="search_result.csv",
        )
        if not path:
            return

        try:
            fieldnames = [
                "source", "similarity",
                "pixiv_id", "pixiv_page", "pixiv_image_id",
                "artist", "artist_id", "title", "material",
                "ext_url", "highres_url",
                "danbooru_id", "gelbooru_id", "twitter_id",
            ]
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for r in self._current_results:
                    writer.writerow({
                        "source": r.source,
                        "similarity": f"{r.similarity:.1f}%" if r.similarity > 0 else "",
                        "pixiv_id": r.pixiv_id or "",
                        "pixiv_page": r.pixiv_page,
                        "pixiv_image_id": r.pixiv_image_id() or "",
                        "artist": r.artist or "",
                        "artist_id": r.artist_id or "",
                        "title": r.title or "",
                        "material": r.material or "",
                        "ext_url": r.ext_urls[0] if r.ext_urls else "",
                        "highres_url": r.highres_url or "",
                        "danbooru_id": r.danbooru_id or "",
                        "gelbooru_id": r.gelbooru_id or "",
                        "twitter_id": r.twitter_id or "",
                    })
            self._log_success(f"CSV 已保存: {path}")
        except Exception as e:
            self._log_error(f"保存 CSV 失败: {e}")

    # ── 生成 Pixiv URL ─────────────────────────

    def _generate_urls(self):
        """从当前搜索结果生成 Pixiv URL 并显示"""
        if not self._current_results:
            self._log_warn("没有可生成链接的结果")
            return

        # 收集所有有 pixiv_id 的结果
        target_results = [r for r in self._current_results if r.pixiv_id]
        if not target_results:
            self._log_warn("当前结果中没有 Pixiv ID")
            return

        try:
            generator = PixivUrlGenerator()
            urls = generator.generate_from_results(target_results)

            if urls:
                self._log_success(f"生成了 {len(urls)} 个 Pixiv URL:")
                for url in urls:
                    self._log(f"  {url}", COLOR_ACCENT)

                # 也复制到剪贴板
                text = "\n".join(urls)
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
                self._log_success("URL 已复制到剪贴板，可直接粘贴到下载工具中")
            else:
                self._log_warn("未能生成 URL，请检查 URL 模板设置")

        except Exception as e:
            self._log_error(f"生成 URL 失败: {e}")

    # ── URL 模板管理窗口 ───────────────────────

    def _show_source_window(self):
        """弹出 URL 模板管理窗口"""
        win = tk.Toplevel(self.root)
        win.title("🔧 Pixiv URL 模板管理")
        win.geometry("660x460")
        win.configure(bg=COLOR_FRAME)
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        win.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 660) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 460) // 2
        win.geometry(f"+{x}+{y}")

        self._source_win = win
        self._refresh_source_list(win)

    def _refresh_source_list(self, win=None):
        """刷新 URL 模板列表显示"""
        if win is None:
            win = self._source_win

        for w in win.winfo_children():
            w.destroy()

        generator = PixivUrlGenerator()
        sources = generator.list_sources()

        # 标题
        tk.Label(
            win,
            text="Pixiv URL 模板管理",
            font=FONT_TITLE,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT,
        ).pack(anchor=tk.W, padx=16, pady=(16, 4))

        tk.Label(
            win,
            text="将 CSV 中的 pixiv_id 套用模板生成可访问的 URL。支持 {pixiv_id} 和 {page} 占位符。",
            font=FONT_SMALL,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT_SECONDARY,
            wraplength=620,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, padx=16, pady=(0, 8))

        # 列表
        list_frame = tk.Frame(win, bg=COLOR_FRAME)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 8))
        list_frame.configure(highlightbackground=COLOR_BORDER, highlightthickness=1)

        scroll = tk.Scrollbar(list_frame)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        header_frame = tk.Frame(list_frame, bg=COLOR_BORDER)
        header_frame.pack(fill=tk.X)

        col_widths = [14, 8, 8, 42]
        col_labels = ["名称", "状态", "优先级", "URL 模板"]
        for i, (w, label) in enumerate(zip(col_widths, col_labels)):
            tk.Label(
                header_frame,
                text=label,
                font=FONT_BOLD,
                bg="#e8e8e8",
                fg=COLOR_TEXT,
                width=w,
                anchor=tk.W,
            ).pack(side=tk.LEFT, padx=4, pady=2)

        text_widget = tk.Text(
            list_frame,
            font=FONT_MONO,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT,
            relief=tk.FLAT,
            bd=0,
            height=10,
            wrap=tk.NONE,
            yscrollcommand=scroll.set,
        )
        text_widget.pack(fill=tk.BOTH, expand=True)
        scroll.config(command=text_widget.yview)

        for s in sources:
            status = "✅ 启用" if s.enabled else "❌ 禁用"
            line = f"{s.name:<14} {status:<8} {s.priority:<8} {s.base_url}"
            text_widget.insert(tk.END, line + "\n")

        text_widget.config(state=tk.DISABLED)

        # 操作按钮
        btn_frame = tk.Frame(win, bg=COLOR_FRAME)
        btn_frame.pack(fill=tk.X, padx=16, pady=(0, 16))

        # 添加
        tk.Label(btn_frame, text="添加:", font=FONT_BOLD, bg=COLOR_FRAME, fg=COLOR_TEXT).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        name_var = tk.StringVar()
        name_entry = tk.Entry(
            btn_frame, textvariable=name_var, font=FONT_SMALL,
            bg="white", fg=COLOR_TEXT, relief=tk.FLAT, bd=1, width=12,
        )
        name_entry.pack(side=tk.LEFT, padx=(0, 4), ipady=2)
        name_entry.insert(0, "名称")

        url_var = tk.StringVar()
        url_entry = tk.Entry(
            btn_frame, textvariable=url_var, font=FONT_SMALL,
            bg="white", fg=COLOR_TEXT, relief=tk.FLAT, bd=1, width=30,
        )
        url_entry.pack(side=tk.LEFT, padx=(0, 4), ipady=2)
        url_entry.insert(0, "https://.../{pixiv_id}_p{page}.jpg")

        def _add_source():
            name = name_var.get().strip()
            url = url_var.get().strip()
            if not name or not url or name == "名称":
                messagebox.showwarning("提示", "请输入有效名称和 URL 模板", parent=win)
                return
            ok = generator.add_source(name, url)
            if ok:
                self._log_success(f"已添加模板: {name}")
                self._refresh_source_list(win)
            else:
                messagebox.showwarning("提示", f"模板名称已存在: {name}", parent=win)

        tk.Button(
            btn_frame, text="➕ 添加", font=FONT_SMALL,
            bg=COLOR_ACCENT, fg="white", relief=tk.FLAT, padx=8,
            cursor="hand2", command=_add_source,
        ).pack(side=tk.LEFT, padx=(0, 10))

        del_var = tk.StringVar()
        del_entry = tk.Entry(
            btn_frame, textvariable=del_var, font=FONT_SMALL,
            bg="white", fg=COLOR_TEXT, relief=tk.FLAT, bd=1, width=12,
        )
        del_entry.pack(side=tk.LEFT, padx=(10, 4), ipady=2)
        del_entry.insert(0, "模板名称")

        def _remove_source():
            name = del_var.get().strip()
            if not name or name == "模板名称":
                messagebox.showwarning("提示", "请输入模板名称", parent=win)
                return
            ok = generator.remove_source(name)
            if ok:
                self._log_success(f"已删除模板: {name}")
                self._refresh_source_list(win)
            else:
                messagebox.showwarning("提示", f"未找到模板: {name}", parent=win)

        tk.Button(
            btn_frame, text="🗑 删除", font=FONT_SMALL,
            bg=COLOR_ERROR, fg="white", relief=tk.FLAT, padx=8,
            cursor="hand2", command=_remove_source,
        ).pack(side=tk.LEFT, padx=(0, 4))

        def _toggle_source():
            name = del_var.get().strip()
            if not name or name == "模板名称":
                messagebox.showwarning("提示", "请输入模板名称", parent=win)
                return
            new_state = generator.toggle_source(name)
            if new_state is not None:
                status = "启用" if new_state else "禁用"
                self._log_info(f"已{status}模板: {name}")
                self._refresh_source_list(win)
            else:
                messagebox.showwarning("提示", f"未找到模板: {name}", parent=win)

        tk.Button(
            btn_frame, text="🔄 切换", font=FONT_SMALL,
            bg=COLOR_WARN, fg="white", relief=tk.FLAT, padx=8,
            cursor="hand2", command=_toggle_source,
        ).pack(side=tk.LEFT, padx=(0, 10))

        def _reset_sources():
            if messagebox.askyesno("确认", "恢复默认模板？自定义模板将被清除。", parent=win):
                default_sources = PixivUrlGenerator.get_default_sources()
                save_config("pixiv_sources", default_sources)
                self._log_info("已恢复默认 URL 模板")
                self._refresh_source_list(win)

        tk.Button(
            btn_frame, text="🔁 恢复默认", font=FONT_SMALL,
            bg=COLOR_FRAME, fg=COLOR_TEXT, relief=tk.FLAT, padx=8,
            cursor="hand2", command=_reset_sources,
        ).pack(side=tk.LEFT)

    # ── 配额显示 ────────────────────────────────

    def _update_quota_display(self):
        """更新配额显示（滑动窗口，从引擎配置读取限额和窗口时长）"""
        import time as time_module
        from imgsearch.engines.config import EngineManager

        mgr = EngineManager()
        saucenao_cfg = mgr.get_by_name("sauceNAO")
        long_limit = getattr(saucenao_cfg, "long_limit", 100) if saucenao_cfg else 100
        long_window = getattr(saucenao_cfg, "long_window", 86400) if saucenao_cfg else 86400
        window_hours = long_window // 3600

        quota_file = Path(__file__).parent / "data" / "saucenao_quota.json"
        if quota_file.exists():
            try:
                with open(quota_file, "r") as f:
                    data = json.load(f)
                timestamps = data.get("timestamps", [])
                now = time_module.time()
                cutoff = now - long_window
                active = [t for t in timestamps if t > cutoff]
                used = len(active)
                if long_limit > 0:
                    remaining = max(0, long_limit - used)
                    if active:
                        oldest = min(active)
                        reset_in = int(long_window - (now - oldest))
                        reset_min = reset_in // 60
                        label = f"SauceNAO 配额: {window_hours}h 窗口已用 {used}/{long_limit} | 剩余 {remaining} | 最早约 {reset_min}分钟后释放"
                    else:
                        label = f"SauceNAO 配额: {window_hours}h 窗口已用 0/{long_limit} | 剩余 {long_limit}"
                else:
                    label = f"SauceNAO 配额: {window_hours}h 窗口已用 {used} 次 (无限制)"
                self._label_quota.config(text=label)
                return
            except Exception:
                pass
        self._label_quota.config(text="")

    # ── 配置窗口 ────────────────────────────────

    def _show_config_window(self):
        """弹出配置窗口（简化版：代理 + 引擎管理入口）"""
        win = tk.Toplevel(self.root)
        win.title("⚙ 配置")
        win.geometry("500x320")
        win.configure(bg=COLOR_FRAME)
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        # 居中
        win.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 500) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 320) // 2
        win.geometry(f"+{x}+{y}")

        config = load_config()
        current_proxy = config.get("proxy", "")

        pad_options = {"padx": 16, "pady": (12, 4)}
        entry_options = {
            "font": FONT_DEFAULT,
            "bg": "white",
            "fg": COLOR_TEXT,
            "relief": tk.FLAT,
            "bd": 1,
            "highlightthickness": 1,
            "highlightcolor": COLOR_ACCENT,
            "highlightbackground": COLOR_BORDER,
        }

        # ── 代理 ──
        tk.Label(win, text="HTTP 代理 (可选):", font=FONT_BOLD, bg=COLOR_FRAME, fg=COLOR_TEXT).pack(
            anchor=tk.W, **pad_options
        )
        proxy_var = tk.StringVar(value=current_proxy)
        proxy_entry = tk.Entry(win, textvariable=proxy_var, **entry_options, width=50)
        proxy_entry.pack(fill=tk.X, padx=16, ipady=4)
        tk.Label(
            win,
            text="例如: http://127.0.0.1:7890 （留空则不使用代理）",
            font=FONT_SMALL,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT_SECONDARY,
        ).pack(anchor=tk.W, padx=16, pady=(0, 8))

        # ── 搜索引擎管理 ──
        separator = tk.Frame(win, height=1, bg=COLOR_BORDER)
        separator.pack(fill=tk.X, padx=16, pady=(8, 4))

        eng_frame = tk.Frame(win, bg=COLOR_FRAME)
        eng_frame.pack(fill=tk.X, padx=16, pady=(8, 4))

        mgr = EngineManager()
        engines = mgr.list_all()
        enabled_count = len([e for e in engines if e.enabled])
        summary = f"当前 {len(engines)} 个引擎，已启用 {enabled_count} 个"

        tk.Label(eng_frame, text="🔍 搜索引擎", font=FONT_BOLD, bg=COLOR_FRAME, fg=COLOR_TEXT).pack(
            side=tk.LEFT
        )
        tk.Label(eng_frame, text=summary, font=FONT_SMALL, bg=COLOR_FRAME,
                 fg=COLOR_TEXT_SECONDARY).pack(side=tk.LEFT, padx=(8, 0))

        tk.Button(
            eng_frame,
            text="⚙ 管理配置",
            font=FONT_DEFAULT,
            bg=COLOR_ACCENT,
            fg="white",
            relief=tk.FLAT,
            padx=12,
            cursor="hand2",
            command=lambda: self._show_engine_window(),
        ).pack(side=tk.RIGHT)

        # ── 保存按钮 ──
        btn_frame = tk.Frame(win, bg=COLOR_FRAME)
        btn_frame.pack(fill=tk.X, padx=16, pady=(16, 16))

        def _save():
            proxy_val = proxy_var.get().strip()
            if proxy_val:
                save_config("proxy", proxy_val)
            elif current_proxy:
                save_config("proxy", "")
            self._log_success("配置已保存")
            win.destroy()

        tk.Button(
            btn_frame,
            text="💾 保存",
            font=FONT_BOLD,
            bg=COLOR_ACCENT,
            fg="white",
            relief=tk.FLAT,
            padx=24,
            cursor="hand2",
            command=_save,
        ).pack(side=tk.LEFT)

    # ── 搜索引擎管理窗口 ──────────────────────────

    def _show_engine_window(self):
        """弹出搜索引擎管理窗口（独立配置 + 数字权重排序 + 详情编辑）"""
        win = tk.Toplevel(self.root)
        win.title("🔍 搜索引擎管理")
        win.geometry("680x500")
        win.configure(bg=COLOR_FRAME)
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        win.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 680) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 500) // 2
        win.geometry(f"+{x}+{y}")

        self._engine_win = win
        self._refresh_engine_list(win)

    def _refresh_engine_list(self, win=None):
        """刷新搜索引擎列表显示"""
        if win is None:
            win = self._engine_win

        for w in win.winfo_children():
            w.destroy()

        mgr = EngineManager()
        engines = mgr.list_all()

        # ── 标题 ──
        tk.Label(
            win,
            text="🔍 搜索引擎管理",
            font=FONT_TITLE,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT,
        ).pack(anchor=tk.W, padx=16, pady=(16, 4))

        tk.Label(
            win,
            text="每个引擎独立配置，双击引擎名称或点击 ⚙ 进入详细配置",
            font=FONT_SMALL,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT_SECONDARY,
            wraplength=640,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, padx=16, pady=(0, 8))

        # ── 引擎列表（带双击进入详情） ──
        list_frame = tk.Frame(win, bg=COLOR_FRAME)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 6))
        list_frame.configure(highlightbackground=COLOR_BORDER, highlightthickness=1)

        # Canvas + Scrollbar 实现可滚动的操作按钮行
        canvas = tk.Canvas(list_frame, bg=COLOR_FRAME, bd=0, highlightthickness=0)
        scroll = tk.Scrollbar(list_frame, orient=tk.VERTICAL, command=canvas.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        canvas.configure(yscrollcommand=scroll.set)

        inner_frame = tk.Frame(canvas, bg=COLOR_FRAME)
        canvas.create_window((0, 0), window=inner_frame, anchor=tk.NW, tags="inner")

        def _configure_inner(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner_frame.bind("<Configure>", _configure_inner)

        # 表头
        header = tk.Frame(inner_frame, bg="#e8e8e8")
        header.pack(fill=tk.X, pady=(0, 2))
        col_defs = [
            ("权", 4, tk.W),
            ("引擎名称", 16, tk.W),
            ("状态", 8, tk.W),
            ("类型", 8, tk.W),
            ("操作", 28, tk.W),
        ]
        for text, w, anchor in col_defs:
            tk.Label(header, text=text, font=FONT_BOLD, bg="#e8e8e8",
                     fg=COLOR_TEXT, width=w, anchor=anchor
                     ).pack(side=tk.LEFT, padx=4, pady=2)

        # ── 每行一个引擎 ──
        for e in engines:
            row = tk.Frame(inner_frame, bg=COLOR_FRAME)
            row.pack(fill=tk.X, pady=1)

            # 权重
            tk.Label(row, text=f"#{e.priority}", font=FONT_MONO,
                     bg=COLOR_FRAME, fg=COLOR_ACCENT,
                     width=4, anchor=tk.W).pack(side=tk.LEFT)

            # 引擎名称（双击打开详情）
            name_lbl = tk.Label(row, text=e.name, font=FONT_BOLD,
                                bg=COLOR_FRAME, fg=COLOR_TEXT,
                                width=16, anchor=tk.W, cursor="hand2")
            name_lbl.pack(side=tk.LEFT)
            name_lbl.bind(
                "<Button-1>",
                lambda event, n=e.name: self._show_engine_detail_window(mgr, n, win),
            )
            # 整行也支持双击
            for child in [row]:
                child.bind(
                    "<Double-Button-1>",
                    lambda event, n=e.name: self._show_engine_detail_window(mgr, n, win),
                )

            # 状态
            status_text = "✅ 启用" if e.enabled else "❌ 禁用"
            status_color = COLOR_SUCCESS if e.enabled else COLOR_ERROR
            tk.Label(row, text=status_text, font=FONT_SMALL,
                     bg=COLOR_FRAME, fg=status_color,
                     width=8, anchor=tk.W).pack(side=tk.LEFT)

            # 类型
            type_text = "📦 内置" if mgr.is_builtin(e.name) else "🔧 自定义"
            tk.Label(row, text=type_text, font=FONT_SMALL,
                     bg=COLOR_FRAME, fg=COLOR_TEXT_SECONDARY,
                     width=8, anchor=tk.W).pack(side=tk.LEFT)

            # ⚙ 配置按钮
            btn_config = tk.Button(
                row, text="⚙ 配置", font=FONT_SMALL,
                bg=COLOR_FRAME, fg=COLOR_ACCENT, relief=tk.FLAT,
                padx=4, cursor="hand2",
                command=lambda n=e.name: self._show_engine_detail_window(mgr, n, win),
            )
            btn_config.pack(side=tk.LEFT, padx=(4, 2))

            # ⏯ 启禁
            btn_toggle = tk.Button(
                row, text="⏯ 启禁", font=FONT_SMALL,
                bg=COLOR_FRAME, fg=COLOR_WARN, relief=tk.FLAT,
                padx=4, cursor="hand2",
                command=lambda n=e.name: (mgr.toggle(n),
                    self._log_info(f"已切换引擎: {n}"),
                    self._refresh_engine_list(win)),
            )
            btn_toggle.pack(side=tk.LEFT, padx=(0, 2))

            # ▲ ▼
            btn_up = tk.Button(row, text="▲", font=FONT_SMALL,
                               bg=COLOR_FRAME, fg=COLOR_TEXT, relief=tk.FLAT,
                               padx=4, cursor="hand2",
                               command=lambda n=e.name: (mgr.move(n, -1),
                                   self._refresh_engine_list(win)))
            btn_up.pack(side=tk.LEFT)
            btn_down = tk.Button(row, text="▼", font=FONT_SMALL,
                                 bg=COLOR_FRAME, fg=COLOR_TEXT, relief=tk.FLAT,
                                 padx=4, cursor="hand2",
                                 command=lambda n=e.name: (mgr.move(n, 1),
                                     self._refresh_engine_list(win)))
            btn_down.pack(side=tk.LEFT)

            # 🗑 删除（仅自定义引擎）
            if not mgr.is_builtin(e.name):
                btn_del = tk.Button(row, text="🗑", font=FONT_SMALL,
                                    bg=COLOR_FRAME, fg=COLOR_ERROR, relief=tk.FLAT,
                                    padx=4, cursor="hand2",
                                    command=lambda n=e.name: (
                                        mgr.remove(n),
                                        self._log_info(f"已删除引擎: {n}"),
                                        self._refresh_engine_list(win)))
                btn_del.pack(side=tk.LEFT, padx=(2, 0))

        # ── 添加自定义引擎 ──
        add_frame = tk.Frame(win, bg=COLOR_FRAME)
        add_frame.pack(fill=tk.X, padx=16, pady=(6, 4))

        tk.Label(add_frame, text="添加自定义引擎:", font=FONT_BOLD,
                 bg=COLOR_FRAME, fg=COLOR_TEXT).pack(side=tk.LEFT, padx=(0, 6))

        name_var = tk.StringVar()
        name_entry = tk.Entry(add_frame, textvariable=name_var, font=FONT_SMALL,
                              bg="white", fg=COLOR_TEXT, relief=tk.FLAT,
                              bd=1, width=16)
        name_entry.pack(side=tk.LEFT, padx=(0, 4), ipady=2)
        name_entry.insert(0, "引擎名称")

        def _add_engine():
            name = name_var.get().strip()
            if not name or name == "引擎名称":
                messagebox.showwarning("提示", "请输入有效的引擎名称", parent=win)
                return
            ok = mgr.add(name)
            if ok:
                self._log_success(f"已添加自定义引擎: {name}")
                self._refresh_engine_list(win)
            else:
                messagebox.showwarning("提示", f"引擎名称已存在: {name}", parent=win)

        tk.Button(add_frame, text="➕ 添加", font=FONT_SMALL,
                  bg=COLOR_ACCENT, fg="white", relief=tk.FLAT,
                  padx=8, cursor="hand2", command=_add_engine).pack(side=tk.LEFT)

        # ── 重置按钮 ──
        reset_frame = tk.Frame(win, bg=COLOR_FRAME)
        reset_frame.pack(fill=tk.X, padx=16, pady=(4, 12))

        def _reset_engines():
            if messagebox.askyesno("确认重置",
                                   "恢复默认搜索引擎列表？自定义引擎将被清除。",
                                   parent=win):
                mgr.reset()
                self._log_info("已恢复默认搜索引擎")
                self._refresh_engine_list(win)

        tk.Button(reset_frame, text="🔁 恢复默认", font=FONT_DEFAULT,
                  bg=COLOR_FRAME, fg=COLOR_TEXT, relief=tk.FLAT,
                  padx=12, cursor="hand2", command=_reset_engines).pack(side=tk.LEFT)

        tk.Label(reset_frame, text="💡 权重数字自动调整，按当前顺序编号为 1, 2, 3...",
                 font=FONT_SMALL, bg=COLOR_FRAME,
                 fg=COLOR_TEXT_SECONDARY).pack(side=tk.LEFT, padx=(12, 0))

    # ──────────────────────────────────────────────
    #  键值对编辑器（供 _show_engine_detail_window 使用）
    # ──────────────────────────────────────────────

    def _build_kv_editor(self, parent, initial_dict=None) -> dict:
        """
        构建可编辑的键值对列表

        Args:
            parent: 父 Frame
            initial_dict: 初始键值对字典

        Returns:
            {"frame": Frame, "rows": [{"key": StringVar, "val": StringVar}, ...]}
        """
        outer = tk.Frame(parent, bg=COLOR_FRAME)

        rows_container = tk.Frame(outer, bg=COLOR_FRAME)
        rows_container.pack(fill=tk.X)

        kv_rows = []  # [{"key": StringVar, "val": StringVar}, ...]

        def _rebuild_rows():
            """清空并重新绘制所有行"""
            for w in rows_container.winfo_children():
                w.destroy()
            for rd in kv_rows:
                row_f = tk.Frame(rows_container, bg=COLOR_FRAME)
                row_f.pack(fill=tk.X, pady=(0, 3))

                key_entry = tk.Entry(row_f, textvariable=rd["key"],
                                     font=FONT_SMALL, bg="white", fg=COLOR_TEXT,
                                     relief=tk.FLAT, bd=1, width=24)
                key_entry.pack(side=tk.LEFT, padx=(0, 4), ipady=2)

                tk.Label(row_f, text="=", font=FONT_SMALL,
                         bg=COLOR_FRAME, fg=COLOR_TEXT_SECONDARY).pack(side=tk.LEFT, padx=(0, 4))

                val_entry = tk.Entry(row_f, textvariable=rd["val"],
                                     font=FONT_SMALL, bg="white", fg=COLOR_TEXT,
                                     relief=tk.FLAT, bd=1, width=36)
                val_entry.pack(side=tk.LEFT, padx=(0, 4), ipady=2)

                def _del_row(r=rd):
                    kv_rows.remove(r)
                    _rebuild_rows()

                tk.Button(row_f, text="✕", font=FONT_SMALL,
                          bg=COLOR_FRAME, fg=COLOR_ERROR, relief=tk.FLAT,
                          padx=4, cursor="hand2", command=_del_row).pack(side=tk.LEFT)

        # 从 initial_dict 填充初始行
        if initial_dict:
            for k, v in initial_dict.items():
                kv_rows.append({"key": tk.StringVar(value=k), "val": tk.StringVar(value=v)})

        _rebuild_rows()

        # 添加按钮
        def _add_row():
            kv_rows.append({"key": tk.StringVar(value=""), "val": tk.StringVar(value="")})
            _rebuild_rows()

        add_btn = tk.Button(outer, text="➕ 添加一行", font=FONT_SMALL,
                            bg=COLOR_FRAME, fg=COLOR_ACCENT, relief=tk.FLAT,
                            padx=8, cursor="hand2", command=_add_row)
        add_btn.pack(anchor=tk.W, pady=(2, 0))

        return {"frame": outer, "rows": kv_rows}

    # ──────────────────────────────────────────────
    #  引擎详情配置窗口（双击或点 ⚙ 打开）
    # ──────────────────────────────────────────────

    def _show_engine_detail_window(self, mgr: EngineManager, engine_name: str, parent_win):
        """弹出引擎详情配置窗口"""
        engine = mgr.get_by_name(engine_name)
        if engine is None:
            return

        win = tk.Toplevel(parent_win)
        win.title(f"⚙ 引擎配置 — {engine.name}")
        win.geometry("520x640")
        win.configure(bg=COLOR_FRAME)
        win.resizable(False, False)
        win.transient(parent_win)
        win.grab_set()

        win.update_idletasks()
        x = parent_win.winfo_x() + (parent_win.winfo_width() - 520) // 2
        y = parent_win.winfo_y() + (parent_win.winfo_height() - 640) // 2
        win.geometry(f"+{x}+{y}")

        is_builtin = mgr.is_builtin(engine.name)

        # ── 可滚动内容 ──
        canvas = tk.Canvas(win, bg=COLOR_FRAME, bd=0, highlightthickness=0)
        scroll = tk.Scrollbar(win, orient=tk.VERTICAL, command=canvas.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        canvas.configure(yscrollcommand=scroll.set)

        content = tk.Frame(canvas, bg=COLOR_FRAME)
        canvas.create_window((0, 0), window=content, anchor=tk.NW, tags="content")

        def _configure_content(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        content.bind("<Configure>", _configure_content)

        # ── 标题 ──
        tk.Label(content, text=f"⚙ {engine.name} 配置",
                 font=FONT_TITLE, bg=COLOR_FRAME, fg=COLOR_TEXT,
                 ).pack(anchor=tk.W, padx=16, pady=(16, 8))

        # ── 表单区域 ──
        form_frame = tk.Frame(content, bg=COLOR_FRAME)
        form_frame.pack(fill=tk.X, padx=16, pady=(0, 8))

        row_opts = {"fill": tk.X, "pady": (0, 6)}
        entry_opts = {
            "font": FONT_DEFAULT, "bg": "white", "fg": COLOR_TEXT,
            "relief": tk.FLAT, "bd": 1,
            "highlightthickness": 1, "highlightcolor": COLOR_ACCENT,
            "highlightbackground": COLOR_BORDER,
        }

        def _make_row(label_text, row_idx):
            """创建一行：label + entry"""
            f = tk.Frame(form_frame, bg=COLOR_FRAME)
            f.pack(**row_opts)
            tk.Label(f, text=label_text, font=FONT_BOLD, bg=COLOR_FRAME,
                     fg=COLOR_TEXT, width=14, anchor=tk.W).pack(side=tk.LEFT)
            return f

        # 名称（仅自定义引擎可改）
        name_var = tk.StringVar(value=engine.name)
        name_frame = _make_row("名称", 1)
        name_entry = tk.Entry(name_frame, textvariable=name_var, **entry_opts)
        name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3)
        if is_builtin:
            name_entry.config(state="readonly", readonlybackground="white")

        # API 地址
        api_url_var = tk.StringVar(value=engine.api_url)
        url_frame = _make_row("API 地址", 2)
        tk.Entry(url_frame, textvariable=api_url_var, **entry_opts,
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3)

        # API Key
        api_key_var = tk.StringVar(value=engine.api_key)
        key_frame = _make_row("API Key", 3)
        key_entry = tk.Entry(key_frame, textvariable=api_key_var, **entry_opts,
                             show="*" if engine.api_key else "")
        key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3)
        # 显示/隐藏按钮
        def _toggle_key_show():
            if key_entry.cget("show") == "*":
                key_entry.config(show="")
                key_btn.config(text="🙈")
            else:
                key_entry.config(show="*")
                key_btn.config(text="👁")
        key_btn = tk.Button(key_frame, text="👁", font=FONT_SMALL,
                            bg=COLOR_FRAME, fg=COLOR_TEXT, relief=tk.FLAT,
                            padx=4, cursor="hand2", command=_toggle_key_show)
        key_btn.pack(side=tk.LEFT, padx=(4, 0))

        # 请求间隔
        delay_var = tk.StringVar(value=str(engine.request_delay))
        delay_frame = _make_row("请求间隔(秒)", 4)
        tk.Entry(delay_frame, textvariable=delay_var, **entry_opts, width=10,
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3)

        # 超时
        timeout_var = tk.StringVar(value=str(engine.timeout))
        timeout_frame = _make_row("超时(秒)", 5)
        tk.Entry(timeout_frame, textvariable=timeout_var, **entry_opts, width=10,
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3)

        # 长期限额
        long_limit_var = tk.StringVar(value=str(getattr(engine, "long_limit", 100) or 100))
        long_frame = _make_row("长期限额(次)", 6)
        tk.Entry(long_frame, textvariable=long_limit_var, **entry_opts, width=10,
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3)
        tk.Label(long_frame, text="(0=无限制)", font=FONT_SMALL,
                 bg=COLOR_FRAME, fg=COLOR_TEXT_SECONDARY).pack(side=tk.LEFT, padx=(6, 0))

        # 短期限额
        short_limit_var = tk.StringVar(value=str(getattr(engine, "short_limit", 4) or 4))
        short_frame = _make_row("短期限额(次)", 7)
        tk.Entry(short_frame, textvariable=short_limit_var, **entry_opts, width=10,
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3)
        tk.Label(short_frame, text="(0=无限制)", font=FONT_SMALL,
                 bg=COLOR_FRAME, fg=COLOR_TEXT_SECONDARY).pack(side=tk.LEFT, padx=(6, 0))

        # 长期窗口(秒)
        long_window_var = tk.StringVar(value=str(getattr(engine, "long_window", 86400)))
        long_win_frame = _make_row("长期窗口(秒)", 8)
        tk.Entry(long_win_frame, textvariable=long_window_var, **entry_opts, width=10,
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3)
        tk.Label(long_win_frame, text=f"(默认 {86400} = 24h)", font=FONT_SMALL,
                 bg=COLOR_FRAME, fg=COLOR_TEXT_SECONDARY).pack(side=tk.LEFT, padx=(6, 0))

        # 短期窗口(秒)
        short_window_var = tk.StringVar(value=str(getattr(engine, "short_window", 30)))
        short_win_frame = _make_row("短期窗口(秒)", 9)
        tk.Entry(short_win_frame, textvariable=short_window_var, **entry_opts, width=10,
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3)
        tk.Label(short_win_frame, text=f"(默认 {30} = 30s)", font=FONT_SMALL,
                 bg=COLOR_FRAME, fg=COLOR_TEXT_SECONDARY).pack(side=tk.LEFT, padx=(6, 0))

        # ── 自定义 Headers ──
        sep1 = tk.Frame(content, height=1, bg=COLOR_BORDER)
        sep1.pack(fill=tk.X, padx=16, pady=(4, 8))

        tk.Label(content, text="自定义请求头 (Headers):", font=FONT_BOLD,
                 bg=COLOR_FRAME, fg=COLOR_TEXT,
                 ).pack(anchor=tk.W, padx=16, pady=(0, 4))

        headers_frame = tk.Frame(content, bg=COLOR_FRAME)
        headers_frame.pack(fill=tk.X, padx=16, pady=(0, 6))

        # 键值对编辑列表
        headers_items = self._build_kv_editor(headers_frame, engine.headers.copy())
        headers_items["frame"].pack(fill=tk.X)

        # ── 自定义 Params ──
        sep2 = tk.Frame(content, height=1, bg=COLOR_BORDER)
        sep2.pack(fill=tk.X, padx=16, pady=(4, 8))

        tk.Label(content, text="自定义查询参数 (Params):", font=FONT_BOLD,
                 bg=COLOR_FRAME, fg=COLOR_TEXT,
                 ).pack(anchor=tk.W, padx=16, pady=(0, 4))

        params_frame = tk.Frame(content, bg=COLOR_FRAME)
        params_frame.pack(fill=tk.X, padx=16, pady=(0, 6))

        params_items = self._build_kv_editor(params_frame, engine.params.copy())
        params_items["frame"].pack(fill=tk.X)

        # ── 反爬绕过设置 ──
        sep3 = tk.Frame(content, height=1, bg=COLOR_BORDER)
        sep3.pack(fill=tk.X, padx=16, pady=(4, 8))

        cw_frame = tk.Frame(content, bg=COLOR_FRAME)
        cw_frame.pack(fill=tk.X, padx=16, pady=(0, 6))

        bypass_cfw_var = tk.BooleanVar(value=getattr(engine, "bypass_cfw", False))
        tk.Checkbutton(
            cw_frame,
            text="🌩 启用 Cloudflare 反爬绕过（仅 Ascii2D 生效）",
            variable=bypass_cfw_var,
            font=FONT_DEFAULT,
            bg=COLOR_FRAME, fg=COLOR_TEXT,
            selectcolor=COLOR_FRAME,
            activebackground=COLOR_FRAME,
            activeforeground=COLOR_TEXT,
            cursor="hand2",
        ).pack(anchor=tk.W, pady=(4, 4))

        # ── 保存/取消按钮 ──
        btn_frame = tk.Frame(content, bg=COLOR_FRAME)
        btn_frame.pack(fill=tk.X, padx=16, pady=(12, 16))

        def _save_engine_config():
            """保存引擎配置"""
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning("提示", "引擎名称不能为空", parent=win)
                return

            # 如果是自定义引擎且改名，检查冲突
            if name != engine.name and mgr.get_by_name(name) is not None:
                messagebox.showwarning("提示", f"引擎名称已存在: {name}", parent=win)
                return

            try:
                delay = float(delay_var.get().strip())
                timeout = int(timeout_var.get().strip())
                long_limit = int(long_limit_var.get().strip())
                short_limit = int(short_limit_var.get().strip())
                long_window = int(long_window_var.get().strip())
                short_window = int(short_window_var.get().strip())
            except ValueError:
                messagebox.showwarning("提示", "请求间隔、超时、限额和窗口时长必须为数字", parent=win)
                return

            # 收集 headers
            new_headers = {}
            for row_data in headers_items["rows"]:
                k = row_data["key"].get().strip()
                v = row_data["val"].get().strip()
                if k:
                    new_headers[k] = v

            # 收集 params
            new_params = {}
            for row_data in params_items["rows"]:
                k = row_data["key"].get().strip()
                v = row_data["val"].get().strip()
                if k:
                    new_params[k] = v

            # 先处理改名（使用 update_config 的 name 参数即可，无需重新获取）
            if name != engine.name and not is_builtin:
                # 删除旧名，用新名创建新记录（保留原配置）
                engine_name_for_update = name
                mgr.remove(engine.name)
                mgr.add(name, enabled=engine.enabled)
            else:
                engine_name_for_update = engine.name

            # 更新配置（改名已由上面的 remove+add 处理，此处只更新其他字段）
            mgr.update_config(
                engine_name_for_update,
                api_url=api_url_var.get().strip(),
                api_key=api_key_var.get().strip(),
                request_delay=delay,
                timeout=timeout,
                long_limit=long_limit,
                short_limit=short_limit,
                long_window=long_window,
                short_window=short_window,
                headers=new_headers,
                params=new_params,
                bypass_cfw=bypass_cfw_var.get(),
            )

            self._log_success(f"已保存引擎配置: {name}")
            self._refresh_engine_list(self._engine_win)
            win.destroy()

        tk.Button(btn_frame, text="💾 保存", font=FONT_BOLD,
                  bg=COLOR_ACCENT, fg="white", relief=tk.FLAT,
                  padx=24, cursor="hand2",
                  command=_save_engine_config).pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(btn_frame, text="↩ 取消", font=FONT_DEFAULT,
                  bg=COLOR_FRAME, fg=COLOR_TEXT, relief=tk.FLAT,
                  padx=16, cursor="hand2",
                  command=win.destroy).pack(side=tk.LEFT)

    # ── 批量搜索窗口 ────────────────────────────

    def _show_batch_window(self):
        """弹出批量搜索窗口"""
        win = tk.Toplevel(self.root)
        win.title("📁 批量搜索")
        win.geometry("600x450")
        win.configure(bg=COLOR_FRAME)
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        # 居中
        win.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 600) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 450) // 2
        win.geometry(f"+{x}+{y}")

        # ── 目录选择 ──
        path_frame = tk.Frame(win, bg=COLOR_FRAME)
        path_frame.pack(fill=tk.X, padx=16, pady=(16, 8))

        tk.Label(path_frame, text="图片目录:", font=FONT_BOLD, bg=COLOR_FRAME, fg=COLOR_TEXT).pack(
            side=tk.LEFT
        )

        dir_var = tk.StringVar()
        dir_entry = tk.Entry(
            path_frame,
            textvariable=dir_var,
            font=FONT_DEFAULT,
            bg="white",
            fg=COLOR_TEXT,
            relief=tk.FLAT,
            bd=1,
            highlightthickness=1,
            highlightcolor=COLOR_ACCENT,
            highlightbackground=COLOR_BORDER,
        )
        dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6), ipady=4)

        def _browse_dir():
            d = filedialog.askdirectory(title="选择图片目录")
            if d:
                dir_var.set(d)

        tk.Button(
            path_frame,
            text="📂 浏览",
            font=FONT_DEFAULT,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT,
            relief=tk.FLAT,
            padx=12,
            cursor="hand2",
            command=_browse_dir,
        ).pack(side=tk.LEFT)

        # ── 统计信息 ──
        info_frame = tk.Frame(win, bg=COLOR_FRAME)
        info_frame.pack(fill=tk.X, padx=16, pady=(4, 8))

        self._batch_label_info = tk.Label(
            info_frame,
            text="选择目录后自动统计图片数量",
            font=FONT_DEFAULT,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT_SECONDARY,
            anchor=tk.W,
        )
        self._batch_label_info.pack(fill=tk.X)

        # ── 进度条 ──
        progress_frame = tk.Frame(win, bg=COLOR_FRAME)
        progress_frame.pack(fill=tk.X, padx=16, pady=(4, 8))

        self._batch_progress = ttk.Progressbar(
            progress_frame,
            orient=tk.HORIZONTAL,
            length=500,
            mode="determinate",
        )
        self._batch_progress.pack(fill=tk.X)

        self._batch_label_progress = tk.Label(
            progress_frame,
            text="",
            font=FONT_DEFAULT,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT_SECONDARY,
            anchor=tk.W,
        )
        self._batch_label_progress.pack(fill=tk.X, pady=(4, 0))

        # ── 当前结果 ──
        result_frame = tk.Frame(win, bg=COLOR_FRAME)
        result_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 8))
        result_frame.configure(highlightbackground=COLOR_BORDER, highlightthickness=1)

        scroll_batch = tk.Scrollbar(result_frame)
        scroll_batch.pack(side=tk.RIGHT, fill=tk.Y)

        self._batch_text = tk.Text(
            result_frame,
            font=FONT_MONO,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT,
            relief=tk.FLAT,
            bd=0,
            height=10,
            wrap=tk.WORD,
            yscrollcommand=scroll_batch.set,
        )
        self._batch_text.pack(fill=tk.BOTH, expand=True)
        scroll_batch.config(command=self._batch_text.yview)

        # ── 控制按钮 ──
        btn_frame = tk.Frame(win, bg=COLOR_FRAME)
        btn_frame.pack(fill=tk.X, padx=16, pady=(0, 16))

        # 增量 CSV 文件路径
        self._batch_csv_path = None

        def _save_partial_results():
            """保存已收集的中间结果到 CSV"""
            if hasattr(self, '_batch_partial_log') and self._batch_partial_log and self._batch_csv_path:
                try:
                    fieldnames = [
                        "file", "status", "source", "similarity",
                        "pixiv_id", "pixiv_image_id",
                        "artist", "artist_id", "title",
                        "ext_url", "error",
                    ]
                    with open(self._batch_csv_path, "w", encoding="utf-8-sig", newline="") as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        for entry in self._batch_partial_log:
                            row = {k: entry.get(k, "") for k in fieldnames}
                            if row.get("similarity") and isinstance(row["similarity"], (int, float)):
                                row["similarity"] = f"{row['similarity']:.1f}%"
                            writer.writerow(row)
                    return True
                except Exception:
                    return False
            return False

        def _on_batch_close():
            """批量窗口关闭时：停止搜索 + 保存中间结果"""
            if self._batch_running:
                self._batch_cancel = True
                saved = _save_partial_results()
                if saved:
                    self._log_info(f"批量搜索已中断，中间结果已保存到: {self._batch_csv_path}")
            self._batch_running = False
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", _on_batch_close)

        def _start_batch():
            nonlocal browse_btn, start_btn
            directory = dir_var.get().strip()
            if not directory:
                messagebox.showwarning("提示", "请先选择图片目录", parent=win)
                return
            dir_path = Path(directory)
            if not dir_path.is_dir():
                messagebox.showwarning("提示", "目录不存在", parent=win)
                return

            if self._batch_running:
                # 点击停止：先保存中间结果
                self._batch_cancel = True
                saved = _save_partial_results()
                if saved:
                    self._batch_log(f"⏹ 已停止，部分结果已保存到: {self._batch_csv_path}", COLOR_WARN)
                else:
                    self._batch_log("⏹ 已停止", COLOR_WARN)
                return

            self._batch_running = True
            self._batch_cancel = False
            self._batch_text.delete(1.0, tk.END)
            self._batch_progress["value"] = 0
            self._batch_partial_log = []
            self._batch_csv_path = str(dir_path / "search_results.csv")

            start_btn.config(text="⏹ 停止", bg=COLOR_ERROR)
            browse_btn.config(state=tk.DISABLED)

            # 在新线程中运行
            thread = threading.Thread(
                target=self._batch_thread,
                args=(str(dir_path), win),
                daemon=True,
            )
            thread.start()

        start_btn = tk.Button(
            btn_frame,
            text="▶ 开始",
            font=FONT_BOLD,
            bg=COLOR_ACCENT,
            fg="white",
            relief=tk.FLAT,
            padx=24,
            cursor="hand2",
            command=_start_batch,
        )
        start_btn.pack(side=tk.LEFT)

        browse_btn = tk.Button(
            btn_frame,
            text="📂 浏览",
            font=FONT_DEFAULT,
            bg=COLOR_FRAME,
            fg=COLOR_TEXT,
            relief=tk.FLAT,
            padx=12,
            cursor="hand2",
            command=_browse_dir,
        )
        browse_btn.pack(side=tk.LEFT, padx=(6, 0))

        # 保存批量引用
        self._batch_win_ref = win
        self._batch_start_btn = start_btn
        self._batch_browse_btn = browse_btn

    def _batch_log(self, text, color=None):
        """向批量窗口追加日志"""
        self._batch_text.insert(tk.END, text + "\n")
        if color:
            start = self._batch_text.index("end-2l")
            end = self._batch_text.index("end-1l")
            self._batch_text.tag_add(color, start, end)
            self._batch_text.tag_configure(color, foreground=color)
        self._batch_text.see(tk.END)

    def _batch_thread(self, dir_path_str: str, win):
        """批量搜索线程"""
        from main import search_image as do_search
        from imgsearch.config import get as cfg_get

        dir_path = Path(dir_path_str)
        delay = cfg_get("request_delay", 8.0)

        # 收集图片文件
        image_files = []
        for ext in [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"]:
            image_files.extend(dir_path.glob(f"*{ext}"))
            image_files.extend(dir_path.glob(f"*{ext.upper()}"))

        total = len(image_files)
        if total == 0:
            self.root.after(0, lambda: self._batch_finished(0, 0, win, dir_path))
            return

        self.root.after(0, lambda: self._batch_label_info.config(
            text=f"📁 共找到 {total} 张图片"
        ))
        self.root.after(0, lambda: self._batch_progress.config(maximum=total))

        success = 0
        fail = 0
        self._batch_partial_log = []

        for i, img_path in enumerate(image_files, 1):
            if self._batch_cancel:
                self.root.after(0, lambda: self._batch_log("⏹ 用户已停止", COLOR_WARN))
                # 停止时先将已完成的部分保存
                self.root.after(0, self._incremental_save_csv)
                break

            file_name = img_path.name
            self.root.after(0, lambda idx=i, name=file_name: self._batch_label_progress.config(
                text=f"进度: [{idx}/{total}] {name}"
            ))
            self.root.after(0, lambda: self._batch_progress.step(1))

            try:
                results = do_search(str(img_path))
                if results:
                    success += 1
                    best = results[0]
                    log_entry = {
                        "file": str(img_path),
                        "status": "success",
                        "source": best.source,
                        "similarity": best.similarity,
                        "pixiv_id": best.pixiv_id,
                        "pixiv_image_id": best.pixiv_image_id(),
                        "artist": best.artist,
                        "artist_id": best.artist_id,
                        "title": best.title,
                        "ext_url": best.ext_urls[0] if best.ext_urls else None,
                        "error": None,
                    }
                    msg = f"✅ [{i}/{total}] {file_name} → {best.pixiv_image_id() or best.pixiv_id or '匹配'} ({best.similarity:.1f}%)"
                    self.root.after(0, lambda m=msg, c=COLOR_SUCCESS: self._batch_log(m, c))
                else:
                    fail += 1
                    log_entry = {
                        "file": str(img_path), "status": "no_match",
                        "source": None, "similarity": None,
                        "pixiv_id": None, "pixiv_image_id": None,
                        "artist": None, "artist_id": None, "title": None,
                        "ext_url": None, "error": None,
                    }
                    msg = f"❌ [{i}/{total}] {file_name} → 无匹配"
                    self.root.after(0, lambda m=msg, c=COLOR_WARN: self._batch_log(m, c))

                self._batch_partial_log.append(log_entry)
                # 每处理完一张图，增量保存 CSV
                self.root.after(0, self._incremental_save_csv)

            except Exception as e:
                fail += 1
                log_entry = {
                    "file": str(img_path), "status": "error",
                    "source": None, "similarity": None,
                    "pixiv_id": None, "pixiv_image_id": None,
                    "artist": None, "artist_id": None, "title": None,
                    "ext_url": None, "error": str(e),
                }
                msg = f"⚠️ [{i}/{total}] {file_name} → 错误: {str(e)[:50]}"
                self.root.after(0, lambda m=msg, c=COLOR_ERROR: self._batch_log(m, c))
                self._batch_partial_log.append(log_entry)
                # 出错也增量保存
                self.root.after(0, self._incremental_save_csv)

            # 延迟
            if i < total and not self._batch_cancel:
                time.sleep(delay)

        # 完成
        self.root.after(0, lambda: self._batch_finished(success, fail, win, dir_path))

    def _incremental_save_csv(self):
        """增量保存 CSV（每处理一张图调用一次，覆盖写入以保证数据完整）"""
        if not self._batch_partial_log or not self._batch_csv_path:
            return
        try:
            fieldnames = [
                "file", "status", "source", "similarity",
                "pixiv_id", "pixiv_image_id",
                "artist", "artist_id", "title",
                "ext_url", "error",
            ]
            with open(self._batch_csv_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for entry in self._batch_partial_log:
                    row = {k: entry.get(k, "") for k in fieldnames}
                    if row.get("similarity") and isinstance(row["similarity"], (int, float)):
                        row["similarity"] = f"{row['similarity']:.1f}%"
                    writer.writerow(row)
        except Exception:
            pass  # 增量保存静默失败，最终保存还会再试

    def _batch_finished(self, success, fail, win, dir_path=None):
        """批量搜索完成回调"""
        self._batch_running = False

        if self._batch_start_btn:
            self._batch_start_btn.config(text="▶ 开始", bg=COLOR_ACCENT)
        if self._batch_browse_btn:
            self._batch_browse_btn.config(state=tk.NORMAL)

        total = success + fail
        self._batch_label_progress.config(text=f"完成: ✅ {success} 成功 | ❌ {fail} 失败 | 📁 {total} 总计")

        # 最终保存 CSV（覆盖增量写入，确保完整）
        if self._batch_partial_log and dir_path:
            csv_path = dir_path / "search_results.csv"
            try:
                fieldnames = [
                    "file", "status", "source", "similarity",
                    "pixiv_id", "pixiv_image_id",
                    "artist", "artist_id", "title",
                    "ext_url", "error",
                ]
                with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for entry in self._batch_partial_log:
                        row = {k: entry.get(k, "") for k in fieldnames}
                        if row.get("similarity") and isinstance(row["similarity"], (int, float)):
                            row["similarity"] = f"{row['similarity']:.1f}%"
                        writer.writerow(row)
                self._batch_log(f"\n📊 CSV 已保存: {csv_path}", COLOR_SUCCESS)
            except Exception as e:
                self._batch_log(f"⚠️ 保存 CSV 失败: {e}", COLOR_ERROR)

    # ── 拖拽支持 ────────────────────────────────

    # Windows 下 tkinter 原生拖拽支持有限，
    # 可以通过右键粘贴路径方式替代


def main():
    """启动 GUI"""
    gui = ImageTraceGUI()
    gui.run()


if __name__ == "__main__":
    main()
