# 第三方组件与许可（Third-Party Notices）

本项目使用下列第三方组件。它们各自的许可条款独立于本项目自身的许可，
在分发本项目（源码或编译产物）时必须一并保留本文件与 `LICENSES/` 下的许可全文。

---

## Qt / PySide6 —— LGPL-3.0

| 项 | 内容 |
|---|---|
| 组件 | Qt 6.11.2、PySide6 6.11.2、Shiboken6 |
| 版权 | Copyright (C) The Qt Company Ltd. and contributors |
| 许可 | **GNU Lesser General Public License v3.0**（LGPL-3.0） |
| 许可全文 | [`LICENSES/LGPL-3.0.txt`](LICENSES/LGPL-3.0.txt)、[`LICENSES/GPL-3.0.txt`](LICENSES/GPL-3.0.txt) |
| 源码获取 | https://download.qt.io/official_releases/QtForPython/ 与 https://code.qt.io/ |
| 项目主页 | https://www.qt.io/qt-for-python |

### 本项目的合规做法

LGPL-3.0 允许把 Qt 与**非自由软件**一起分发，前提是满足以下条件。
本项目按如下方式满足：

1. **动态链接**：PySide6 / Qt 以共享库形式使用，未做静态链接、未修改其源码。
2. **可替换**：编译产物使用 **onedir** 形式（Qt 的 `.so` / `.dll` 作为独立文件
   存放于程序目录内），用户可直接替换这些库文件。
3. **许可告知**：本文件在**构建产物中一并分发**（见下节的打包说明），
   并在程序内提供查看入口。
4. **源码可获取**：上方「源码获取」给出了 Qt / PySide6 的官方源码地址。

> ⚠️ 打包时的具体要求（供构建者参考）：
> - 使用 `--onedir`，**不要**用只产出单个可执行文件的封装形式；
> - 把 `THIRD_PARTY_NOTICES.md` 与整个 `LICENSES/` 目录放进产物目录
>   （PyInstaller 用 `--add-data`）；
> - 不要对 Qt 的库文件做加壳、加密或任何妨碍替换的处理。

---

## Python 运行时与依赖

| 组件 | 许可 | 用途 |
|---|---|---|
| CPython 3.13 | PSF License | Python 运行时 |
| requests | Apache-2.0 | HTTP 请求 |
| urllib3 | MIT | requests 的传输层 |
| certifi | MPL-2.0 | CA 证书包 |
| charset-normalizer | MIT | 响应编码识别 |
| idna | BSD-3-Clause | 国际化域名 |
| Pillow | MIT-CMU（HPND） | 图片解码、缩略图 |
| lxml | BSD-3-Clause | HTML 解析（BeautifulSoup 的后端） |
| beautifulsoup4 | MIT | HTML 解析 |
| soupsieve | MIT | CSS 选择器（BeautifulSoup 依赖） |
| cloudscraper | MIT | 绕过 Cloudflare（仅 Ascii2D 引擎使用） |

> 各组件许可全文随其发行包提供；如需在产物中附带，可从对应的 PyPI 页面下载。

---

## 数据来源

本项目**只查询**下列第三方图片检索服务，不重新分发其数据：

- SauceNAO —— https://saucenao.com
- IQDB —— https://iqdb.org
- Ascii2D —— https://ascii2d.net
- trace.moe —— https://trace.moe
- Danbooru —— https://danbooru.donmai.us

使用这些服务时适用各自的使用条款与速率限制。**使用者需自行遵守**。

---

## 关于图片内容

本工具只输出**链接**与元数据，不下载、不存储、不再分发任何第三方图片作品。
图片版权归其原作者所有。使用者应自行确认其使用行为符合当地法律与站点条款。
