import json, sqlite3
from datetime import datetime, timezone
from . import settings
def now(): return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
def connect():
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    c=sqlite3.connect(settings.DATA_DIR/"furcolor.sqlite3",check_same_thread=False);c.row_factory=sqlite3.Row;return c
def init():
    with connect() as c:
        c.executescript("""PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,source_dir TEXT NOT NULL DEFAULT '',edited_dir TEXT NOT NULL DEFAULT '',analysis_dir TEXT NOT NULL DEFAULT '',output_dir TEXT NOT NULL DEFAULT '',watermark_path TEXT NOT NULL DEFAULT '',manifest_path TEXT NOT NULL DEFAULT '',selection_mode TEXT NOT NULL DEFAULT 'negative',status TEXT NOT NULL DEFAULT 'configured',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS photos(id INTEGER PRIMARY KEY AUTOINCREMENT,project_id INTEGER NOT NULL,stem TEXT NOT NULL,source_path TEXT NOT NULL,selection TEXT NOT NULL DEFAULT 'unset',UNIQUE(project_id,stem));
        CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY AUTOINCREMENT,project_id INTEGER NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,progress REAL NOT NULL DEFAULT 0,log TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,project_id INTEGER,event TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL);""")
        cols={r[1] for r in c.execute("PRAGMA table_info(projects)")}
        if "manifest_path" not in cols:c.execute("ALTER TABLE projects ADD COLUMN manifest_path TEXT NOT NULL DEFAULT ''")
        c.execute("""UPDATE jobs SET status='failed',progress=1,
        log=CASE WHEN log='' THEN 'Interrupted by FurColor service restart.' ELSE log || char(10) || 'Interrupted by FurColor service restart.' END,
        updated_at=? WHERE status IN ('queued','running')""",(now(),))
def rows(sql,params=()):
    with connect() as c:return [dict(x) for x in c.execute(sql,params).fetchall()]
def one(sql,params=()):
    with connect() as c:
        x=c.execute(sql,params).fetchone();return dict(x) if x else None
def run(sql,params=()):
    with connect() as c:
        x=c.execute(sql,params);c.commit();return int(x.lastrowid)
def audit(pid,event,detail=None):run("INSERT INTO audit(project_id,event,detail,created_at) VALUES(?,?,?,?)",(pid,event,json.dumps(detail or {},ensure_ascii=False),now()))
