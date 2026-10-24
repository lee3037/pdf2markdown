import json
import sqlite3
from contextlib import contextmanager


class Store:
    def __init__(self, directory):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "gateway.sqlite3"
        with self.db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, body TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def all(self):
        with self.db() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM tasks ORDER BY created_at, rowid")]

    def get(self, task_id):
        with self.db() as db:
            row = db.execute("SELECT body FROM tasks WHERE id=?", (task_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def add(self, task, limit):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            tasks = [json.loads(row[0]) for row in db.execute("SELECT body FROM tasks")]
            if any(t.get("uncertain") for t in tasks):
                return "submission_uncertain"
            if sum(t["status"] in {"pending", "processing"} for t in tasks) >= limit:
                return "queue_full"
            db.execute("INSERT INTO tasks(id,body) VALUES (?,?)", (task["task_id"], json.dumps(task)))
        return None

    def update(self, task_id, **fields):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            task = json.loads(row[0]) | fields
            db.execute("UPDATE tasks SET body=? WHERE id=?", (json.dumps(task), task_id))
        return task

    def recover(self):
        for task in self.all():
            if task["phase"] == "submitting" and not task.get("upstream_id"):
                self.update(task["task_id"], status="failed", phase="failed", uncertain=True, error="submission_uncertain")


def atomic_json(path, value):
    temporary = path.with_suffix(".part")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
