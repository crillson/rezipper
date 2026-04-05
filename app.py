import base64
import json
import os
import queue
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, Generator, List, Optional

import smtplib
import zipfile
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, Response, jsonify, redirect, render_template, request
from werkzeug.security import check_password_hash, generate_password_hash


DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/config"))
PORT = int(os.environ.get("PORT", "5063"))
TRASH_DIR = DATA_DIR / ".trash"
DB_PATH = CONFIG_DIR / "jobs.db"
LOG_PATH = CONFIG_DIR / "system.log"
AUTH_PATH = CONFIG_DIR / "auth.json"

DEFAULT_TRASH_RETENTION = os.environ.get("TRASH_RETENTION", "24h")
DEFAULT_CRON = os.environ.get("CRON_SCHEDULE", "0 0 * * *")
DEFAULT_SCAN_SORT = "name"
DEFAULT_WORK_DIR = os.environ.get("WORK_DIR", "/jobs")
DEFAULT_COMPRESSION_THREADS = os.environ.get("COMPRESSION_THREADS", "0")
ALLOWED_LANGUAGES = {"en", "sv"}
SUPPORTED_FORMATS = [".zip", ".7z", ".rar"]
SUPPORTED_FORMATS_SET = set(SUPPORTED_FORMATS)
WHATS_NEW_PATH = Path(os.environ.get("WHATS_NEW_PATH", "/app/WHATS_NEW.md"))

app = Flask(__name__)


def parse_duration_to_hours(value: str) -> float:
    value = (value or "24h").strip().lower()
    if value.endswith("h"):
        return float(value[:-1])
    if value.endswith("d"):
        return float(value[:-1]) * 24.0
    if value.endswith("m"):
        return float(value[:-1]) / 60.0
    return float(value)


