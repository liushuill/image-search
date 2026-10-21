"""
新建引擎向导

**给用户用的路**：不写代码，选 JSON 或 HTML，填一张映射表就能接一个新站点。

设计要点：

1. **两部分表单**
   - 顶部：名称 / 类型 / 站点地址 / 接口路径（这些是「这是什么站点」）
   - 下面：适配器的字段映射（原样复用 :class:`SchemaForm`，
     它已经会按 schema 生成控件、写好帮助文本、处理类型转换）
   - 限流、代理、超时这些先不给 —— 创建后在「引擎」页慢慢调，
     向导只负责让新引擎**先能跑起来**

2. **「测试这个引擎」必须能看到原始响应**
   没有它，用户根本判断不了「是路径写错了，还是站点没返回」——
   这是适配器最难排查的一类问题。所以测试会先抓一份响应原文，
   显示前 800 字，再显示解析出几条、第一条各字段是什么。

3. **测试用的是真实请求**
   会消耗该站点的配额（SauceNAO 一次就是 1/100）。界面上要写明。
"""

from pathlib import Path

from PySide6 import QtWidgets

from imgsearch.engines.adapters.generic_html import GenericHtml
from imgsearch.engines.adapters.generic_json import GenericJson
from imgsearch.engines.schema import Schema
from imgsearch.engines.store import get_store
from imgsearch_gui.widgets.schema_form import SchemaForm

# 向导里**只放这些**：把「让新引擎跑起来」必需的东西挑出来。
#
# 为什么用白名单：
#   适配器 schema 有 45 个字段（限流、反爬、鉴权、各种 ID 映射…），
#   全塞进向导会把人吓退。向导的职责是「先跑通」，
#   精细项（限流、代理、额外 ID 字段）创建后在「引擎」页慢慢调。
_WIZARD_KEYS = {
    # 请求（endpoint 由顶部的「接口路径」填，这里不重复）
    "method", "image_field",
    # 结果定位
    "results_path", "container_selector", "row_selector",
    # 相似度
    "similarity_scale", "field_similarity",
    # 常用字段映射
    "field_artist", "field_title", "field_material", "field_pixiv_id",
    "field_urls", "field_highres", "field_thumbnail", "field_detail",
    # 收窄（结果页常有噪声）
    "links_from_hosts", "dedupe_by",
}

_TYPES = (
    ("json", "JSON（站点返回 JSON）", GenericJson),
    ("html", "HTML（站点返回网页）", GenericHtml),
)


def _mappable_schema(cls) -> Schema:
    """从适配器的 schema 里挑出向导要展示的字段（白名单，保持原顺序）"""
    return Schema(*[f for f in cls.CONFIG_SCHEMA if f.key in _WIZARD_KEYS])


