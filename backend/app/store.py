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
            db.execute("""CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, filename TEXT NOT NULL, pages INTEGER NOT NULL,
                size INTEGER NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, markdown TEXT, settings TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0, edited INTEGER NOT NULL DEFAULT 0,
                error TEXT, attempts INTEGER NOT NULL DEFAULT 1
            )""")

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
        return task

    def get(self, task_id):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def list(self):
        with self.connect() as db:
            return [self.decode(row) for row in db.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT 100"
            ).fetchall()]

    def create(self, task_id, filename, pages, size):
        stamp = now()
        options = json.dumps({"separator": "<<<FASTGPT_CHUNK>>>", "target_size": 800, "include_source": False})
        with self.connect() as db:
            db.execute("""INSERT INTO tasks
                (id,filename,pages,size,status,stage,created_at,updated_at,settings)
                VALUES (?,?,?,?, 'queued','等待 Worker',?,?,?)""",
                (task_id, filename, pages, size, stamp, stamp, options))

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id FROM tasks WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE tasks SET status='processing',stage='生成演示内容',progress=20,updated_at=? WHERE id=?",
                       (now(), row["id"]))
        return self.get(row["id"])

    def recover(self):
        with self.connect() as db:
            db.execute("""UPDATE tasks SET status='failed',stage='任务已中断',
                error='Worker 中断，原文件已保留，请重试。',updated_at=? WHERE status='processing'""", (now(),))

    def progress(self, task_id, stage, progress):
        with self.connect() as db:
            db.execute("UPDATE tasks SET stage=?,progress=?,updated_at=? WHERE id=?", (stage, progress, now(), task_id))

    def complete(self, task_id, markdown):
        with self.connect() as db:
            db.execute("""UPDATE tasks SET status='completed',stage='演示处理完成',progress=100,
                markdown=?,revision=revision+1,error=NULL,updated_at=? WHERE id=?""", (markdown, now(), task_id))

    def fail(self, task_id, message):
        with self.connect() as db:
            db.execute("UPDATE tasks SET status='failed',stage='处理失败',error=?,updated_at=? WHERE id=?",
                       (message, now(), task_id))

    def save(self, task_id, markdown, options, revision):
        with self.connect() as db:
            changed = db.execute("""UPDATE tasks SET markdown=?,settings=?,revision=revision+1,
                edited=CASE WHEN markdown != ? THEN 1 ELSE edited END,updated_at=?
                WHERE id=? AND revision=? AND status='completed'""",
                (markdown, json.dumps(options, ensure_ascii=False), markdown, now(), task_id, revision)).rowcount
        return changed == 1

    def retry(self, task_id):
        with self.connect() as db:
            return db.execute("""UPDATE tasks SET status='queued',stage='等待重试',progress=0,
                error=NULL,attempts=attempts+1,updated_at=? WHERE id=? AND status='failed'""",
                (now(), task_id)).rowcount == 1
