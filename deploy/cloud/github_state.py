"""Download the preceding successful GitHub runtime's encrypted state only.

No fallback to older state is allowed after missing artifacts, failed runs, or
ambiguous execution. Bootstrap/recovery is an explicit separate workflow path.
The GitHub token is used only against api.github.com, never a download redirect.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile

API = 'https://api.github.com'
WORKFLOW = 'news-runtime.yml'
ARTIFACT = 'newsautobot-state'
STATE_FILE = 'state.tar.age'
MAX_BYTES = 2 * 1024 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_PAGES = 100
PAGE_SIZE = 100


class StateDownloadError(RuntimeError):
    """Only fixed diagnostic text; never private upstream data or URLs."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _positive_id(value):
    if isinstance(value, bool) or not re.fullmatch(r'[1-9][0-9]*', str(value)):
        raise StateDownloadError('Invalid GitHub execution metadata')
    return int(value)


def _created(value):
    try:
        date = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if date.tzinfo is None:
            raise ValueError
        return date.timestamp()
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise StateDownloadError('Invalid GitHub artifact timestamp') from None


def _download_url(value):
    try:
        if not isinstance(value, str) or any(ord(c) <= 32 or ord(c) == 127 for c in value) or '\\' in value:
            raise ValueError
        url = urlsplit(value)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment or '@' in url.netloc:
            raise ValueError
        url.port
    except ValueError:
        raise StateDownloadError('Invalid GitHub artifact download location') from None
    return value


