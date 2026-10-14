"""Explicitly gated cloud entrypoint; diagnostics never print credential values."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading

PROJECT = Path(__file__).resolve().parents[2]
REQUIRED_ENV = (
    'NEWS_CODEX_API_KEY', 'NEWS_GMAIL_CLIENT_ID', 'NEWS_GMAIL_CLIENT_SECRET',
    'NEWS_GMAIL_REFRESH_TOKEN', 'NEWS_TELEGRAM_BOT_TOKEN', 'NEWS_TELEGRAM_CHAT_ID',
    'NEWS_DART_KEY', 'NEWS_GRID_URL', 'NEWS_GRID_TOKEN',
)
DATABASES = {
    'rss-news-monitor.db': {'articles', 'delivery_history', 'decision_history'},
    'v11/queue.db': {'jobs', 'state', 'completed_versions'},
    'grid-bridge/grid.db': {'observations'},
}


def data_directory():
    return Path(os.environ.get('NEWS_DATA_DIR', '/var/lib/newsflow/state')).resolve()


def migration_metadata(data):
    """Validate restore metadata shape; the marker alone is not proof of integrity."""
    migration = json.loads((Path(data) / '.news-state-migration.json').read_text(encoding='utf-8'))
    if not isinstance(migration, dict):
        raise ValueError('invalid restoration marker')
    source_root = migration.get('source_root')
    if not isinstance(source_root, str) or not source_root.strip():
        raise ValueError('missing source root')
    from pathlib import PureWindowsPath
    if not Path(source_root).is_absolute() and not PureWindowsPath(source_root).is_absolute():
        raise ValueError('source root must be absolute')
    if '..' in PureWindowsPath(source_root).parts or '..' in Path(source_root).parts:
        raise ValueError('source root must not contain traversal')
    if migration.get('classification') != 'private-operational-state':
        raise ValueError('invalid state classification')
    digest = migration.get('archive_manifest_sha256')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', digest):
        raise ValueError('invalid archive manifest checksum')
    return migration


def configure_migration():
    try:
        migration = migration_metadata(data_directory())
    except (OSError, ValueError, TypeError):
        raise RuntimeError('State restoration metadata is unavailable or invalid; no service was started') from None
    # New artifacts retain the cloud path; old evidence is mapped on read. The
    # restored archive's source root is authoritative over stale environment settings.
    os.environ['NEWS_LEGACY_ROOT'] = migration['source_root']


def preflight(project=PROJECT, data=None, *, require_runtime=True):
    """Check restored state and runtime without creating DBs or sending requests."""
    data = Path(data or data_directory()).resolve()
    project = Path(project).resolve()
    problems = []
    if require_runtime:
        for name in REQUIRED_ENV:
            if not os.environ.get(name, '').strip():
                problems.append('missing environment variable: ' + name)
        if os.environ.get('NEWS_GMAIL_TRANSPORT') != 'gmail_api':
            problems.append('NEWS_GMAIL_TRANSPORT must be gmail_api for this deployment')
        for command in ('pwsh', 'codex'):
            if shutil.which(command) is None:
                problems.append('missing executable: ' + command)
    configured_data = os.environ.get('NEWS_DATA_DIR')
    if configured_data and not Path(configured_data).is_absolute():
        problems.append('NEWS_DATA_DIR must be absolute')
    if (project / 'work').resolve() != data / 'work':
        problems.append('project work directory must resolve to the persistent data directory')
    try:
        migration_metadata(data)
    except (OSError, ValueError, TypeError):
        problems.append('state restoration marker is missing or invalid')
    for relative, expected in DATABASES.items():
        path = data / 'work' / relative
        if not path.is_file():
            problems.append('missing restored database: ' + relative)
            continue
        try:
            with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as connection:
                if connection.execute('PRAGMA quick_check').fetchone() != ('ok',):
                    raise ValueError('integrity')
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not expected <= tables:
                    raise ValueError('schema')
        except (sqlite3.Error, ValueError):
            problems.append('restored database integrity/schema check failed: ' + relative)
    if not (data / 'work/runs').is_dir():
        problems.append('restored immutable run/receipt directory is missing')
    return {'ready': not problems, 'checks': 'local prerequisites only; remote authentication is unverified', 'problems': problems}


def audit_state():
    """Validate receipt/history consistency without exposing private audit output."""
    try:
        result = subprocess.run([sys.executable, str(PROJECT / 'outputs/rss-news-monitor/audit_migration.py')],
                                cwd=PROJECT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding='utf-8', errors='replace', timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('Restored state audit could not complete; no service was started') from None
    if result.returncode:
        raise RuntimeError('Restored state audit failed; no service was started')


def authenticate_model():
    # Pass the key only on stdin; never include it in argv, logs or exceptions.
    try:
        result = subprocess.run(['codex', 'login', '--with-api-key'],
                                input=os.environ['NEWS_CODEX_API_KEY'] + '\n',
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('Codex login could not complete; check the configured model credential') from None
    if result.returncode:
        raise RuntimeError('Codex login failed; no service was started')


def run(*, seconds=None):
    if seconds is not None and (type(seconds) is not int or not 1 <= seconds <= 3600):
        raise ValueError('Cycle duration must be an integer from 1 to 3600 seconds')
    stopped = threading.Event()
    service = None

    def request_stop(*_):
        stopped.set()
        if service is not None:
            service.stop.set()

    for event in (signal.SIGTERM, signal.SIGINT):
        signal.signal(event, request_stop)
    if os.environ.get('NEWS_SERVICE_ENABLED', '').lower() != 'true':
        print(json.dumps({'status': 'paused', 'message': 'Restore and verify operating history, configure credentials, and stop the old sender before enabling NEWS_SERVICE_ENABLED.'}), flush=True)
        if seconds is None:
            stopped.wait()
        return 0
    report = preflight()
    print(json.dumps(report), flush=True)
    if not report['ready']:
        return 2
    if stopped.is_set():
        return 0
    configure_migration()
    audit_state()
    if stopped.is_set():
        return 0
    authenticate_model()
    if stopped.is_set():
        return 0
    sys.path.insert(0, str(PROJECT / 'outputs/rss-news-monitor'))
    from v11_service import Service
    service = Service(PROJECT)
    if stopped.is_set():
        service.stop.set()
        return 0
    if os.environ.get('NEWS_MODEL'):
        service.config['model'] = os.environ['NEWS_MODEL']
    timer = None
    try:
        if seconds is not None:
            timer = threading.Timer(seconds, request_stop)
            timer.daemon = True
            timer.start()
            print(json.dumps({'status': 'started', 'mode': 'cycle', 'seconds': seconds}), flush=True)
        # Service.run waits for its started loops to drain after stop is set.
        # A cycle deadline never kills an in-flight sender or its receipt write.
        service.run()
    finally:
        request_stop()
        if timer is not None:
            timer.cancel()
            if timer.ident is not None:
                timer.join()
            print(json.dumps({'status': 'stopped', 'mode': 'cycle'}), flush=True)
    return 0


def cycle_duration(value):
    try:
        seconds = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError('Cycle duration must be an integer from 1 to 3600 seconds') from None
    if not 1 <= seconds <= 3600:
        raise argparse.ArgumentTypeError('Cycle duration must be an integer from 1 to 3600 seconds')
    return seconds


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'audit', 'run', 'cycle'])
    parser.add_argument('--seconds', type=cycle_duration,
                        help='Cycle duration before graceful drain (1-3600; default 600)')
    args = parser.parse_args(argv)
    if args.seconds is not None and args.command != 'cycle':
        parser.error('--seconds is only valid with cycle')
    if args.command == 'check':
        report = preflight()
        print(json.dumps(report))
        return 0 if report['ready'] else 2
    try:
        if args.command == 'audit':
            report = preflight(require_runtime=False)
            print(json.dumps(report), flush=True)
            if not report['ready']:
                return 2
            configure_migration()
            audit_state()
            print(json.dumps({'audit': 'passed', 'remote_authentication': 'unverified'}))
            return 0
        return run(seconds=args.seconds if args.seconds is not None else 600) if args.command == 'cycle' else run()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
