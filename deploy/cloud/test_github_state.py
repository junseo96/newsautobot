"""State checkpoint selection and download tests; no live GitHub requests."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
import zipfile

import github_state as state


ENVIRONMENT = {'GITHUB_REPOSITORY':'owner/newsautobot', 'GITHUB_RUN_ID':'200',
               'GITHUB_RUN_ATTEMPT':'1', 'GITHUB_TOKEN':'synthetic-github-token'}
CIPHERTEXT = b'age-encryption.org/v1\nsynthetic encrypted state only\n'


class Response(io.BytesIO):
    def __init__(self, payload, status=200):
        super().__init__(payload)
        self.status = status


def run(run_id, status='completed', conclusion='success'):
    return {'id':run_id, 'status':status, 'conclusion':conclusion,
            'head_branch':'main', 'event':'schedule'}


def job(conclusion='success'):
    return {'name':'cycle', 'status':'completed', 'conclusion':conclusion}


def archive(entries=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as package:
        for name, value in (entries or [('state.tar.age', CIPHERTEXT)]):
            package.writestr(name, value)
    return output.getvalue()


def artifact(artifact_id=10, source=199, *, expired=False, created='2026-10-15T00:00:00Z', body=None):
    payload = body if body is not None else archive()
    return {'id':artifact_id, 'name':state.ARTIFACT, 'expired':expired,
            'created_at':created, 'workflow_run':{'id':source},
            'size_in_bytes':len(payload), 'digest':'sha256:' + hashlib.sha256(payload).hexdigest()}


class Transport:
    def __init__(self, runs=None, artifacts=None, payload=None, *, redirected=True, jobs=None):
        self.runs = runs if runs is not None else [run(200, 'in_progress', None), run(199)]
        self.artifacts = artifacts if artifacts is not None else [artifact()]
        self.payload = payload if payload is not None else archive()
        self.jobs = jobs or {}
        self.redirected = redirected
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        assert 0 < timeout <= 30
        url = urlsplit(request.full_url)
        if url.hostname == 'download.example':
            assert request.get_header('Authorization') is None
            return Response(self.payload)
        assert url.hostname == 'api.github.com'
        assert request.get_header('Authorization') == 'Bearer synthetic-github-token'
        if '/actions/workflows/' in url.path:
            return Response(json.dumps({'workflow_runs':self.runs}).encode())
        if '/jobs' in url.path:
            identifier = int(url.path.split('/')[-2])
            return Response(json.dumps({'jobs':self.jobs.get(identifier, [job()])}).encode())
        if url.path.endswith('/artifacts'):
            return Response(json.dumps({'artifacts':self.artifacts}).encode())
        if url.path.endswith('/zip'):
            if self.redirected:
                raise HTTPError(request.full_url, 302, 'Found',
                                {'Location':'https://download.example/private-checkpoint?signature=private'}, io.BytesIO())
            return Response(self.payload)
        raise AssertionError('Unexpected fake transport request')


class GitHubStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='github-state-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.destination = self.root/'state.tar.age'

    def download(self, transport=None, environment=None):
        return state.GitHubState(environment or ENVIRONMENT, transport or Transport()).download(self.destination)

    def assert_blocked(self, transport, reason):
        with self.assertRaisesRegex(state.StateDownloadError, reason) as failure:
            self.download(transport)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertNotIn('synthetic-github-token', str(failure.exception))
        self.assertNotIn('https://', str(failure.exception))

    def test_redirect_uses_token_only_for_github_and_retains_encrypted_file(self):
        transport = Transport()
        result = self.download(transport)
        self.assertEqual(result, {'artifact_id':10, 'source_run_id':199})
        self.assertEqual(self.destination.read_bytes(), CIPHERTEXT)
        self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode), 0o600)
        self.assertEqual(len([request for request in transport.requests if request.get_header('Authorization')]), 4)
        self.assertIsNone(transport.requests[-1].get_header('Authorization'))
        self.assertTrue(all(request.get_method() == 'GET' for request in transport.requests))
        self.assertEqual(list(self.root.iterdir()), [self.destination])

    def test_direct_authenticated_github_zip_response_is_supported(self):
        self.download(Transport(redirected=False))
        self.assertEqual(self.destination.read_bytes(), CIPHERTEXT)

    def test_failed_prior_runtime_blocks_even_if_it_uploaded_newer_state(self):
        transport = Transport(runs=[run(199, conclusion='failure'), run(198)],
                              artifacts=[artifact(source=199), artifact(9, source=198)])
        self.assert_blocked(transport, 'did not finish successfully')
        self.assertFalse(any(request.full_url.endswith('/zip') for request in transport.requests))

    def test_cancelled_started_job_and_active_prior_run_block(self):
        for prior in (run(199, conclusion='cancelled'), run(199, 'in_progress', None)):
            with self.subTest(prior=prior):
                self.assert_blocked(Transport(runs=[prior, run(198)], jobs={199:[job('cancelled')]}),
                                    'did not finish successfully')

    def test_disabled_successful_workflow_with_skipped_cycle_is_skipped(self):
        transport = Transport(runs=[run(199), run(198)], jobs={199:[job('skipped')]},
                              artifacts=[artifact(source=198)])
        self.assertEqual(self.download(transport)['source_run_id'], 198)

    def test_pending_concurrency_cancellation_without_jobs_is_skipped(self):
        transport = Transport(runs=[run(199, conclusion='cancelled'), run(198)], jobs={199:[]},
                              artifacts=[artifact(source=198)])
        self.assertEqual(self.download(transport)['source_run_id'], 198)

    def test_skipped_global_run_and_newer_queued_run_do_not_hide_previous_state(self):
        transport = Transport(runs=[run(201, 'queued', None), run(200, 'in_progress', None),
                                    run(199, conclusion='skipped'), run(198)],
                              artifacts=[artifact(source=198)])
        self.assertEqual(self.download(transport)['source_run_id'], 198)

    def test_newer_started_runtime_and_old_run_rerun_are_rejected(self):
        self.assert_blocked(Transport(runs=[run(201, 'in_progress', None), run(199)]), 'newer runtime has started')
        transport = Transport()
        with self.assertRaisesRegex(state.StateDownloadError, 'reruns require explicit bootstrap'):
            self.download(transport, {**ENVIRONMENT, 'GITHUB_RUN_ATTEMPT':'2'})
        self.assertEqual(transport.requests, [])

    def test_newer_cancelled_or_disabled_unexecuted_run_does_not_block_active_cycle(self):
        for newer, jobs in ((run(201, conclusion='cancelled'), []),
                            (run(201), [job('skipped')]),
                            (run(201, conclusion='skipped'), [])):
            with self.subTest(newer=newer, jobs=jobs):
                transport = Transport(runs=[newer, run(200, 'in_progress', None), run(199)], jobs={201:jobs})
                self.assertEqual(self.download(transport)['source_run_id'], 199)
                self.destination.unlink()
        self.assert_blocked(Transport(runs=[run(201, conclusion='cancelled'), run(199)],
                                      jobs={201:[job('cancelled')]}), 'newer runtime has started')

    def test_missing_prior_runtime_does_not_auto_bootstrap_from_random_artifact(self):
        self.assert_blocked(Transport(runs=[run(200, 'in_progress', None)]), 'explicit bootstrap is required')

    def test_expired_latest_artifact_is_not_replaced_with_older_state(self):
        self.assert_blocked(Transport(artifacts=[artifact(10, expired=True), artifact(9)]), 'artifact expired')

    def test_deleted_latest_artifact_is_detected_by_previous_run_identity(self):
        self.assert_blocked(Transport(artifacts=[artifact(9, source=198)]), 'does not belong')
        self.assert_blocked(Transport(artifacts=[]), 'artifact is missing')

    def test_latest_artifact_uses_creation_time_then_identifier(self):
        transport = Transport(artifacts=[artifact(11, created='2026-10-14T00:00:00Z'), artifact(9), artifact(10)])
        self.assertEqual(self.download(transport)['artifact_id'], 10)

    def test_runs_and_artifacts_are_paginated_without_older_fallback(self):
        class Pages(Transport):
            def open(inner, request, timeout):
                path = urlsplit(request.full_url).path
                if '/actions/workflows/' in path:
                    inner.requests.append(request)
                    rows = [run(199, conclusion='skipped'), run(198, conclusion='skipped')] if 'page=1' in request.full_url else [run(197)]
                    return Response(json.dumps({'workflow_runs':rows}).encode())
                if path.endswith('/artifacts'):
                    inner.requests.append(request)
                    rows = [artifact(1, source=190), artifact(2, source=191)] if 'page=1' in request.full_url else [artifact(20, source=197)]
                    return Response(json.dumps({'artifacts':rows}).encode())
                return super().open(request, timeout)
        with patch.object(state, 'PAGE_SIZE', 2):
            self.assertEqual(self.download(Pages()), {'artifact_id':20, 'source_run_id':197})

    def test_unsafe_redirect_and_anonymous_redirect_failure_do_not_leak(self):
        class Unsafe(Transport):
            def open(inner, request, timeout):
                if request.full_url.endswith('/zip'):
                    raise HTTPError(request.full_url, 302, 'private body', {'Location':'http://download.example/private'}, io.BytesIO())
                return super().open(request, timeout)
        self.assert_blocked(Unsafe(), 'Invalid GitHub artifact download location')
        class SecondRedirect(Transport):
            def open(inner, request, timeout):
                if urlsplit(request.full_url).hostname == 'download.example':
                    self.assertIsNone(request.get_header('Authorization'))
                    raise HTTPError(request.full_url, 302, 'private body', {'Location':'https://other.example/private'}, io.BytesIO())
                return super().open(request, timeout)
        self.assert_blocked(SecondRedirect(), 'download failed')

    def test_bad_digest_bad_zip_unencrypted_and_extra_entries_are_rejected(self):
        values = [b'not a zip', archive([('state.tar.age', b'plain database')]),
                  archive([('../state.tar.age', CIPHERTEXT)]),
                  archive([('state.tar.age', CIPHERTEXT), ('other.txt', b'private')])]
        for payload in values:
            with self.subTest(payload=payload[:20]):
                self.assert_blocked(Transport(payload=payload, artifacts=[artifact(body=payload)]),
                                    'could not be restored|not an age-encrypted|must contain only')
        self.assert_blocked(Transport(artifacts=[{**artifact(), 'digest':'sha256:' + '0'*64}]), 'checksum mismatch')

    def test_symlink_entry_and_oversized_state_are_rejected(self):
        link = zipfile.ZipInfo('state.tar.age'); link.external_attr = (stat.S_IFLNK | 0o777) << 16
        payload = archive([(link, CIPHERTEXT)])
        self.assert_blocked(Transport(payload=payload, artifacts=[artifact(body=payload)]), 'Invalid encrypted state archive entry')
        self.assert_blocked(Transport(artifacts=[{**artifact(), 'size_in_bytes':state.MAX_BYTES + 1}]), 'supported size')

    def test_existing_destination_is_never_overwritten_or_downloaded(self):
        self.destination.write_bytes(b'existing state')
        transport = Transport()
        with self.assertRaisesRegex(state.StateDownloadError, 'already exists'):
            self.download(transport)
        self.assertEqual(transport.requests, [])
        self.assertEqual(self.destination.read_bytes(), b'existing state')

    def test_network_errors_and_cli_diagnostics_hide_token_url_and_body(self):
        transport = Transport()
        transport.open = lambda *args, **kwargs: (_ for _ in ()).throw(URLError('https://private.example/synthetic-github-token'))
        self.assert_blocked(transport, 'metadata could not be read')
        output = io.StringIO(); errors = io.StringIO()
        with patch.dict(os.environ, ENVIRONMENT, clear=True), patch.object(state, 'build_opener', return_value=transport), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            result = state.main(['download', '--destination', str(self.destination)])
        self.assertEqual(result, 2)
        self.assertEqual(output.getvalue(), '')
        self.assertNotIn('synthetic-github-token', errors.getvalue())
        self.assertNotIn('https://', errors.getvalue())


if __name__ == '__main__':
    unittest.main()
