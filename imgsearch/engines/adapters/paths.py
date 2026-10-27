"""
从 JSON 里按「点号路径」取值

语法（够用且不易写错）::

    "results"              取第一层
    "header.similarity"    嵌套取值
    "data.ext_urls"        取出数组
    "results[0].data"      数组下标
    "edges[?isMain=true].node.name"   取数组里第一个 isMain 为真的元素
    ""                     空串 = 对象本身

严格说这不是完整 JSONPath —— 故意不支持通配、过滤、递归下降：
**映射表是给人看的，语法越简单越好。** 真要复杂逻辑，写一个 Python 引擎文件。
"""

from typing import Any, List

_MISSING = object()


def dig(data: Any, path: str) -> Any:
    """
    按点号路径取值。

    Returns:
        取到的值；路径不存在返回 ``None``（调用方据此跳过该条结果）
    """
    if not path:
        return data

    current = data
    for part in path.split("."):
        part = part.strip()
        if not part:
            continue
        name, indices, selector = _split_indices(part)
        if name:
            if not isinstance(current, dict):
                return None
            current = current.get(name, _MISSING)
            if current is _MISSING:
                return None
        # [?key=value]：从数组里挑第一个满足条件的元素。
        # 有些接口不直接给「主制作公司」，只给一个带 isMain 的列表。
        if selector is not None:
            if not isinstance(current, (list, tuple)):
                return None
            key, expected = selector
            current = next(
                (item for item in current
                 if isinstance(item, dict)
                 and _matches(item.get(key), expected)),
                _MISSING)
            if current is _MISSING:
                return None
        for index in indices:
            if not isinstance(current, (list, tuple)):
                return None
            if index >= len(current):
                return None
            current = current[index]
    return current


def dig_list(data: Any, path: str) -> List[Any]:
    """取一个数组；取不到或不是数组时返回空列表"""
    value = dig(data, path)
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def dig_str(data: Any, path: str) -> str:
    """
    取一个字符串。

    数组会被拼成逗号分隔（有些站点的画师字段是数组），
    数字会转成字符串 —— 映射表里不必关心这些细节。
    """
    value = dig(data, path)
    return _as_text(value)



def dig_any(data: Any, path: str) -> str:
    """
    支持**回退链**：``"anilist.title.chinese|anilist.title.native|anilist.title.romaji"``
    取第一个非空的。

    为什么需要：真实站点的字段常常是多语言/多来源的，声明式映射里
    用竖线串起来比"写段代码依次尝试"省事得多。
    """
    for candidate in (path or "").split("|"):
        text = dig_str(data, candidate.strip())
        if text:
            return text
    return ""


def dig_links(data: Any, path: str) -> List[str]:
    """
    收集链接：支持回退链，且**把所有候选都收下**（不像 dig_any 只取第一个）。

    值可以是数组（`ext_urls`）也可以是单个字符串（`siteUrl`），两种都接受。
    """
    out: List[str] = []
    for candidate in (path or "").split("|"):
        value = dig(data, candidate.strip())
        if isinstance(value, (list, tuple)):
            out.extend(str(v).strip() for v in value if str(v or "").strip())
        elif value is not None:
            text = str(value).strip()
            if text:
                out.append(text)
    return out


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        parts = [_as_text(v) for v in value]
        return ", ".join(p for p in parts if p)
    if isinstance(value, dict):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def _matches(actual: Any, expected: str) -> bool:
    """把数组元素里的值与配置里写的字符串比对"""
    if actual is None:
        return False
    if isinstance(actual, bool):
        return str(actual).lower() == expected.lower()
    return str(actual) == expected


def _split_indices(part: str):
    """
    解析一个路径片段。

    ``a[0][2]``              → ("a", [0, 2], None)
    ``edges[?isMain=true]``  → ("edges", [], ("isMain", "true"))
    """
    indices = []
    selector = None
    name = part
    while "[" in name and name.endswith("]"):
        head, _, tail = name.rpartition("[")
        inner = tail[:-1]
        if inner.startswith("?") and "=" in inner:
            key, _, expected = inner[1:].partition("=")
            selector = (key.strip(), expected.strip())
            name = head
            break
        try:
            index = int(inner)
        except ValueError:
            break
        indices.insert(0, index)
        name = head
    return name, indices, selector
