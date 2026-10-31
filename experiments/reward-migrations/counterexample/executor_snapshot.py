"""Bounded, read-only SQLite execution for a fixed-output reward audit.

This is an evaluator for public SQL, not a general hostile-code sandbox.
Results use BIRD's set-of-row-tuples comparison: order and multiplicity are
ignored. Numeric equality follows Python's exact int/float equality. We expose
the limits of that comparator rather than claiming SQL semantic equivalence.
"""

import base64
from datetime import datetime
from functools import lru_cache
from hashlib import sha256
import json
import math
import platform
from pathlib import Path
import re
import sqlite3
import time


COMPARATOR = "bird-row-set-v1"
CLOCK = "2026-10-31 00:00:00"
CLOCK_ADAPTER = "sqlite-fixed-utc-v1"
MAX_ROWS = 100_000
MAX_SQL_BYTES = 200_000
TIMEOUT = 10.0


def file_hash(path):
    h = sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cell(value):
    if value is None:
        return ["null"]
    if isinstance(value, bytes):
        return ["blob", base64.b64encode(value).decode("ascii")]
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isinf(value):
            return ["infinity", "+" if value > 0 else "-"]
        numerator, denominator = value.as_integer_ratio() if isinstance(value, float) else (value, 1)
        return ["number", str(numerator), str(denominator)]
    return ["text", value]


def row_key(row):
    return json.dumps([cell(v) for v in row], ensure_ascii=False, separators=(",", ":"))


def display(value):
    if isinstance(value, float) and math.isinf(value):
        return {"nonfinite": "+Infinity" if value > 0 else "-Infinity"}
    return {"blob_base64": base64.b64encode(value).decode("ascii")} if isinstance(value, bytes) else value


@lru_cache(maxsize=1)
def runtime_fingerprint():
    with sqlite3.connect(":memory:") as connection:
        source = connection.execute("SELECT sqlite_source_id()").fetchone()[0]
        options = sorted(row[0] for row in connection.execute("PRAGMA compile_options"))
    return {"sqlite_version": sqlite3.sqlite_version, "sqlite_source_id": source,
            "compile_options_sha256": sha256(json.dumps(options, separators=(",", ":")).encode()).hexdigest(),
            "python": platform.python_version(), "machine": platform.machine()}


def execute(db_path, sql, timeout=TIMEOUT, max_rows=MAX_ROWS, clock=CLOCK):
    datetime.strptime(clock, "%Y-%m-%d %H:%M:%S")
    started = time.monotonic()
    base = {"query_sha256": sha256(sql.encode("utf-8")).hexdigest(), "status": None}

    def finish(status, **kwargs):
        return dict(base, status=status, seconds=round(time.monotonic() - started, 6), **kwargs)

    if len(sql.encode("utf-8")) > MAX_SQL_BYTES:
        return finish("limit", error="SQL byte limit exceeded")
    if not sql.strip():
        return finish("sql_error", error="No SQL statement")
    if re.search(r"\bload_extension\s*\(", sql, re.I):
        return finish("unsupported", error="Extension loading is not an evaluation operation")
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
               sqlite3.SQLITE_RECURSIVE}
    nondeterministic = {"random", "randomblob", "changes", "total_changes", "last_insert_rowid", "load_extension"}
    denied = []

    def authorize(action, arg1, arg2, db_name, trigger_name):
        if action not in allowed or (action == sqlite3.SQLITE_FUNCTION and str(arg2).lower() in nondeterministic):
            denied.append([action, arg1, arg2])
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    connection, calendar = None, None
    try:
        path = Path(db_path).resolve(strict=True)
        connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1)
        # Apple's system Python can be compiled without extension loading.
        if hasattr(connection, "enable_load_extension"):
            connection.enable_load_extension(False)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA cache_size=-4096")
        connection.execute("PRAGMA hard_heap_limit=268435456")
        # SQLite's date functions can read the wall clock even when SQL contains
        # no literal 'now'. Resolve runtime arguments, then delegate the calendar
        # arithmetic to an untouched SQLite connection with bound parameters.
        calendar = sqlite3.connect(":memory:")
        connection.create_function("current_timestamp", 0, lambda: clock)
        connection.create_function("current_date", 0, lambda: clock[:10])
        connection.create_function("current_time", 0, lambda: clock[11:])

        def calendar_function(name):
            def call(*original):
                args = list(original)
                if name == "timediff":
                    indices = range(len(args))
                else:
                    position = 1 if name == "strftime" else 0
                    # strftime() has no format and returns NULL natively.
                    if len(args) == position and not (name == "strftime" and not args):
                        args.append(clock)
                    elif len(args) > position and isinstance(args[position], str) and args[position].lower() in ("subsec", "subsecond"):
                        args.insert(position, clock)
                    indices = [position] if len(args) > position else []
                    modifiers = args[position + 1:]
                    if any(isinstance(x, str) and x.lower() in ("localtime", "utc") for x in modifiers):
                        denied.append(["timezone_modifier", name])
                        raise ValueError("Timezone-dependent modifiers are outside the fixed-UTC adapter")
                for index in indices:
                    if isinstance(args[index], str) and args[index].lower() == "now":
                        args[index] = clock
                placeholders = ",".join("?" for _ in args)
                return calendar.execute(f"SELECT {name}({placeholders})", args).fetchone()[0]
            return call

        for name in ("date", "time", "datetime", "julianday", "unixepoch", "strftime", "timediff"):
            connection.create_function(name, -1, calendar_function(name))
        connection.set_authorizer(authorize)
        connection.set_progress_handler(lambda: int(time.monotonic() - started > timeout), 10000)
        cursor = connection.execute(sql)
        if cursor.description is None:
            return finish("sql_error", error="Statement did not produce a query result")
        unique, preview, count = set(), [], 0
        for row in cursor:
            count += 1
            if count > max_rows:
                return finish("limit", error="Result row limit exceeded")
            unique.add(row_key(row))
            if len(preview) < 5:
                preview.append([display(v) for v in row])
            if time.monotonic() - started > timeout:
                return finish("timeout", error="Wall-clock query budget exceeded")
        # A newline is safe because json.dumps escapes all embedded newlines.
        serialized = "\n".join(sorted(unique)).encode("utf-8")
        return finish("ok", result_sha256=sha256(serialized).hexdigest(),
                      rows=count, distinct_rows=len(unique), preview=preview,
                      columns=[item[0] for item in cursor.description or []])
    except sqlite3.Error as exc:
        message = str(exc)
        status = "unsupported" if denied else "sql_error"
        if "interrupted" in message.lower():
            status = "timeout"
        if "out of memory" in message.lower() or "too big" in message.lower():
            status = "limit"
        return finish(status, error=message[:500], denied=denied[:3])
    except (OSError, MemoryError, OverflowError) as exc:
        return finish("runtime_error", error=str(exc)[:500])
    finally:
        if connection is not None:
            connection.close()
        if calendar is not None:
            calendar.close()


def reward(candidate, reference):
    """An unresolved computation is not evidence that a model was wrong."""
    if reference["status"] != "ok":
        return None
    if candidate["status"] == "sql_error":
        return 0
    if candidate["status"] != "ok":
        return None
    return int(candidate["result_sha256"] == reference["result_sha256"]
               and candidate["distinct_rows"] == reference["distinct_rows"])
