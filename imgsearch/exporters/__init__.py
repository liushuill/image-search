"""
导出格式

导出**不下载任何文件**，只输出地址。支持一次产出多种格式（勾选式）。

典型用法::

    from imgsearch.exporters import (
        from_results, from_library, parse_format_list, write_outputs,
    )

    records = from_results(results, file="a.jpg", dhash="...")
    formats = parse_format_list("urls,csv,html")
    write_outputs(formats, records, Path("./out"), stem="我的结果")
"""

from imgsearch.exporters.base import (          # noqa: F401
    DEFAULT_NAME_TEMPLATE,
    ExportRecord,
    Format,
    all_formats,
    format_keys,
    get,
    parse_format_list,
    register,
    render_name,
    sanitize_filename,
    write_outputs,
)
from imgsearch.exporters.collect import (       # noqa: F401
    from_csv,
    from_library,
    from_results,
    result_to_record,
)

# 导入即注册（顺序决定 CLI/GUI 里的展示顺序）
from imgsearch.exporters import clipboard_format  # noqa: F401,E402
from imgsearch.exporters import html_report       # noqa: F401,E402
from imgsearch.exporters import structured        # noqa: F401,E402
from imgsearch.exporters import tabular           # noqa: F401,E402
from imgsearch.exporters import urls              # noqa: F401,E402

__all__ = [
    # 子模块也在 __all__ 里：它们是「导入即注册」的，属于公开表面
    "clipboard_format", "html_report", "structured", "tabular", "urls",
    "ExportRecord", "Format",
    "all_formats", "format_keys", "get", "parse_format_list", "register",
    "render_name", "sanitize_filename", "write_outputs", "DEFAULT_NAME_TEMPLATE",
    "from_results", "from_library", "from_csv", "result_to_record",
]