def duration_hours_to_string(hours: float) -> str:
    if hours >= 24 and hours % 24 == 0:
        return f"{int(hours / 24)}d"
    if hours >= 1 and float(hours).is_integer():
        return f"{int(hours)}h"
    return f"{int(hours * 60)}m"


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self._init()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with self.lock:
            conn = self._connect()
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    original_size INTEGER NOT NULL,
                    new_size INTEGER NOT NULL,
                    savings_bytes INTEGER NOT NULL,
                    savings_percent REAL NOT NULL,
                    ratio REAL NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_filename ON jobs(filename);

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            conn.commit()
            conn.close()

    def set_setting(self, key: str, value: str):
        with self.lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            conn.commit()
            conn.close()

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self.lock:
            conn = self._connect()
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            conn.close()
        if row:
            return row["value"]
        return default

    def get_all_settings(self) -> Dict[str, str]:
        with self.lock:
            conn = self._connect()
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            conn.close()
        return {r["key"]: r["value"] for r in rows}

    def insert_job(self, payload: Dict):
        with self.lock:
            conn = self._connect()
            conn.execute(
                """
                INSERT INTO jobs(
                    filename, original_size, new_size, savings_bytes,
                    savings_percent, ratio, duration_ms, status, error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["filename"],
                    payload["original_size"],
                    payload["new_size"],
                    payload["savings_bytes"],
                    payload["savings_percent"],
                    payload["ratio"],
                    payload["duration_ms"],
                    payload["status"],
                    payload.get("error_message"),
                    payload["created_at"],
                ),
            )
            conn.commit()
            conn.close()

    def history(self, page: int, per_page: int, search: str):
        offset = (page - 1) * per_page
        where = ""
        params: List = []
        if search:
            where = "WHERE filename LIKE ?"
            params.append(f"%{search}%")

        with self.lock:
            conn = self._connect()
            total = conn.execute(f"SELECT COUNT(*) AS c FROM jobs {where}", params).fetchone()["c"]
            rows = conn.execute(
                f"""
                SELECT id, filename, original_size, new_size, savings_percent, ratio, status, duration_ms, created_at
                FROM jobs
                {where}
                ORDER BY datetime(created_at) DESC
                LIMIT ? OFFSET ?
                """,
                params + [per_page, offset],
            ).fetchall()
            conn.close()
        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max((total + per_page - 1) // per_page, 1),
        }


class LogBus:
    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.listeners: List[queue.Queue] = []

    def write(self, level: str, message: str):
        line = f"[{datetime.utcnow().isoformat(timespec='seconds')}] [{level}] {message}"
        with self.lock:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            for q in self.listeners:
                q.put(line)

    def stream(self) -> Generator[str, None, None]:
        q: queue.Queue = queue.Queue()
        with self.lock:
            self.listeners.append(q)
        try:
            if self.log_path.exists():
                tail = self.log_path.read_text(encoding="utf-8").splitlines()[-30:]
                for line in tail:
                    yield f"data: {line}\n\n"
            while True:
                try:
                    line = q.get(timeout=15)
                    yield f"data: {line}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with self.lock:
                if q in self.listeners:
                    self.listeners.remove(q)


@dataclass
class State:
    running: bool = False
    paused: bool = False
    current_file: Optional[str] = None
    total_files: int = 0
    processed_files: int = 0
    last_run: Optional[str] = None


class RezipperService:
    def __init__(self, db: Database, logger: LogBus):
        self.db = db
        self.logger = logger
        self.state = State()
        self.lock = threading.Lock()
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.worker: Optional[threading.Thread] = None

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        TRASH_DIR.mkdir(parents=True, exist_ok=True)

    def _sort_files(self, files: List[Path], mode: str) -> List[Path]:
        if mode == "size":
            return sorted(files, key=lambda p: p.stat().st_size)
        if mode == "date":
            return sorted(files, key=lambda p: p.stat().st_mtime)
        return sorted(files, key=lambda p: p.name.lower())

    def _get_work_root(self) -> Path:
        configured = (self.db.get_setting("work_dir", DEFAULT_WORK_DIR) or DEFAULT_WORK_DIR).strip()
        if not configured:
            configured = DEFAULT_WORK_DIR
        root = Path(configured)
        if not root.is_absolute():
            root = (DATA_DIR / root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _build_work_dir(self, source: Path) -> Path:
        rel = source.relative_to(DATA_DIR)
        safe_name = rel.as_posix().replace("/", "__")
        stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        return self._get_work_root() / f"{safe_name}__{stamp}"

    def _compression_threads(self) -> int:
        configured = (self.db.get_setting("compression_threads", DEFAULT_COMPRESSION_THREADS) or "0").strip()
        try:
            value = int(configured)
        except ValueError:
            value = 0

        max_threads = os.cpu_count() or 1
        if value <= 0:
            return 0
        return min(value, max_threads)

    def _debug_enabled(self) -> bool:
        return parse_bool(self.db.get_setting("debug_logging", "false"), default=False)

    def _debug_log(self, message: str):
        if self._debug_enabled():
            self.logger.write("DEBUG", message)

    def _run_command(self, cmd: List[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
        cwd_str = str(cwd) if cwd else None
        self._debug_log(f"Kör kommando: {' '.join(cmd)} (cwd={cwd_str or '<none>'})")
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)

        self._debug_log(
            f"Kommando klart (rc={result.returncode}): {' '.join(cmd)}"
            + (f" | stderr: {result.stderr.strip()[:400]}" if result.stderr else "")
        )
        return result

    def scan_files(self) -> List[Path]:
        sort_mode = self.db.get_setting("scan_sort", DEFAULT_SCAN_SORT)
        files: List[Path] = []
        for p in DATA_DIR.rglob("*"):
            if not p.is_file():
                continue
            if TRASH_DIR in p.parents:
                continue
            if p.suffix.lower() in SUPPORTED_FORMATS_SET:
                files.append(p)
        return self._sort_files(files, sort_mode)

    def start(self):
        with self.lock:
            if self.state.running:
                self.logger.write("INFO", "Körning ignorerad: redan aktiv.")
                return False
            files = self.scan_files()
            if not files:
                self.state = State(
                    running=False,
                    paused=False,
                    current_file=None,
                    total_files=0,
                    processed_files=0,
                    last_run=now_iso(),
                )
                self.logger.write(
                    "WARNING",
                    "Start avbruten: inga arkiv hittades. Kontrollera /data och filändelser (.zip/.7z/.rar).",
                )
                return False
            self.state = State(
                running=True,
                paused=False,
                current_file=None,
                total_files=len(files),
                processed_files=0,
                last_run=now_iso(),
            )
            self.pause_event.set()
            self.worker = threading.Thread(target=self._run, args=(files,), daemon=True)
            self.worker.start()
            threads = self._compression_threads()
            threads_text = str(threads) if threads > 0 else "auto"
            self.logger.write("INFO", f"Startar optimering. {len(files)} filer i kö.")
            self.logger.write("INFO", f"Komprimeringstrådar: {threads_text}")
            return True

    def debug_scan(self) -> Dict:
        files = self.scan_files()
        examples = [str(p.relative_to(DATA_DIR)) for p in files[:25]]
        return {
            "data_dir": str(DATA_DIR),
            "trash_dir": str(TRASH_DIR),
            "work_dir": str(self._get_work_root()),
            "compression_threads": self._compression_threads(),
            "scan_sort": self.db.get_setting("scan_sort", DEFAULT_SCAN_SORT),
            "supported_formats": SUPPORTED_FORMATS,
            "found_count": len(files),
            "examples": examples,
            "truncated": len(files) > len(examples),
        }

    def pause(self):
        with self.lock:
            self.state.paused = True
            self.pause_event.clear()
        self.logger.write("INFO", "Kön pausad via webbgränssnitt.")

    def resume(self):
        with self.lock:
            if not self.state.running:
                self.start()
                return
            self.state.paused = False
            self.pause_event.set()
        self.logger.write("INFO", "Kön återupptagen.")

    def status(self) -> Dict:
        with self.lock:
            payload = asdict(self.state)
        total = max(payload["total_files"], 1)
        payload["progress_percent"] = int((payload["processed_files"] / total) * 100)
        return payload

    def _run(self, files: List[Path]):
        for file in files:
            self.pause_event.wait()
            with self.lock:
                self.state.current_file = str(file.relative_to(DATA_DIR))
            self.logger.write("INFO", f"Bearbetar: {file.relative_to(DATA_DIR)}")
            self._process_single(file)
            with self.lock:
                self.state.processed_files += 1
                self.state.current_file = None

        with self.lock:
            self.state.running = False
            self.state.paused = False
            self.state.current_file = None
        self.logger.write("INFO", "Optimeringskön är färdig.")

    def _process_single(self, path: Path):
        start = time.time()
        original_size = path.stat().st_size
        rel_name = str(path.relative_to(DATA_DIR))
        work_dir: Optional[Path] = None
        try:
            work_dir = self._build_work_dir(path)
            work_dir.mkdir(parents=True, exist_ok=True)
            self._debug_log(f"Arbetsmapp: {work_dir}")
            optimized = work_dir / f"optimized{path.suffix.lower()}"
            self._debug_log(f"Tempfil för optimering: {optimized}")
            self._recompress(path, optimized, work_dir)
            self._crc_test(optimized)

            new_size = optimized.stat().st_size
            trash_target = self._move_original_to_trash(path)
            shutil.move(str(optimized), str(path))

            savings = original_size - new_size
            savings_percent = (savings / original_size * 100.0) if original_size else 0.0
            ratio = (original_size / new_size * 100.0) if new_size else 0.0
            self.db.insert_job(
                {
                    "filename": rel_name,
                    "original_size": original_size,
                    "new_size": new_size,
                    "savings_bytes": savings,
                    "savings_percent": round(savings_percent, 2),
                    "ratio": round(ratio, 2),
                    "duration_ms": int((time.time() - start) * 1000),
                    "status": "SUCCESS",
                    "error_message": None,
                    "created_at": now_iso(),
                }
            )
            self.logger.write(
                "INFO",
                f"Klar: {rel_name} ({original_size} -> {new_size} bytes, trash: {trash_target.name})",
            )
        except Exception as exc:
            self.db.insert_job(
                {
                    "filename": rel_name,
                    "original_size": original_size,
                    "new_size": original_size,
                    "savings_bytes": 0,
                    "savings_percent": 0.0,
                    "ratio": 100.0,
                    "duration_ms": int((time.time() - start) * 1000),
                    "status": "FAILED",
                    "error_message": str(exc),
                    "created_at": now_iso(),
                }
            )
            self.logger.write("ERROR", f"Fel vid {rel_name}: {exc}")
            send_critical_email(f"CRC/optimeringsfel för {rel_name}", str(exc))
        finally:
            if work_dir and work_dir.exists():
                shutil.rmtree(work_dir, ignore_errors=True)

    def _recompress(self, source: Path, target: Path, work_dir: Path):
        archive_type = source.suffix.lower()
        self._debug_log(f"Startar recompress för {source} ({archive_type})")
        thread_count = self._compression_threads()
        thread_hint = f" (threads={thread_count})" if thread_count > 0 else " (threads=auto)"
        self._debug_log(f"Komprimeringsinställning{thread_hint}")

        # ZIP kan hanteras utan externa binärer som fallback.
        if archive_type == ".zip" and not shutil.which("7z"):
            with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(
                target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
            ) as zout:
                for info in zin.infolist():
                    data = zin.read(info.filename)
                    zi = zipfile.ZipInfo(filename=info.filename, date_time=info.date_time)
                    zi.external_attr = info.external_attr
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    zout.writestr(zi, data)
            return

        # 7z krävs för .7z/.rar samt används för .zip när tillgänglig.
        if not shutil.which("7z"):
            raise RuntimeError("7z krävs för att optimera detta format.")

        extract_dir = work_dir / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)
        extract_cmd = ["7z", "x", "-y", f"-o{extract_dir}", str(source)]
        r = self._run_command(extract_cmd)
        if r.returncode != 0:
            raise RuntimeError(f"7z extract misslyckades: {r.stderr or r.stdout}")

        if archive_type in {".zip", ".7z"}:
            target_type = "zip" if archive_type == ".zip" else "7z"
            add_cmd = ["7z", "a", f"-t{target_type}", "-mx=9", str(target), "."]
            if thread_count > 0:
                add_cmd.insert(3, f"-mmt={thread_count}")
            r = self._run_command(add_cmd, cwd=extract_dir)
            if r.returncode != 0:
                raise RuntimeError(
                    f"7z komprimering misslyckades för {archive_type}: {r.stderr or r.stdout}"
                )
            return

        if archive_type == ".rar":
            if not shutil.which("rar"):
                raise RuntimeError(
                    "RAR-optimering kräver 'rar'-binär för ompackning (7z kan normalt inte skapa RAR)."
                )

            add_cmd = ["rar", "a", "-idq", "-m5", str(target), "."]
            if thread_count > 0:
                add_cmd.insert(3, f"-mt{thread_count}")
            r = self._run_command(add_cmd, cwd=extract_dir)
            if r.returncode != 0:
                raise RuntimeError(
                    f"RAR-komprimering misslyckades: {r.stderr or r.stdout}"
                )
            return

        raise RuntimeError(f"Format stöds inte: {archive_type}")

    def _crc_test(self, path: Path):
        if shutil.which("7z"):
            r = self._run_command(["7z", "t", str(path)])
            if r.returncode != 0:
                raise RuntimeError(f"CRC-test misslyckades: {r.stderr or r.stdout}")
            return

        if path.suffix.lower() != ".zip":
            raise RuntimeError("CRC-test för detta format kräver 7z.")

        with zipfile.ZipFile(path, "r") as zf:
            bad_file = zf.testzip()
            if bad_file:
                raise RuntimeError(f"CRC-test misslyckades på fil: {bad_file}")

    def _move_original_to_trash(self, source: Path) -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        rel = source.relative_to(DATA_DIR)
        safe_name = rel.as_posix().replace("/", "__")
        target = TRASH_DIR / f"{timestamp}__{safe_name}"
        shutil.move(str(source), str(target))
        return target

    def cleanup_trash(self):
        retention_raw = self.db.get_setting("trash_retention", DEFAULT_TRASH_RETENTION)
        retention_hours = parse_duration_to_hours(retention_raw)
        cutoff = datetime.utcnow() - timedelta(hours=retention_hours)
        removed = 0
        for item in TRASH_DIR.iterdir():
            if not item.is_file():
                continue
            mtime = datetime.utcfromtimestamp(item.stat().st_mtime)
            if mtime < cutoff:
                item.unlink(missing_ok=True)
                removed += 1
        if removed:
            self.logger.write("INFO", f"Rensade {removed} filer från .trash.")


db = Database(DB_PATH)
log_bus = LogBus(LOG_PATH)
service = RezipperService(db, log_bus)
scheduler = BackgroundScheduler(timezone="UTC")


def init_defaults():
    if db.get_setting("trash_retention") is None:
        db.set_setting("trash_retention", DEFAULT_TRASH_RETENTION)
    if db.get_setting("cron_schedule") is None:
        db.set_setting("cron_schedule", DEFAULT_CRON)
    if db.get_setting("scan_sort") is None:
        db.set_setting("scan_sort", DEFAULT_SCAN_SORT)
    if db.get_setting("work_dir") is None:
        db.set_setting("work_dir", DEFAULT_WORK_DIR)
    if db.get_setting("compression_threads") is None:
        db.set_setting("compression_threads", DEFAULT_COMPRESSION_THREADS)
    if db.get_setting("debug_logging") is None:
        db.set_setting("debug_logging", "false")
    if db.get_setting("language") is None:
        db.set_setting("language", "en")

    for key in [
        "smtp_host",
        "smtp_port",
        "smtp_user",
        "smtp_pass",
        "smtp_from",
        "smtp_to",
    ]:
        if db.get_setting(key) is None:
            db.set_setting(key, "")


def credentials_configured() -> bool:
    env_user = os.environ.get("AUTH_USER")
    env_pass = os.environ.get("AUTH_PASS")
    if env_user and env_pass:
        return True
    return AUTH_PATH.exists()


def verify_credentials(username: str, password: str) -> bool:
    env_user = os.environ.get("AUTH_USER")
    env_pass = os.environ.get("AUTH_PASS")
    if env_user and env_pass:
        return username == env_user and password == env_pass

    if not AUTH_PATH.exists():
        return False
    data = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    return username == data.get("username") and check_password_hash(data.get("password_hash", ""), password)


@app.before_request
def enforce_auth():
    allowed = {"setup", "setup_post", "static"}
    if request.endpoint in allowed:
        return None

    if not credentials_configured():
        return redirect("/setup")

    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return Response("Auth required", 401, {"WWW-Authenticate": "Basic realm='Rezipper'"})
    encoded = header.split(" ", 1)[1].strip()
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        return Response("Invalid auth", 401, {"WWW-Authenticate": "Basic realm='Rezipper'"})

    if not verify_credentials(username, password):
        return Response("Unauthorized", 401, {"WWW-Authenticate": "Basic realm='Rezipper'"})
    return None


def send_critical_email(subject: str, body: str):
    smtp_host = db.get_setting("smtp_host", "")
    smtp_port = db.get_setting("smtp_port", "")
    smtp_from = db.get_setting("smtp_from", "")
    smtp_to = db.get_setting("smtp_to", "")

    if not (smtp_host and smtp_port and smtp_from and smtp_to):
        return

    msg = EmailMessage()
    msg["Subject"] = f"[Rezipper] {subject}"
    msg["From"] = smtp_from
    msg["To"] = smtp_to
    msg.set_content(body)

    user = db.get_setting("smtp_user", "")
    password = db.get_setting("smtp_pass", "")

    try:
        with smtplib.SMTP(smtp_host, int(smtp_port), timeout=15) as server:
            server.starttls()
            if user:
                server.login(user, password)
            server.send_message(msg)
        log_bus.write("INFO", "Kritisk notis skickad via SMTP.")
    except Exception as exc:
        log_bus.write("ERROR", f"SMTP-notis misslyckades: {exc}")


def configure_scheduler():
    for job in scheduler.get_jobs():
        scheduler.remove_job(job.id)

    cron = db.get_setting("cron_schedule", DEFAULT_CRON)
    try:
        trigger = cron_trigger_from_expression(cron)
        scheduler.add_job(service.start, trigger, id="optimizer_cron", replace_existing=True)
        log_bus.write("INFO", f"Cron-schema laddat: {cron}")
    except Exception as exc:
        log_bus.write("ERROR", f"Ogiltigt cron-schema '{cron}': {exc}")

    scheduler.add_job(service.cleanup_trash, "interval", hours=1, id="trash_cleanup", replace_existing=True)


@app.get("/setup")
def setup():
    if credentials_configured():
        return redirect("/")
    return render_template("setup.html")


@app.post("/setup")
def setup_post():
    if credentials_configured():
        return jsonify({"ok": False, "error": "Already configured"}), 400
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if len(username) < 3 or len(password) < 6:
        return jsonify({"ok": False, "error": "username >=3 och password >=6 krävs"}), 400

    AUTH_PATH.write_text(
        json.dumps({"username": username, "password_hash": generate_password_hash(password)}),
        encoding="utf-8",
    )
    log_bus.write("INFO", "Basic Auth skapad via first-run setup.")
    return jsonify({"ok": True})


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def api_status():
    payload = service.status()
    payload["current_file"] = payload.get("current_file")
    return jsonify(payload)


@app.post("/api/start")
def api_start():
    started = service.start()
    status = service.status()
    if not started and status.get("total_files", 0) == 0:
        return jsonify(
            {
                "ok": False,
                "error_code": "no_files_found",
            }
        )
    return jsonify({"ok": started})


@app.post("/api/pause")
def api_pause():
    service.pause()
    return jsonify({"ok": True})


@app.post("/api/resume")
def api_resume():
    service.resume()
    return jsonify({"ok": True})


@app.get("/api/history")
def api_history():
    page = max(int(request.args.get("page", "1")), 1)
    per_page = min(max(int(request.args.get("per_page", "20")), 1), 100)
    search = request.args.get("search", "").strip()
    return jsonify(db.history(page=page, per_page=per_page, search=search))


@app.get("/api/settings")
def api_get_settings():
    settings = db.get_all_settings()
    settings.setdefault("trash_retention", DEFAULT_TRASH_RETENTION)
    settings.setdefault("cron_schedule", DEFAULT_CRON)
    settings.setdefault("scan_sort", DEFAULT_SCAN_SORT)
    settings.setdefault("work_dir", DEFAULT_WORK_DIR)
    settings.setdefault("compression_threads", DEFAULT_COMPRESSION_THREADS)
    settings.setdefault("debug_logging", "false")
    settings.setdefault("language", "en")
    if settings.get("language") not in ALLOWED_LANGUAGES:
        settings["language"] = "en"
    return jsonify(settings)


@app.post("/api/settings")
def api_set_settings():
    data = request.get_json(force=True)
    allowed = {
        "trash_retention",
        "cron_schedule",
        "scan_sort",
        "work_dir",
        "compression_threads",
        "debug_logging",
        "language",
        "smtp_host",
        "smtp_port",
        "smtp_user",
        "smtp_pass",
        "smtp_from",
        "smtp_to",
    }
    for k, v in data.items():
        if k in allowed:
            if k == "language":
                lang = str(v).strip().lower()
                db.set_setting("language", lang if lang in ALLOWED_LANGUAGES else "en")
                continue
            if k == "work_dir":
                work_dir = str(v).strip() or DEFAULT_WORK_DIR
                db.set_setting("work_dir", work_dir)
                continue
            if k == "compression_threads":
                max_threads = os.cpu_count() or 1
                try:
                    raw_value = int(str(v).strip() or "0")
                except ValueError:
                    raw_value = 0
                sanitized = max(0, min(raw_value, max_threads))
                db.set_setting("compression_threads", str(sanitized))
                continue
            if k == "debug_logging":
                db.set_setting("debug_logging", "true" if parse_bool(str(v)) else "false")
                continue
            db.set_setting(k, str(v))

    configure_scheduler()
    return jsonify({"ok": True})


@app.get("/api/log-stream")
def api_log_stream():
    return Response(log_bus.stream(), mimetype="text/event-stream")


@app.get("/api/debug/scan")
def api_debug_scan():
    return jsonify(service.debug_scan())


_cpu_lock = threading.Lock()
_prev_cpu_total: Optional[int] = None
_prev_cpu_idle: Optional[int] = None


def _read_cpu_times() -> Optional[tuple[int, int]]:
    try:
        line = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
        parts = line.split()
        if not parts or parts[0] != "cpu":
            return None
        values = [int(v) for v in parts[1:]]
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return total, idle
    except Exception:
        return None


def get_cpu_usage_percent() -> Optional[float]:
    global _prev_cpu_total, _prev_cpu_idle
    current = _read_cpu_times()
    if not current:
        return None

    total, idle = current
    with _cpu_lock:
        if _prev_cpu_total is None or _prev_cpu_idle is None:
            _prev_cpu_total = total
            _prev_cpu_idle = idle
            return None

        delta_total = total - _prev_cpu_total
        delta_idle = idle - _prev_cpu_idle
        _prev_cpu_total = total
        _prev_cpu_idle = idle

    if delta_total <= 0:
        return None
    usage = (1.0 - (delta_idle / delta_total)) * 100.0
    return max(0.0, min(100.0, usage))


def get_memory_snapshot() -> Dict[str, Optional[int]]:
    total = None
    available = None
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                total = int(line.split()[1]) * 1024
            elif line.startswith("MemAvailable:"):
                available = int(line.split()[1]) * 1024
        used = (total - available) if total is not None and available is not None else None
        return {"total": total, "available": available, "used": used}
    except Exception:
        return {"total": None, "available": None, "used": None}


def get_uptime_seconds() -> Optional[float]:
    try:
        value = Path("/proc/uptime").read_text(encoding="utf-8").split()[0]
        return float(value)
    except Exception:
        return None


def read_whats_new() -> str:
    try:
        if WHATS_NEW_PATH.exists():
            return WHATS_NEW_PATH.read_text(encoding="utf-8")
    except Exception:
        pass
    return "# pre-release-0.6\n\nNo release notes available."


@app.get("/api/system-status")
def api_system_status():
    cpu_percent = get_cpu_usage_percent()
    mem = get_memory_snapshot()
    load_1m, load_5m, load_15m = os.getloadavg()
    return jsonify(
        {
            "cpu_percent": round(cpu_percent, 1) if cpu_percent is not None else None,
            "cpu_cores": os.cpu_count() or 1,
            "load_avg": {
                "1m": round(load_1m, 2),
                "5m": round(load_5m, 2),
                "15m": round(load_15m, 2),
            },
            "memory": mem,
            "uptime_seconds": get_uptime_seconds(),
        }
    )


@app.get("/api/whats-new")
def api_whats_new():
    return jsonify({"version": "pre-release-0.6", "content": read_whats_new()})


def cron_trigger_from_expression(expr: str) -> CronTrigger:
    raw = (expr or "").strip()
    if not raw:
        raise ValueError("Tomt cron-schema")

    parts = raw.split()
    if len(parts) == 5:
        return CronTrigger.from_crontab(raw, timezone="UTC")

    if len(parts) in {6, 7}:
        normalized = ["*" if p == "?" else p for p in parts]
        kwargs = {
            "second": normalized[0],
            "minute": normalized[1],
            "hour": normalized[2],
            "day": normalized[3],
            "month": normalized[4],
            "day_of_week": normalized[5],
            "timezone": "UTC",
        }
        if len(normalized) == 7:
            kwargs["year"] = normalized[6]
        return CronTrigger(**kwargs)

    raise ValueError(
        f"Fel antal fält: {len(parts)}. Stöder 5-fälts crontab eller 6/7-fälts (Quartz-liknande)."
    )


def bootstrap():
    init_defaults()
    configure_scheduler()
    if not scheduler.running:
        scheduler.start()
    service.cleanup_trash()
    log_bus.write("INFO", "Rezipper startad.")


bootstrap()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)