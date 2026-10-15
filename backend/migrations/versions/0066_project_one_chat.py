"""v2.95 项目 = 一段对话（app/project_chat.py）：同一项目的多段普通对话合并成一段 + 部分唯一索引。

合并（merge，幂等）：只看“还有 >1 段普通对话（task_id 为空）”的项目——
- 保留最早创建的那段（id 不变），其余对话的消息原样（created_at 不变）挪进来，时间线自然交织；
- 引用被合并对话 id 的行（REF_TABLES）一并改指保留那段，报告卡 / 反馈 / 账单点开不 404；
- 保留那段：标题 = 项目名、title_source=fixed、title_at / summary / summary_upto 清空（滚动摘要下一轮按新历史重生成）、
  updated_at = 各段最大、pinned / model / reasoning / routed_model / mode 取最近更新那段；被合并的对话行删除。
备份（可回退）：project_chat_merge_convs（每段被改 / 被删的对话一行：角色 kept|merged + 全部元数据 JSON），
project_chat_merge_refs（表名、行 id、原对话 id：每一行被改指的消息 / 引用）。downgrade 按备份还原后删索引和备份表。

Revision ID: 0066
Revises: 0065
"""
import json
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = '0066'
down_revision = '0065'
branch_labels = None
depends_on = None

INDEX = 'uq_conversations_project_chat'
WHERE = "project_id IS NOT NULL AND task_id IS NULL"
CONV_COLS = ('title', 'title_source', 'title_at', 'pinned', 'model', 'routed_model', 'reasoning', 'mode', 'mode_seen',
             'plan_path', 'summary', 'summary_upto', 'created_at', 'updated_at', 'project_id', 'task_id')
# 带 conversation_id 的表（messages 单独处理但同一套备份）；主键都是 id
REF_TABLES = ('messages', 'turn_journals', 'task_runs', 'feedback', 'home_cards', 'usage', 'routings', 'subagent_threads',
              'video_transcripts', 'jobs')
LATEST = ('pinned', 'model', 'routed_model', 'reasoning', 'mode')


