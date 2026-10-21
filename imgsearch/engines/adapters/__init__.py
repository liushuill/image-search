"""
声明式适配器：不写代码就接一个新站点

分成两大类（用户视角的「两类模板」）：

- :mod:`~imgsearch.engines.adapters.generic_json` —— 站点返回 JSON
- :mod:`~imgsearch.engines.adapters.generic_html` —— 站点返回 HTML 页面

两者共用 :mod:`~imgsearch.engines.adapters.declarative` 里的请求/鉴权/量纲逻辑，
站点差异全部由配置（一张映射表）表达。

⚠️ 覆盖不到的仍然要写代码：多步流程（POST→重定向→GET）、Cloudflare 反爬、
需要计算拼接的字段。这类站点保持「一个引擎一个文件」的方式。
"""

# 从这里导出，注册表才能自动发现它们 ——
# registry.ensure_builtins_loaded() 遍历的是 engines/ 下的模块，
# 对子包只导入其 __init__，所以类必须在这里可见。
from imgsearch.engines.adapters.generic_html import GenericHtml  # noqa: E402
from imgsearch.engines.adapters.generic_json import GenericJson  # noqa: E402

# 列进 __all__ 既表明「这是公开表面」，也让静态检查知道它们是被有意导出的
__all__ = ["GenericHtml", "GenericJson"]