class GitHubState:
    def __init__(self, environment=None, opener=None):
        environment = os.environ if environment is None else environment
        self.repository = environment.get('GITHUB_REPOSITORY', '')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*', self.repository):
            raise StateDownloadError('GITHUB_REPOSITORY must identify the current repository')
        self.token = environment.get('GITHUB_TOKEN', '')
        if not self.token or any(ord(c) <= 32 or ord(c) == 127 for c in self.token):
            raise StateDownloadError('GITHUB_TOKEN is missing or invalid')
        self.run_id = _positive_id(environment.get('GITHUB_RUN_ID', ''))
        if _positive_id(environment.get('GITHUB_RUN_ATTEMPT', '1')) != 1:
            raise StateDownloadError('Runtime reruns require explicit bootstrap recovery; older state will not be restored')
        self.opener = opener or build_opener(_NoRedirect())

    def _request(self, path):
        # Every authenticated URL is constructed locally, never copied from an
        # API body or a redirect Location.
        return Request(API + '/repos/' + self.repository + path, headers={
            'Authorization': 'Bearer ' + self.token,
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'newsautobot-state',
            'Accept-Encoding': 'identity',
        })

    def _json(self, path):
        try:
            with self.opener.open(self._request(path), timeout=30) as response:
                if response.status != 200:
                    raise StateDownloadError('GitHub state metadata request failed')
                raw = response.read(MAX_JSON_BYTES + 1)
            if len(raw) > MAX_JSON_BYTES:
                raise StateDownloadError('GitHub state metadata exceeded its size limit')
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise StateDownloadError('Invalid GitHub state metadata')
            return value
        except HTTPError as error:
            error.close()
            raise StateDownloadError('GitHub state metadata request failed') from None
        except StateDownloadError:
            raise
        except Exception:
            raise StateDownloadError('GitHub state metadata could not be read') from None

    def _pages(self, path, key):
        separator = '&' if '?' in path else '?'
        for page in range(1, MAX_PAGES + 1):
            result = self._json(path + separator + f'per_page={PAGE_SIZE}&page={page}')
            rows = result.get(key)
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise StateDownloadError('Invalid GitHub state list')
            yield rows
            if len(rows) < PAGE_SIZE:
                return
        raise StateDownloadError('GitHub state history exceeded its inspection limit')

    def previous_run(self):
        path = '/actions/workflows/' + WORKFLOW + '/runs?branch=main'
        # GitHub lists workflow runs newest first. Continue past skipped runs
        # and queued newer runs; never skip an uncertain earlier execution.
        for rows in self._pages(path, 'workflow_runs'):
            eligible = []
            for run in rows:
                if run.get('head_branch') != 'main' or run.get('event') not in ('schedule', 'workflow_dispatch'):
                    continue
                run_id = _positive_id(run.get('id'))
                if run_id == self.run_id:
                    continue
                if run_id > self.run_id:
                    if run.get('status') not in ('queued', 'requested', 'waiting', 'pending'):
                        if self._never_executed(run):
                            continue
                        raise StateDownloadError('A newer runtime has started; stale execution cannot restore state')
                    continue
                if run.get('status') == 'completed' and run.get('conclusion') == 'skipped':
                    continue
                eligible.append(run)
            for previous in sorted(eligible, key=lambda run: _positive_id(run['id']), reverse=True):
                if self._never_executed(previous):
                    continue
                if previous.get('status') != 'completed' or previous.get('conclusion') != 'success':
                    raise StateDownloadError('Previous runtime did not finish successfully; explicit bootstrap recovery is required')
                return _positive_id(previous['id'])
        raise StateDownloadError('No successful previous runtime exists; explicit bootstrap is required')

    def _never_executed(self, run):
        if run.get('status') != 'completed':
            return False
        jobs = []
        for rows in self._pages('/actions/runs/' + str(_positive_id(run['id'])) + '/jobs?filter=latest', 'jobs'):
            jobs.extend(rows)
        # GitHub coalesces queued runs before allocating a runner. Do not treat
        # cancellation of a started job as equivalent to this empty-job case.
        if not jobs:
            return run.get('conclusion') in ('cancelled', 'skipped')
        return all(job.get('name') == 'cycle' and job.get('status') == 'completed'
                   and job.get('conclusion') == 'skipped' for job in jobs)

    def latest_artifact(self, previous_run):
        artifacts = []
        for rows in self._pages('/actions/artifacts?name=' + ARTIFACT, 'artifacts'):
            artifacts.extend(row for row in rows if row.get('name') == ARTIFACT)
        if not artifacts:
            raise StateDownloadError('Latest encrypted state artifact is missing; older state will not be used')
        latest = max(artifacts, key=lambda row: (_created(row.get('created_at')), _positive_id(row.get('id'))))
        if latest.get('expired') is not False:
            raise StateDownloadError('Latest encrypted state artifact expired; older state will not be used')
        source = latest.get('workflow_run')
        if not isinstance(source, dict) or _positive_id(source.get('id')) != previous_run:
            raise StateDownloadError('Latest encrypted state does not belong to the preceding successful runtime')
        size = latest.get('size_in_bytes')
        if type(size) is not int or size <= 0 or size > MAX_BYTES:
            raise StateDownloadError('Encrypted state artifact exceeds its supported size')
        return latest

    def _archive(self, artifact):
        request = self._request('/actions/artifacts/' + str(_positive_id(artifact['id'])) + '/zip')
        try:
            return self.opener.open(request, timeout=30)
        except HTTPError as error:
            try:
                if error.code != 302:
                    raise StateDownloadError('Encrypted state artifact could not be downloaded')
                location = _download_url(error.headers.get('Location'))
            finally:
                error.close()
        # A fresh Request intentionally contains no Authorization header. Signed
        # download URLs are never printed, persisted, or followed with a token.
        return self.opener.open(Request(location, headers={
            'User-Agent': 'newsautobot-state', 'Accept-Encoding': 'identity',
        }), timeout=30)

    def download(self, destination):
        destination = Path(destination)
        if destination.exists() or destination.is_symlink():
            raise StateDownloadError('State download destination already exists')
        previous = self.previous_run()
        artifact = self.latest_artifact(previous)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.news-state-download-', dir=destination.parent) as temporary:
                archive = Path(temporary) / 'download.zip'
                checksum = hashlib.sha256(); size = 0
                with self._archive(artifact) as response, archive.open('xb') as output:
                    if response.status != 200:
                        raise StateDownloadError('Encrypted state download was rejected')
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise StateDownloadError('Encrypted state download exceeded its size limit')
                        checksum.update(chunk); output.write(chunk)
                expected = artifact.get('digest')
                if expected is not None:
                    if not isinstance(expected, str) or not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', expected):
                        raise StateDownloadError('Invalid encrypted artifact digest metadata')
                    if checksum.hexdigest() != expected.removeprefix('sha256:').lower():
                        raise StateDownloadError('Encrypted state artifact checksum mismatch')
                payload = Path(temporary) / STATE_FILE
                with zipfile.ZipFile(archive) as package:
                    entries = package.infolist()
                    if len(entries) != 1 or entries[0].filename != STATE_FILE or entries[0].is_dir():
                        raise StateDownloadError('State artifact must contain only state.tar.age')
                    entry = entries[0]
                    mode = stat.S_IFMT(entry.external_attr >> 16)
                    if mode not in (0, stat.S_IFREG) or entry.flag_bits & 1 or not 0 < entry.file_size <= MAX_BYTES:
                        raise StateDownloadError('Invalid encrypted state archive entry')
                    with package.open(entry) as source, payload.open('xb') as output:
                        total = 0
                        while chunk := source.read(1024 * 1024):
                            total += len(chunk)
                            if total > MAX_BYTES:
                                raise StateDownloadError('Encrypted state payload exceeded its size limit')
                            output.write(chunk)
                    if total != entry.file_size:
                        raise StateDownloadError('Incomplete encrypted state payload')
                with payload.open('rb') as source:
                    prefix = source.read(64)
                if not prefix.startswith((b'age-encryption.org/v1\n', b'-----BEGIN AGE ENCRYPTED FILE-----\n')):
                    raise StateDownloadError('State artifact is not an age-encrypted payload')
                payload.chmod(0o600)
                # Hard-link creation is atomic and refuses a destination created
                # after the initial check. Both paths share the same filesystem.
                os.link(payload, destination)
        except HTTPError as error:
            error.close()
            raise StateDownloadError('Encrypted state artifact download failed') from None
        except StateDownloadError:
            raise
        except Exception:
            raise StateDownloadError('Encrypted state artifact could not be restored') from None
        return {'artifact_id': _positive_id(artifact['id']), 'source_run_id': previous}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    download = commands.add_parser('download')
    download.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = GitHubState().download(args.destination)
    except StateDownloadError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps({'downloaded': True, **result}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
