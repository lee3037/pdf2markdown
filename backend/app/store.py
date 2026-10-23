import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import Settings


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = settings.data_dir / "tasks.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, filename TEXT NOT NULL, pages INTEGER NOT NULL,
                size INTEGER NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, markdown TEXT, settings TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0, edited INTEGER NOT NULL DEFAULT 0,
                error TEXT, attempts INTEGER NOT NULL DEFAULT 1
            )""")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(tasks)")}
            for name, definition in {
                "mode": "TEXT NOT NULL DEFAULT 'mock'", "input_sha256": "TEXT NOT NULL DEFAULT ''",
                "parse_profile": "TEXT NOT NULL DEFAULT '{}'", "upstream_id": "TEXT",
                "submission_started": "INTEGER NOT NULL DEFAULT 0", "error_code": "TEXT",
                "metadata": "TEXT NOT NULL DEFAULT '{}'", "cache_key": "TEXT",
            }.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE tasks ADD COLUMN {name} {definition}")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def decode(row):
        if row is None:
            return None
        task = dict(row)
        task["settings"] = json.loads(task["settings"])
        task["edited"] = bool(task["edited"])
        task["metadata"] = json.loads(task["metadata"])
        task["parse_profile"] = json.loads(task["parse_profile"])
        task["submission_started"] = bool(task["submission_started"])
        return task

    def get(self, task_id):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def list(self):
        with self.connect() as db:
            return [self.decode(row) for row in db.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT 100"
            ).fetchall()]

    def create(self, task_id, filename, pages, size, content_hash=""):
        stamp = now()
        options = json.dumps({"separator": "<<<FASTGPT_CHUNK>>>", "target_size": 800, "include_source": False})
        with self.connect() as db:
            db.execute("""INSERT INTO tasks
                (id,filename,pages,size,status,stage,created_at,updated_at,settings,mode,input_sha256,parse_profile)
                VALUES (?,?,?,?, 'queued','等待 Worker',?,?,?,?,?,?)""",
                (task_id, filename, pages, size, stamp, stamp, options, self.settings.mode, content_hash,
                 json.dumps({"base_url": self.settings.mineru_base_url, "backend": self.settings.mineru_backend,
                             "parse_method": self.settings.parse_method, "language": self.settings.language})))

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id FROM tasks WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE tasks SET status='processing',stage='准备解析',progress=10,updated_at=? WHERE id=?",
                       (now(), row["id"]))
        return self.get(row["id"])

    def recover(self):
        with self.connect() as db:
            db.execute("""UPDATE tasks SET status='queued',stage='恢复上游任务查询',updated_at=?
                WHERE status='processing' AND mode='remote' AND upstream_id IS NOT NULL""", (now(),))
            db.execute("""UPDATE tasks SET status='failed',stage='提交状态待确认',error_code='submission_uncertain',
                error='提交期间 Worker 中断，上游可能已接收；请确认后再重新提交。',updated_at=?
                WHERE status='processing' AND mode='remote' AND submission_started=1""", (now(),))
            db.execute("""UPDATE tasks SET status='failed',stage='任务已中断',
                error='Worker 中断，原文件已保留，请重试。',updated_at=? WHERE status='processing'""", (now(),))

    def progress(self, task_id, stage, progress):
        with self.connect() as db:
            db.execute("UPDATE tasks SET stage=?,progress=?,updated_at=? WHERE id=?", (stage, progress, now(), task_id))

    def complete(self, task_id, markdown, metadata=None):
        with self.connect() as db:
            task = db.execute("SELECT mode,settings FROM tasks WHERE id=?", (task_id,)).fetchone()
            options = json.loads(task["settings"])
            separator = options["separator"]
            counter = 1
            while options["separator"] in markdown:
                counter += 1
                options["separator"] = f"{separator}_{counter}"
            metadata = metadata or {}
            if counter > 1:
                metadata.setdefault("warnings", []).append("默认分隔符出现在正文中，已自动选择不冲突的分隔符。")
            db.execute("""UPDATE tasks SET status='completed',stage='演示处理完成',progress=100,
                markdown=?,revision=revision+1,error=NULL,error_code=NULL,submission_started=0,
                metadata=?,settings=?,updated_at=? WHERE id=?""",
                (markdown, json.dumps(metadata, ensure_ascii=False), json.dumps(options), now(), task_id))
            if task["mode"] == "remote":
                db.execute("UPDATE tasks SET stage='真实解析完成' WHERE id=?", (task_id,))

    def fail(self, task_id, message, code="processing_failed"):
        with self.connect() as db:
            db.execute("UPDATE tasks SET status='failed',stage='处理失败',error=?,error_code=?,updated_at=? WHERE id=?",
                       (message, code, now(), task_id))

    def submission(self, task_id, started):
        with self.connect() as db:
            db.execute("UPDATE tasks SET submission_started=?,updated_at=? WHERE id=?", (int(started), now(), task_id))

    def attach_upstream(self, task_id, upstream_id):
        with self.connect() as db:
            db.execute("UPDATE tasks SET upstream_id=?,submission_started=0,updated_at=? WHERE id=?",
                       (upstream_id, now(), task_id))

    def set_cache_key(self, task_id, key):
        with self.connect() as db:
            db.execute("UPDATE tasks SET cache_key=? WHERE id=?", (key, task_id))

    def save(self, task_id, markdown, options, revision):
        with self.connect() as db:
            changed = db.execute("""UPDATE tasks SET markdown=?,settings=?,revision=revision+1,
                edited=CASE WHEN markdown != ? THEN 1 ELSE edited END,updated_at=?
                WHERE id=? AND revision=? AND status='completed'""",
                (markdown, json.dumps(options, ensure_ascii=False), markdown, now(), task_id, revision)).rowcount
        return changed == 1

    def retry(self, task_id, allow_resubmit=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task or task["status"] != "failed":
                return False
            uncertain = task["submission_started"] or task["error_code"] == "upstream_expired"
            if uncertain and not allow_resubmit:
                return False
            if allow_resubmit or task["error_code"] == "upstream_task_failed":
                db.execute("UPDATE tasks SET upstream_id=NULL,submission_started=0,cache_key=NULL WHERE id=?", (task_id,))
            return db.execute("""UPDATE tasks SET status='queued',stage='等待重试',progress=0,
                error=NULL,error_code=NULL,attempts=attempts+1,updated_at=? WHERE id=? AND status='failed'""",
                (now(), task_id)).rowcount == 1
