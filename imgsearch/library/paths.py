"""
图库根路径管理

用户可以手动登记多个根路径（分布在不同的磁盘/目录）。三条设计约束：

1. **拒绝嵌套**
   若 `图片库/` 与 `图片库/待查/` 同时登记，同一张图会被两条路径覆盖 ——
   记录重复、占用统计失真、"删路径时清理"也会误伤。因此在**添加时**就拒绝，
   并明确告出与哪条已有路径冲突。

2. **失效路径要标出来，而不是默默删数据**
   外接盘未挂载、目录被改名都会让路径暂时不存在。这时只标记状态，
   让用户**重新指定**新位置（:meth:`RootManager.relocate`），记录一律保留。

3. **删除时可选择是否清理持久化数据**
   删根路径只解除登记；要不要顺带清掉它名下的搜索结果/缩略图，由调用方决定
   （见 :mod:`imgsearch.library.cleanup`）。
"""

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

from imgsearch.library.db import LibraryDB
from imgsearch.library.errors import LibraryError


def normalize_path(raw: Union[str, Path]) -> str:
    """
    归一化路径：展开 ``~``、转绝对路径、消除 ``..`` 与符号链接。

    路径**不存在**也要能归一化 —— 用户可能先登记一个尚未挂载的外接盘。
    """
    text = os.path.expanduser(str(raw)).strip()
    if not text:
        raise LibraryError("路径不能为空")
    # realpath 在路径不存在时仍会做词法归一（消除 .. 与重复分隔符）
    return os.path.realpath(os.path.abspath(text))


def _is_ancestor_or_same(a: str, b: str) -> bool:
    """a 是否等于 b，或 b 位于 a 之内"""
    try:
        return os.path.commonpath([a, b]) == a
    except ValueError:
        # 不同盘符（Windows）或无法比较
        return False


@dataclass
class Root:
    """一个已登记的图库根路径"""

    id: int
    path: str
    label: str = ""
    added_at: str = ""
    enabled: bool = True

    @property
    def exists(self) -> bool:
        """路径当前是否存在（外接盘未挂载 / 目录被改名时为 False）"""
        return os.path.isdir(self.path)

    @property
    def display(self) -> str:
        """界面上显示的名字：有别名用别名，否则用路径"""
        return self.label or self.path

    def __str__(self) -> str:
        status = "" if self.exists else "  [路径不存在]"
        return f"{self.display}{status}"


