#!/usr/bin/env python3
"""按 voices_simplefied.csv 应用短 voice_id：重命名音频、更新 SQLite、删除废弃音色。"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from api.config import resolve_voice_db_path

REMOVED_VOICE_IDS = (
    "bingling",
    "403_speaker_0020260124_100540",
    "ext_switch_test",
    "test_upload_check",
)

# id -> (old_voice_id from DB at migration time, old file on disk)
RENAME_FILES = {
    14: ("bud__Hale__dXtC3XhB9GtPusIpNtQx", "bud__Hale__dXtC3XhB9GtPusIpNtQx.mp3"),
    5: ("dorothy__Hope__OYTbf65OHHFELVut7v2H", "dorothy__Hope__OYTbf65OHHFELVut7v2H.mp3"),
    3: ("ellen__Tara__P7vsEyTOpZ6YUTulin8m", "ellen__Tara__P7vsEyTOpZ6YUTulin8m.mp3"),
    7: ("leo__William_Shanks__8Es4wFxsDlHBmFWAOWRS", "leo__William_Shanks__8Es4wFxsDlHBmFWAOWRS.mp3"),
    2: ("marion__LavenderLessons__QwvsCFsQcnpWxmP1z7V9", "marion__LavenderLessons__QwvsCFsQcnpWxmP1z7V9.mp3"),
    9: ("narrator__Ian_Cartwell__e5WNhrdI30aXpS2RSGm1", "narrator__Ian_Cartwell__e5WNhrdI30aXpS2RSGm1.mp3"),
    49: ("prompt_10_70", "prompt_10_70.mp3"),
    52: ("prompt_k0ls_15_75", "prompt_k0ls_15_75.wav"),
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_csv(path: str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["file_name"] = (r.get("file_name") or "").strip().rstrip("@")
        stem = os.path.splitext(r["file_name"])[0]
        if stem != r["voice_id"]:
            ext = os.path.splitext(r["file_name"])[1]
            r["file_name"] = r["voice_id"] + ext
    return rows


def _rename_audio(speakers_dir: str, rows: list[dict[str, str]], dry_run: bool) -> None:
    id_to_row = {int(r["id"]): r for r in rows}
    for rid, (old_vid, old_fn) in RENAME_FILES.items():
        row = id_to_row.get(rid)
        if not row:
            raise SystemExit(f"CSV 缺少 id={rid}")
        new_fn = row["file_name"]
        src = os.path.join(speakers_dir, old_fn)
        dst = os.path.join(speakers_dir, new_fn)
        if not os.path.isfile(src):
            if os.path.isfile(dst):
                print(f"  跳过重命名（目标已存在）: {old_fn} -> {new_fn}")
                continue
            raise SystemExit(f"源文件不存在: {src}")
        if os.path.abspath(src) == os.path.abspath(dst):
            continue
        if os.path.exists(dst):
            raise SystemExit(f"目标已存在，无法重命名: {dst}")
        print(f"  重命名: {old_fn} -> {new_fn}")
        if not dry_run:
            os.rename(src, dst)

    for r in rows:
        fn = r["file_name"]
        path = os.path.join(speakers_dir, fn)
        if os.path.isfile(path):
            continue
        rid = int(r["id"])
        if rid in RENAME_FILES:
            _, old_fn = RENAME_FILES[rid]
            if os.path.isfile(os.path.join(speakers_dir, old_fn)):
                continue
        raise SystemExit(f"缺少音频文件 voice_id={r['voice_id']}: {path}")


def _delete_removed(speakers_dir: str, conn: sqlite3.Connection, dry_run: bool) -> None:
    for vid in REMOVED_VOICE_IDS:
        cur = conn.execute("SELECT file_name FROM voices WHERE voice_id = ?", (vid,))
        row = cur.fetchone()
        if row:
            fn = row[0]
            path = os.path.join(speakers_dir, fn)
            print(f"  删除库记录: {vid}")
            if not dry_run:
                conn.execute("DELETE FROM voices WHERE voice_id = ?", (vid,))
            if os.path.isfile(path):
                print(f"  删除音频: {fn}")
                if not dry_run:
                    os.remove(path)
        else:
            print(f"  库中无记录（跳过）: {vid}")


def _apply_db(conn: sqlite3.Connection, rows: list[dict[str, str]], dry_run: bool) -> None:
    now = _utc_now_iso()
    id_to_old_vid = {
        rid: old for rid, (old, _) in RENAME_FILES.items()
    }
    cur_vids = {int(row[0]): row[1] for row in conn.execute("SELECT id, voice_id FROM voices")}

    for r in rows:
        rid = int(r["id"])
        new_vid = r["voice_id"]
        old_vid = cur_vids.get(rid)
        if old_vid is None:
            raise SystemExit(f"DB 无 id={rid}，CSV 行 voice_id={new_vid}")

        if old_vid != new_vid:
            print(f"  voice_id: {old_vid} -> {new_vid} (id={rid})")
            if not dry_run:
                conn.execute(
                    "UPDATE voices SET voice_id = ? WHERE id = ?",
                    (new_vid, rid),
                )

        if not dry_run:
            conn.execute(
                """
                UPDATE voices SET
                    name = ?,
                    description = ?,
                    language = ?,
                    gender = ?,
                    file_name = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    r["name"],
                    r["description"],
                    r["language"],
                    r["gender"],
                    r["file_name"],
                    now,
                    rid,
                ),
            )

    if not dry_run:
        conn.commit()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--csv",
        default=os.path.join(_ROOT, "voices_simplefied.csv"),
        help="简化音色 CSV",
    )
    p.add_argument("--prompt-dir", default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    speakers_dir = (
        os.path.abspath(args.prompt_dir)
        if args.prompt_dir and os.path.isabs(args.prompt_dir)
        else os.path.dirname(resolve_voice_db_path(args.prompt_dir))
    )
    db_path = os.path.join(speakers_dir, "voices.db")
    rows = _load_csv(args.csv)

    print(f"CSV 行数: {len(rows)}")
    print(f"目录: {speakers_dir}")
    print(f"数据库: {db_path}")
    if args.dry_run:
        print("*** DRY RUN ***\n")

    print("1) 重命名音频文件")
    _rename_audio(speakers_dir, rows, args.dry_run)

    conn = sqlite3.connect(db_path)
    try:
        print("2) 删除废弃音色")
        _delete_removed(speakers_dir, conn, args.dry_run)
        print("3) 更新元数据与 voice_id")
        _apply_db(conn, rows, args.dry_run)
        if not args.dry_run:
            n = conn.execute("SELECT COUNT(*) FROM voices").fetchone()[0]
            print(f"\n完成。voices 表现有 {n} 条。")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