def _tables(conn) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def _json(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _backup_tables(conn) -> None:
    have = _tables(conn)
    if 'project_chat_merge_convs' not in have:
        op.create_table('project_chat_merge_convs',
                        sa.Column('conversation_id', sa.String(32), primary_key=True),
                        sa.Column('project_id', sa.String(32), nullable=False),
                        sa.Column('kept_id', sa.String(32), nullable=False),
                        sa.Column('role', sa.String(8), nullable=False),  # kept | merged
                        sa.Column('meta', sa.Text(), nullable=False),     # CONV_COLS 的原值（JSON）
                        sa.Column('merged_at', sa.DateTime(timezone=True), nullable=False))
    if 'project_chat_merge_refs' not in have:
        op.create_table('project_chat_merge_refs',
                        sa.Column('table_name', sa.String(32), primary_key=True),
                        sa.Column('row_id', sa.String(64), primary_key=True),
                        sa.Column('conversation_id', sa.String(32), nullable=False))


def merge(conn) -> int:
    """合并所有多对话项目；返回合并掉的对话段数。重复调用无变化（已经只剩一段的项目不碰）。"""
    have = _tables(conn)
    refs = [t for t in REF_TABLES if t in have]
    cols = ', '.join(CONV_COLS)
    multi = [r[0] for r in conn.execute(sa.text(
        "SELECT project_id FROM conversations WHERE project_id IS NOT NULL AND task_id IS NULL "
        "GROUP BY project_id HAVING COUNT(*) > 1")).all()]
    merged = 0
    now = datetime.now(timezone.utc)
    for pid in multi:
        rows = conn.execute(sa.text(f"SELECT id, {cols} FROM conversations WHERE project_id = :p AND task_id IS NULL "
                                    "ORDER BY created_at, id"), {"p": pid}).mappings().all()
        kept, others = rows[0], rows[1:]
        name = conn.execute(sa.text("SELECT name FROM projects WHERE id = :p"), {"p": pid}).scalar()
        for r in rows:
            exists = conn.execute(sa.text("SELECT 1 FROM project_chat_merge_convs WHERE conversation_id = :c"),
                                  {"c": r["id"]}).first()
            if not exists:
                conn.execute(sa.text("INSERT INTO project_chat_merge_convs (conversation_id, project_id, kept_id, role, meta, merged_at) "
                                     "VALUES (:c, :p, :k, :role, :m, :at)"),
                             {"c": r["id"], "p": pid, "k": kept["id"], "role": "kept" if r is kept else "merged",
                              "m": json.dumps({k: _json(r[k]) for k in CONV_COLS}, ensure_ascii=False), "at": now})
        other_ids = [r["id"] for r in others]
        for t in refs:
            for (row_id, cid) in conn.execute(sa.text(f"SELECT id, conversation_id FROM {t} WHERE conversation_id IN :ids")
                                              .bindparams(sa.bindparam("ids", expanding=True)), {"ids": other_ids}).all():
                if not conn.execute(sa.text("SELECT 1 FROM project_chat_merge_refs WHERE table_name = :t AND row_id = :r"),
                                    {"t": t, "r": str(row_id)}).first():
                    conn.execute(sa.text("INSERT INTO project_chat_merge_refs (table_name, row_id, conversation_id) VALUES (:t, :r, :c)"),
                                 {"t": t, "r": str(row_id), "c": cid})
            conn.execute(sa.text(f"UPDATE {t} SET conversation_id = :k WHERE conversation_id IN :ids")
                         .bindparams(sa.bindparam("ids", expanding=True)), {"k": kept["id"], "ids": other_ids})
        latest = max(rows, key=lambda r: (r["updated_at"] is not None, r["updated_at"] or 0))
        conn.execute(sa.text("UPDATE conversations SET title = :title, title_source = 'fixed', title_at = NULL, summary = '', "
                             "summary_upto = NULL, updated_at = :u, pinned = :pinned, model = :model, routed_model = :routed, "
                             "reasoning = :reasoning, mode = :mode WHERE id = :k"),
                     {"title": (name or kept["title"] or "项目")[:200], "u": latest["updated_at"], "pinned": latest["pinned"],
                      "model": latest["model"], "routed": latest["routed_model"], "reasoning": latest["reasoning"],
                      "mode": latest["mode"] or "default", "k": kept["id"]})
        conn.execute(sa.text("DELETE FROM conversations WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True)),
                     {"ids": other_ids})
        merged += len(other_ids)
    return merged


def restore(conn) -> int:
    """按备份还原（downgrade）：重建被合并的对话、行改回原对话、恢复保留那段的元数据。返回还原的对话段数。"""
    if 'project_chat_merge_convs' not in _tables(conn):
        return 0
    backups = conn.execute(sa.text("SELECT conversation_id, role, meta FROM project_chat_merge_convs")).mappings().all()
    names = ', '.join(CONV_COLS)
    params = ', '.join(f':{k}' for k in CONV_COLS)

    def values(meta: str, cid: str) -> dict:
        m = json.loads(meta)
        out = {k: m.get(k) for k in CONV_COLS}
        for k in ('created_at', 'updated_at'):
            if isinstance(out[k], str):
                out[k] = datetime.fromisoformat(out[k])
        return {**out, "id": cid}

    for b in backups:
        if b["role"] == "merged" and not conn.execute(sa.text("SELECT 1 FROM conversations WHERE id = :c"),
                                                      {"c": b["conversation_id"]}).first():
            conn.execute(sa.text(f"INSERT INTO conversations (id, {names}) VALUES (:id, {params})"),
                         values(b["meta"], b["conversation_id"]))
    have = _tables(conn)
    for t, row_id, cid in conn.execute(sa.text("SELECT table_name, row_id, conversation_id FROM project_chat_merge_refs")).all():
        if t in have:
            conn.execute(sa.text(f"UPDATE {t} SET conversation_id = :c WHERE CAST(id AS VARCHAR(64)) = :r"), {"c": cid, "r": row_id})
    for b in backups:
        if b["role"] == "kept":
            v = values(b["meta"], b["conversation_id"])
            sets = ', '.join(f'{k} = :{k}' for k in CONV_COLS)
            conn.execute(sa.text(f"UPDATE conversations SET {sets} WHERE id = :id"), v)
    return sum(1 for b in backups if b["role"] == "merged")


def upgrade() -> None:
    conn = op.get_bind()
    _backup_tables(conn)
    merge(conn)
    op.create_index(INDEX, 'conversations', ['project_id'], unique=True,
                    sqlite_where=sa.text(WHERE), postgresql_where=sa.text(WHERE))


def downgrade() -> None:
    conn = op.get_bind()
    op.drop_index(INDEX, table_name='conversations')
    restore(conn)
    op.drop_table('project_chat_merge_refs')
    op.drop_table('project_chat_merge_convs')
