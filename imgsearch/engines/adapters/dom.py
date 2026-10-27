"""
从 HTML 里按「选择器@属性」取值

语法（比完整 CSS 选择器语法简单，够用）::

    "td.image a"            取这个元素的**文本**
    "td.image a@href"       取 href 属性
    "td.image img@src"      取 src 属性
    "td.match@text"         显式取文本

⚠️ 用 ``rsplit("@", 1)`` 拆分：CSS 属性选择器里也可能出现 ``@``（少见），
从右边拆更安全。
"""

from typing import Any, List, Optional

WRAPPER = "html.parser"


def parse_html(text: str):
    """把 HTML 字符串解析成 soup（BeautifulSoup 未安装时抛 ImportError）"""
    from bs4 import BeautifulSoup
    return BeautifulSoup(text, "lxml")


def scoped(soup, selector: str):
    """
    按容器选择器缩小范围。

    选择器为空 → 返回整个 soup（站点没有明显容器时用）。
    """
    if not selector:
        return soup
    try:
        found = soup.select_one(selector)
    except Exception:                                     # noqa: BLE001
        found = None
    return found


def select_all(root, selector: str) -> List[Any]:
    if root is None or not selector:
        return []
    try:
        return list(root.select(selector))
    except Exception:                                     # noqa: BLE001
        return []


def _target(node, selector: str):
    """
    取范围内的第一个元素。

    特殊选择器 ``:self`` / ``.`` 表示**节点自己** ——
    有些站点的相似度就写在整行的文本里（IQDB 就是），没有单独的元素可指。
    """
    if selector in (":self", "."):
        return node
    try:
        return node.select_one(selector)
    except Exception:                                     # noqa: BLE001
        return None


def split_spec(spec: str):
    """``"td a@href"`` → ("td a", "href")；没有 @ 时属性为 text"""
    if not spec:
        return "", "text"
    if "@" in spec:
        selector, _, attr = spec.rpartition("@")
        return selector.strip(), (attr.strip() or "text")
    return spec.strip(), "text"


def extract(node, spec: str) -> str:
    """在 node 范围内按 spec 取第一处的值（文本或属性）"""
    for candidate in (spec or "").split("|"):
        selector, attr = split_spec(candidate.strip())
        if not selector:
            continue
        value = node_value(_target(node, selector), attr)
        if value:
            return value
    return ""



def extract_links(node, spec: str) -> List[str]:
    """
    收集所有候选（``|`` 分隔）里出现的链接，去重保序。

    ⚠️ 不能先用 _target 取第一个再往里找 —— 那样会在已经取到的
    <a> 元素内部再搜 `td.image a`，永远是空的。
    """
    out: List[str] = []
    for candidate in (spec or "").split("|"):
        selector, attr = split_spec(candidate.strip())
        if not selector:
            continue
        if selector in (":self", "."):
            value = node_value(node, attr)
            if value:
                out.append(value)
            continue
        for found in select_all(node, selector):
            value = node_value(found, attr)
            if value:
                out.append(value)

    seen, unique = set(), []
    for url in out:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def node_value(found, attr: str) -> str:
    """从一个元素上取值"""
    if found is None:
        return ""
    if attr in ("", "text"):
        try:
            return found.get_text(strip=True)
        except Exception:                                 # noqa: BLE001
            return ""
    try:
        value: Optional[str] = found.get(attr)
    except Exception:                                     # noqa: BLE001
        return ""
    return (value or "").strip()