class RootManager:
    """根路径的增删查改"""

    def __init__(self, db: LibraryDB):
        self.db = db

    # ── 查 ──────────────────────────────────────

    def list(self, only_existing: bool = False) -> List[Root]:
        rows = self.db.query("SELECT * FROM roots ORDER BY id")
        roots = [self._row_to_root(r) for r in rows]
        if only_existing:
            roots = [r for r in roots if r.exists]
        return roots

    def get(self, ident: Union[int, str]) -> Optional[Root]:
        """按 id 或路径取根路径"""
        row = None
        if isinstance(ident, int):
            row = self.db.query_one("SELECT * FROM roots WHERE id = ?", (ident,))
        else:
            row = self.db.query_one(
                "SELECT * FROM roots WHERE path = ?", (normalize_path(ident),)
            )
        return self._row_to_root(row) if row else None

    @staticmethod
    def _row_to_root(row) -> Root:
        return Root(
            id=row["id"],
            path=row["path"],
            label=row["label"],
            added_at=row["added_at"],
            enabled=bool(row["enabled"]),
        )

    def find_conflict(self, path: str, exclude_id: Optional[int] = None) -> Optional[Root]:
        """
        找出会与该路径产生重叠（嵌套）的已有根路径。

        Returns:
            冲突的 Root；无冲突返回 None
        """
        target = normalize_path(path)
        for root in self.list():
            if exclude_id is not None and root.id == exclude_id:
                continue
            if root.path == target:
                return root
            # 任一方包含另一方，都会导致同一文件被两条路径覆盖
            if _is_ancestor_or_same(root.path, target):
                return root
            if _is_ancestor_or_same(target, root.path):
                return root
        return None

    def roots_containing(self, file_path: str) -> List[Root]:
        """文件落在哪些根路径下（按路径长度降序，最具体的在前）"""
        target = normalize_path(file_path)
        hits = [r for r in self.list() if _is_ancestor_or_same(r.path, target)]
        return sorted(hits, key=lambda r: len(r.path), reverse=True)

    # ── 增 ──────────────────────────────────────

    def add(self, path: Union[str, Path], label: str = "") -> Root:
        """
        登记一个图库根路径。

        ⚠️ 路径**不要求已存在** —— 允许先登记尚未挂载的外接盘，
        之后用 :meth:`relocate` 指定或等它挂载上来。

        Raises:
            LibraryError: 路径为空、重复登记，或与已有路径嵌套
        """
        target = normalize_path(path)

        conflict = self.find_conflict(target)
        if conflict is not None:
            if conflict.path == target:
                raise LibraryError(f"该路径已经登记过了：\n  {target}")
            if _is_ancestor_or_same(conflict.path, target):
                raise LibraryError(
                    f"路径重叠：新路径位于已登记的根路径之内\n"
                    f"  已有：{conflict.path}\n"
                    f"  新增：{target}\n"
                    f"（同时登记会让同一张图被记录两次，请只保留粒度合适的那一条）"
                )
            raise LibraryError(
                f"路径重叠：新路径包含了已登记的根路径\n"
                f"  已有：{conflict.path}\n"
                f"  新增：{target}\n"
                f"（同时登记会让同一张图被记录两次，请只保留粒度合适的那一条）"
            )

        added_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.db.transaction():
            cur = self.db.conn.execute(
                "INSERT INTO roots(path, label, added_at, enabled) VALUES(?, ?, ?, 1)",
                (target, label or "", added_at),
            )
        return Root(id=cur.lastrowid, path=target, label=label or "",
                    added_at=added_at, enabled=True)

    # ── 改 ──────────────────────────────────────

    def set_label(self, root_id: int, label: str) -> bool:
        with self.db.transaction():
            cur = self.db.conn.execute(
                "UPDATE roots SET label = ? WHERE id = ?", (label or "", root_id)
            )
        return cur.rowcount > 0

    def set_enabled(self, root_id: int, enabled: bool) -> bool:
        with self.db.transaction():
            cur = self.db.conn.execute(
                "UPDATE roots SET enabled = ? WHERE id = ?", (1 if enabled else 0, root_id)
            )
        return cur.rowcount > 0

    def relocate(self, root_id: int, new_path: Union[str, Path],
                 rewrite_records: bool = True) -> int:
        """
        把根路径指到新位置（目录被改名/移动后使用）。

        Args:
            root_id: 要改的根路径
            new_path: 新位置
            rewrite_records: 是否顺带改写名下记录的绝对路径前缀。
                置 True 时记录会跟着一起搬到新位置，不需要重新扫描。

        Returns:
            被改写路径的记录条数

        Raises:
            LibraryError: 根路径不存在、新路径与别的根路径冲突
        """
        root = self.get(root_id)
        if root is None:
            raise LibraryError(f"未找到根路径 id={root_id}")

        target = normalize_path(new_path)
        conflict = self.find_conflict(target, exclude_id=root_id)
        if conflict is not None:
            raise LibraryError(
                f"新位置与已有根路径重叠：\n  {conflict.path}\n  {target}"
            )

        old_prefix = root.path
        updated = 0

        with self.db.transaction():
            self.db.conn.execute(
                "UPDATE roots SET path = ? WHERE id = ?", (target, root_id)
            )
            if rewrite_records:
                rows = self.db.conn.execute(
                    "SELECT id, abs_path FROM images WHERE root_id = ?", (root_id,)
                ).fetchall()
                for row in rows:
                    old_abs = row["abs_path"] or ""
                    if old_abs.startswith(old_prefix):
                        new_abs = target + old_abs[len(old_prefix):]
                    else:
                        new_abs = target
                    rel = os.path.relpath(new_abs, target) if new_abs != target else ""
                    self.db.conn.execute(
                        "UPDATE images SET abs_path = ?, rel_path = ?, missing = 0 "
                        "WHERE id = ?",
                        (new_abs, rel, row["id"]),
                    )
                    updated += 1

        return updated

    # ── 删 ──────────────────────────────────────

    def remove(self, ident: Union[int, str]) -> bool:
        """
        解除登记（**不动**持久化数据）。

        要不要顺带清理它名下的记录，由调用方在删除前后自行决定 ——
        见 :func:`imgsearch.library.cleanup.purge_root`。
        """
        root = self.get(ident)
        if root is None:
            return False
        with self.db.transaction():
            # images.root_id 是 ON DELETE SET NULL：记录保留，只失去归属
            self.db.conn.execute("DELETE FROM roots WHERE id = ?", (root.id,))
        return True

    # ── 状态刷新 ────────────────────────────────

    def refresh_missing(self, root_id: Optional[int] = None) -> int:
        """
        重新检查文件是否还在最后已知位置，更新 ``missing`` 标记。

        文件被移走后记录**不会**删除 —— 仍然可以凭 dHash 命中缓存结果，
        只是界面上会显示「文件已不在原位置」。

        Returns:
            标记为 missing 的记录数
        """
        sql = "SELECT id, abs_path FROM images"
        params: tuple = ()
        if root_id is not None:
            sql += " WHERE root_id = ?"
            params = (root_id,)

        rows = self.db.query(sql, params)
        missing_ids, present_ids = [], []
        for row in rows:
            path = row["abs_path"] or ""
            (present_ids if path and os.path.isfile(path) else missing_ids).append(row["id"])

        with self.db.transaction():
            if missing_ids:
                self.db.conn.executemany(
                    "UPDATE images SET missing = 1 WHERE id = ?",
                    [(i,) for i in missing_ids],
                )
            if present_ids:
                self.db.conn.executemany(
                    "UPDATE images SET missing = 0 WHERE id = ?",
                    [(i,) for i in present_ids],
                )
        return len(missing_ids)
