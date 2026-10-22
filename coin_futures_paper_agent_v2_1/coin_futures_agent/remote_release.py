"""Stdlib approved-release protocol. Local click only; no application/update HTTP API."""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import urllib.request
import urllib.error
import zipfile

from local_update import UpdateError

REPO = 'amen090104-collab/coin-futures-agent'
REQUIRED_CHECKS = {'test (ubuntu-latest, Python 3.12)', 'test (windows-latest, Python 3.13.5)'}


def version(value):
    match = re.fullmatch(r'v?(5)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', str(value))
    if not match: raise UpdateError('UPDATE_BLOCKED_INVALID_V5_VERSION')
    return tuple(map(int, match.groups()))


def source_digest(raw_archive):
    with zipfile.ZipFile(io.BytesIO(raw_archive)) as z:
        files = {}
        for info in z.infolist():
            if info.is_dir(): continue
            if info.filename in files or info.filename.startswith('/') or '..' in info.filename.split('/'):
                raise UpdateError('UPDATE_BLOCKED_INVALID_SOURCE_ARCHIVE')
            files[info.filename] = hashlib.sha256(z.read(info)).hexdigest()
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class GitHub:
    def __init__(self, root): self.root = root; self._auth = os.environ.get('GH_TOKEN') or None; self._tried_auth = False

    def _credentials(self):
        if self._tried_auth: return self._auth
        self._tried_auth = True
        # Existing HTTPS Git credential manager only. Never print its output or
        # read .env/report tokens. GCM interactive prompts are disabled.
        try:
            p = subprocess.run(['git', 'credential', 'fill'], input=b'protocol=https\nhost=github.com\npath='+REPO.encode()+b'.git\n\n',
                cwd=self.root, capture_output=True, timeout=15,
                env=dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never'))
            if p.returncode == 0:
                values = dict(line.split('=', 1) for line in p.stdout.decode('utf-8').splitlines() if '=' in line)
                self._auth = values.get('password')
        except (OSError, ValueError, subprocess.TimeoutExpired): pass
        return self._auth

    def _get(self, path, token=None):
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'coin-agent-approved-updater'}
        if token: headers['Authorization'] = 'Bearer '+token
        request = urllib.request.Request('https://api.github.com/repos/'+REPO+'/'+path, headers=headers)
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.geturl().split('/')[2] != 'api.github.com':
                raise UpdateError('UPDATE_BLOCKED_UNEXPECTED_API_REDIRECT')
            return json.load(response)

    def get(self, path):
        try: return self._get(path, self._auth)
        except urllib.error.HTTPError as exc:
            if exc.code not in (401, 404): raise UpdateError('UPDATE_BLOCKED_GITHUB_API_ERROR') from None
            if exc.code == 404 and path:
                try:
                    self._get('')  # A public repo with no release doesn't need credentials.
                    return None
                except urllib.error.HTTPError: pass
            token = self._credentials()
            if token:
                try: return self._get(path, token)
                except urllib.error.HTTPError as inner:
                    if inner.code == 404: return None
                    raise UpdateError('UPDATE_BLOCKED_GITHUB_AUTH_OR_RATE_LIMIT') from None
            # SSH-only origin users can reuse an existing gh login, without
            # extracting or logging its token. No new credentials are requested.
            if shutil.which('gh'):
                result = subprocess.run(['gh', 'api', 'repos/'+REPO+'/'+path], cwd=self.root,
                    capture_output=True, timeout=20)
                if result.returncode == 0:
                    try: return json.loads(result.stdout)
                    except ValueError: pass
            raise UpdateError('UPDATE_BLOCKED_PRIVATE_API_CREDENTIAL_UNAVAILABLE') from None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise UpdateError('UPDATE_BLOCKED_OFFLINE') from None


def verify_review(pin, api):
    match = re.fullmatch(r'https://github.com/'+re.escape(REPO)+r'/pull/([0-9]+)', pin.get('review_url', ''))
    if not match or pin.get('reviewed') is not True or not re.fullmatch('[0-9a-f]{40}', pin.get('sha', '')):
        raise UpdateError('UPDATE_BLOCKED_UNAPPROVED')
    pr = api('pulls/'+match[1]); data = api('commits/'+pin['sha']+'/check-runs')
    runs = {}
    for rec in (data or {}).get('check_runs', []):
        if rec.get('app', {}).get('slug') != 'github-actions': continue
        if rec.get('id', 0) >= runs.get(rec.get('name'), {}).get('id', -1): runs[rec.get('name')] = rec
    if (not pr or not pr.get('merged_at') or pin['sha'] not in {pr.get('merge_commit_sha'), pr.get('head', {}).get('sha')}
            or not REQUIRED_CHECKS <= runs.keys() or any(runs[name].get('status') != 'completed'
                or runs[name].get('conclusion') != 'success' for name in REQUIRED_CHECKS)):
        raise UpdateError('UPDATE_BLOCKED_UNAPPROVED')


def approved(release, api):
    if not release or release.get('draft') or release.get('prerelease'):
        return None
    tag = release.get('tag_name', '')
    version(tag)
    try:
        data = json.loads(release['body']); pin = data['approved_release']
        if (data.get('manifest_version') != 2 or data.get('execution_mode') != 'PAPER_SHADOW_ONLY'
                or data.get('version') != tag[1:] or not re.fullmatch(r'v5\.[0-9]+\.[0-9]+', tag)
                or not re.fullmatch('[0-9a-f]{64}', data.get('source_tree_sha256', ''))):
            raise ValueError
        verify_review(pin, api)
        return {**pin, 'version': data['version'], 'source_tree_sha256': data['source_tree_sha256'],
                'acceptance': {'software_review_and_ci_verified': True, 'model_profitability_verified': False}}
    except (KeyError, TypeError, ValueError):
        raise UpdateError('UPDATE_BLOCKED_UNAPPROVED') from None
