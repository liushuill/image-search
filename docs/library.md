# 本地图库

> 图库解决的是「同一张图不要搜第二遍」。身份是内容指纹（dHash），不是路径。

---

## 它是什么

### 为什么要以「内容」而不是「路径」为身份

实际工作流是：**搜完一批图 → 下载原图 → 把图统一移到「搜集过的」目录**。
文件路径会不断变化，所以：

- 图片身份 = **dHash 感知哈希**，路径只是**可变的「最后已知位置」**
- 文件移到任何目录，都能凭 dHash 认出「这张搜过了」，**直接复用缓存结果**
- 这意味着**不重复消耗搜索配额**（SauceNAO 免费版只有 100 次/天）

```bash
./run.sh search 某张图.jpg          # 首次：正常搜索，并自动记入图库
./run.sh search 这张图的新位置.jpg   # 之后：图库命中，零配额消耗
./run.sh search 某张图.jpg --refresh # 想重新搜：加 --refresh
```

```
📚 图库命中：这张图搜过了 —— 同一张
   记录 id=1 · dHash=d6b2ced6b2b39184
   —— 以下结果来自本地缓存，未消耗任何搜索配额 ——
```

### 路径管理

```bash
./run.sh library add /path/to/图库 --label 图片库   # 手动登记（可多个，支持尚未挂载的外接盘）
./run.sh library list                               # 路径列表 + 状态 + 每路径统计
./run.sh library relocate 1 /新位置                  # 目录被改名/搬走：重新指定，记录路径一起改写
./run.sh library refresh                            # 重新检查文件是否还在原位（不会删记录）
./run.sh library find 某张图.jpg                     # 这张搜过了吗（与文件名、路径无关）
```

- **拒绝嵌套**：`图片库/` 与 `图片库/待查/` 不能同时登记 —— 否则同一张图会被记两次。
  添加时就会明确告知与哪条路径冲突。
- **失效路径只标记、不清数据**：外接盘未挂载或目录改名时标出来，用 `relocate` 指定新位置即可。

### 清理持久化数据

```bash
./run.sh library stats                              # 按路径 + 按类别的占用明细
./run.sh library clean --results                    # 清空搜索结果（保留图片记录与 dHash 索引）
./run.sh library clean --thumbs                     # 清空缓存缩略图
./run.sh library clean --path 3 --images --thumbs    # 清空某条路径的全部数据
./run.sh library clean --orphans                    # 清理孤立缩略图
./run.sh library remove 3 --purge all               # 移除路径时顺带清空其数据
```

- 清理前会先**预演**（显示将删除多少条、约多少体积），再要求确认；`--yes` 跳过确认。
- ⚠️ 每次清理后都会 **`checkpoint → VACUUM → checkpoint`**。
  SQLite 的 `DELETE` 只把页标记为可复用、文件不会缩小；而 WAL 模式下
  `VACUUM` 的产物又先落在 `-wal` 里 —— 不 checkpoint 的话磁盘占用**看起来不降反升**。
  这就是「清了半天发现文件没变小」的根因。实测 20000 条记录：**15.4 MB → 56 KB**。

### 直接查数据库

底库就是**一个 SQLite 文件**（`data/image_metadata.db`，WAL 模式）。
不需要装任何东西 —— Python 自带 SQLite：

```bash
./run.sh library sql --tables              # 列出表与行数（不用会 SQL）
./run.sh library sql --schema              # 列出字段定义
./run.sh library sql --schema images       # 只看某张表
./run.sh library sql                        # 打印速查表 + 可直接照抄的示例查询
./run.sh library sql "SELECT dhash, abs_path FROM images LIMIT 5"
./run.sh library sql --write "UPDATE ..."  # 默认只读，要改得显式加 --write
```

默认**只读**（两道护栏：语句筛查 + `PRAGMA query_only`），目的是防手滑而非安全边界。
输出是列对齐的表格，中文按全角宽度计算，不会错位。

> 不用系统装的 `sqlite3`（Debian 上要 apt）。若想用那个交互 shell：
> `sudo apt install sqlite3`，然后 `sqlite3 data/image_metadata.db .tables`。

表结构：

```
roots   (id, path, label, added_at, enabled)          你手动登记的根路径
images  (id, dhash, width, height, size, mtime,       dhash = 身份；路径只是
         root_id→roots, abs_path, rel_path,              「最后已知位置」
         first_seen, last_seen, missing)
results (id, image_id→images, engine, similarity,      一条命中；删图会级联删结果
         pixiv_id, pixiv_page, artist, artist_id,
         title, material, ext_urls, highres_url,
         thumbnail, danbooru_id, gelbooru_id,
         twitter_id, extra_ids, detail, fetched_at)
meta    (key, value)                                   内部元信息
```

规模参考：约 **790 字节/图**（含多条结果），4000 张 ≈ 5 MB，10 万张 ≈ 120 MB。

### 判重档位

匹配结果会如实告知，不把「相似」当成「同一张」：

| 判定 | 含义 |
|---|---|
| `exact` | dHash 相同且尺寸相同 —— 基本就是同一张（可能被重新编码过） |
| `scaled` | dHash 距离很小但尺寸不同 —— 同一张画的缩放版 |
| `similar` | dHash 距离在阈值内且尺寸相同 —— 视觉接近，需人工确认 |

实测：一张 400×300 的原图与它「缩到一半 + 质量 30」的版本，dHash 距离仅 **1**，
判定为 `scaled` —— 正是「质量被压缩、想找原图」要解决的场景。

---


### 存储占用（实测，不是估算）

| 项目 | 单个 | 101 张 | 1 万张 |
|---|---|---|---|
| 原图 | ~1.5 MB | 148 MB | ~15 GB |
| **本地图缩略图**（256px / 质量 82） | **12.3 KB** | **1.8 MB** | ~120 MB |
| **图源缩略图**（每条命中一个） | 4–10 KB | 每个新图 ~55 KB | — |

缩略图只占原图的约 **1.2%**。

**图源缩略图缓存是整套缓存里唯一会无界增长的东西**（每看一次新图的结果
就多几条），因此：

- 有容量上限 `url_thumb_cache_mb`（默认 100 MB，**在「设置」页可调**，0 = 不限制）
- 超出后按 **最久未用** 自动淘汰（依据访问时间）
- **「清理」页能看见它、也能单独清空**（可只清某条路径名下的）

### 两个实测得来的细节

- **图源缩略图的链接会失效**：SauceNAO 的缩略图地址带 `?auth=…` 令牌，
  实测「当场取有效、过一会儿再取 403」。所以磁盘缓存键用**去掉查询串的
  URL** —— 重新搜索同一张图能命中缓存；历史记录里的旧链接取不到时，
  格子会明确显示「取不到（链接已过期）」，而不是留空白让人以为坏了。
- **不同图源的可达性相反**：iqdb.org 的缩略图直连 200、走代理失败；
  i.pximg.net 反之。所以下载是「先直连（短超时）→ 再走代理」。