class NewEngineDialog(QtWidgets.QDialog):
    """新建一个「配置驱动」的引擎"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建引擎")
        self.setMinimumSize(720, 720)
        self.created_name: str = ""
        self._form: SchemaForm | None = None
        self._last_raw: str = ""

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 12)
        outer.setSpacing(10)

        title = QtWidgets.QLabel("新建引擎")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        hint = QtWidgets.QLabel(
            "选一个类型，填上站点地址和字段映射，就能接一个新站点 —— 不需要写代码。\n"
            "⚠️「测试这个引擎」会发出真实请求，可能消耗该站点的额度。"
        )
        hint.setObjectName("PageHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        # ── 基本信息的卡片 ──
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        form = QtWidgets.QFormLayout(card)
        form.setContentsMargins(14, 12, 14, 12)
        form.setSpacing(8)

        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("英文，如 mybooru（会作为配置里的名字）")
        form.addRow("名称", self.name_edit)

        self.type_combo = QtWidgets.QComboBox()
        for key, label, _cls in _TYPES:
            self.type_combo.addItem(label, key)
        self.type_combo.currentIndexChanged.connect(self._rebuild_form)
        form.addRow("类型", self.type_combo)

        self.url_edit = QtWidgets.QLineEdit()
        self.url_edit.setPlaceholderText("https://booru.example")
        form.addRow("站点地址", self.url_edit)

        self.endpoint_edit = QtWidgets.QLineEdit()
        self.endpoint_edit.setPlaceholderText("如 /posts.json（留空 = 就用站点地址）")
        form.addRow("接口路径", self.endpoint_edit)

        outer.addWidget(card)

        # ── 字段映射（滚动区）──
        head = QtWidgets.QLabel("接口与字段映射")
        head.setObjectName("SectionTitle")
        outer.addWidget(head)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._form_host = QtWidgets.QWidget()
        self._form_layout = QtWidgets.QVBoxLayout(self._form_host)
        self._form_layout.setContentsMargins(0, 0, 8, 0)
        self._form_layout.setSpacing(0)
        self.scroll.setWidget(self._form_host)
        outer.addWidget(self.scroll, 1)

        # ── 测试区 ──
        test_card = QtWidgets.QFrame()
        test_card.setObjectName("Card")
        test_lay = QtWidgets.QVBoxLayout(test_card)
        test_lay.setContentsMargins(14, 10, 14, 10)
        test_lay.setSpacing(8)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("用这张图测试："))
        self.image_edit = QtWidgets.QLineEdit()
        self.image_edit.setPlaceholderText("选一张图片，点右边「测试」")
        row.addWidget(self.image_edit, 1)
        pick = QtWidgets.QPushButton("选择…")
        pick.clicked.connect(self._pick_image)
        row.addWidget(pick)
        self.test_btn = QtWidgets.QPushButton("测试这个引擎")
        self.test_btn.clicked.connect(self._test)
        row.addWidget(self.test_btn)
        test_lay.addLayout(row)

        self.test_output = QtWidgets.QPlainTextEdit()
        self.test_output.setReadOnly(True)
        self.test_output.setMinimumHeight(190)
        self.test_output.setPlaceholderText(
            "点「测试这个引擎」后，这里会显示\n"
            "  · 请求的地址与 HTTP 结果\n"
            "  · 响应原文（前 800 字）\n"
            "  · 解析出几条、第一条各字段是什么\n"
            "看不到原文的话，就没法判断是路径写错了还是站点没返回。"
        )
        test_lay.addWidget(self.test_output, 1)
        outer.addWidget(test_card, 1)

        # ── 底部按钮 ──
        bar = QtWidgets.QHBoxLayout()
        bar.addStretch(1)
        cancel = QtWidgets.QPushButton("取消")
        cancel.clicked.connect(self.reject)
        bar.addWidget(cancel)
        self.create_btn = QtWidgets.QPushButton("创建")
        self.create_btn.setDefault(True)
        self.create_btn.clicked.connect(self._create)
        bar.addWidget(self.create_btn)
        outer.addLayout(bar)

        self._rebuild_form()

    # ── 类型切换 ────────────────────────────────

    def _current_class(self):
        key = self.type_combo.currentData()
        return next(cls for k, _label, cls in _TYPES if k == key)

    def _rebuild_form(self) -> None:
        """切换类型时重建映射表单（JSON 与 HTML 的字段说明不同）"""
        if self._form is not None:
            self._form.setParent(None)
            self._form.deleteLater()
        cls = self._current_class()
        self._form = SchemaForm(_mappable_schema(cls), {}, engine_name="")
        self._form_layout.addWidget(self._form)
        self.test_output.clear()

    # ── 收集结果 ────────────────────────────────

    def _collect(self) -> dict:
        values = dict(self._form.values() if self._form else {})
        values["api_url"] = self.url_edit.text().strip()
        values["endpoint"] = self.endpoint_edit.text().strip()
        return values

    def _pick_image(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择一张测试图片", "",
            "图片 (*.jpg *.jpeg *.png *.webp *.gif *.bmp)")
        if path:
            self.image_edit.setText(path)

    # ── 测试 ────────────────────────────────────

    def _test(self) -> None:
        image = self.image_edit.text().strip()
        if not image or not Path(image).is_file():
            QtWidgets.QMessageBox.information(
                self, "先选一张图", "测试需要一张真实的图片文件。")
            return

        cls = self._current_class()
        try:
            engine = cls(**self._collect())
        except Exception as e:                            # noqa: BLE001
            self._show(f"🔴 配置有误，引擎构造失败：\n{e}")
            return

        self.test_btn.setEnabled(False)
        self._show("正在请求…（真实请求，可能需要几秒）")
        QtWidgets.QApplication.processEvents()
        try:
            # 只请求一次：先拿原文，再解析同一份原文
            raw = engine._request(image_path=image)      # type: ignore[attr-defined]
            self._last_raw = raw or ""
            lines = [f"✅ 请求成功，响应 {len(self._last_raw)} 字"]
            lines.append(f"地址：{engine._endpoint()}")   # type: ignore[attr-defined]
            lines.append("")
            lines.append("── 响应原文（前 800 字）──")
            lines.append(self._last_raw[:800])
            lines.append("")
            try:
                results = engine._parse(self._last_raw)  # type: ignore[attr-defined]
            except Exception as e:                        # noqa: BLE001
                lines.append(f"🔴 解析失败：{e}")
                self._show("\n".join(lines))
                return

            lines.append(f"── 解析结果：{len(results)} 条 ──")
            if results:
                first = results[0]
                lines.append(f"  相似度：{first.similarity}")
                lines.append(f"  画师：{first.artist or '—'}")
                lines.append(f"  标题：{first.title or '—'}")
                lines.append(f"  作品：{first.material or '—'}")
                lines.append(f"  Pixiv ID：{first.pixiv_id or '—'}")
                lines.append(f"  站点 ID：{first.danbooru_id or first.gelbooru_id or '—'}")
                lines.append(f"  来源链接：{' / '.join(first.ext_urls) or '—'}")
                lines.append(f"  缩略图：{first.thumbnail or '—'}")
                lines.append("")
                lines.append("若上面有「—」，说明对应字段的映射还没填对。")
            else:
                lines.append(
                    "一条都没解析出来。常见原因：\n"
                    "  · 结果数组路径 / 单条结果选择器不对\n"
                    "  · 相似度路径没填（量纲不是 none 时必须有）\n"
                    "  · 站点确实没有匹配结果")
            self._show("\n".join(lines))
        except Exception as e:                            # noqa: BLE001
            self._show(f"🔴 请求失败：{e}")
        finally:
            self.test_btn.setEnabled(True)

    def _show(self, text: str) -> None:
        self.test_output.setPlainText(text)
        QtWidgets.QApplication.processEvents()

    # ── 创建 ────────────────────────────────────

    def _create(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "缺少名称", "请先给引擎起个名字。")
            return
        cls = self._current_class()
        store = get_store()
        if store.get(name) is not None:
            QtWidgets.QMessageBox.warning(
                self, "名称重复", f"已经有一个叫「{name}」的引擎了，换个名字。")
            return
        try:
            store.add(name, module_path=cls.__module__, class_name=cls.__name__)
            store.update_settings(name, self._collect())
        except Exception as e:                            # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "创建失败", str(e))
            return

        self.created_name = name
        self.accept()
