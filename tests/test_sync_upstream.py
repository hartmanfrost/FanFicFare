# -*- coding: utf-8 -*-
"""scripts/sync-upstream.sh against local bare repositories: it must
never push away commits on origin's fb2 that the local fb2 doesn't have
(pushed from another clone), and its fb2 push after a rebase is a
--force-with-lease on the origin fb2 it fetched.

Needs git and bash (skipped without them, e.g. in the image build)."""
import os
import shutil
import subprocess

import pytest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'scripts', 'sync-upstream.sh')

pytestmark = pytest.mark.skipif(
    not (shutil.which('git') and shutil.which('bash') and os.path.isfile(SCRIPT)),
    reason='needs git, bash and scripts/sync-upstream.sh')


class Repos(object):
    """U.git (upstream, main), O.git (the fork: main, fb2), clone L of
    fb2 with the upstream remote, as the user's checkout."""

    def __init__(self, tmp_path):
        self.root = tmp_path
        home = tmp_path / 'home'
        home.mkdir()
        (home / '.gitconfig').write_text(u'')
        self.env = dict(os.environ,
                        HOME=str(home), GIT_CONFIG_GLOBAL=str(home / '.gitconfig'),
                        GIT_CONFIG_NOSYSTEM='1',
                        GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t',
                        GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t')
        self.env.pop('GIT_DIR', None)
        self.env.pop('GIT_WORK_TREE', None)
        self.U = str(tmp_path / 'U.git')
        self.O = str(tmp_path / 'O.git')
        self.git(None, 'init', '-q', '--bare', self.U)
        self.git(None, 'init', '-q', '--bare', self.O)
        seed = str(tmp_path / 'seed')
        self.git(None, 'init', '-q', seed)
        self.write(seed, 'calibre-plugin/__init__.py',
                   u'__version__ = (4, 63, 4)\nFB2_FORK_REVISION = 1\n')
        self.commit(seed, 'README', u'upstream\n', 'A: upstream base')
        self.git(seed, 'push', '-q', self.U, 'HEAD:refs/heads/main')
        self.git(seed, 'push', '-q', self.O, 'HEAD:refs/heads/main')
        self.commit(seed, 'FORK', u'fb2\n', 'F: fork commit')
        self.git(seed, 'push', '-q', self.O, 'HEAD:refs/heads/fb2')
        self.L = self.clone('L')
        self.git(self.L, 'remote', 'add', 'upstream', self.U)
        self.git(self.L, 'fetch', '-q', '--no-tags', 'upstream')
        self.git(self.L, 'branch', '-q', 'main', 'origin/main')

    def git(self, cwd, *args, **kw):
        return subprocess.run(['git'] + list(args), cwd=cwd, env=self.env, check=kw.get('check', True),
                              capture_output=True, text=True).stdout.strip()

    def write(self, repo, name, text):
        path = os.path.join(repo, name)
        if os.path.dirname(name):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(text)

    def commit(self, repo, name, text, msg):
        self.write(repo, name, text)
        self.git(repo, 'add', name)
        self.git(repo, 'commit', '-q', '-m', msg)
        return self.git(repo, 'rev-parse', 'HEAD')

    def clone(self, name, branch='fb2', url=None):
        path = str(self.root / name)
        self.git(None, 'clone', '-q', '-b', branch, url or self.O, path)
        return path

    def push_from_elsewhere(self, name='L2'):
        "Another clone pushes commit X to origin's fb2."
        other = self.clone(name)
        x = self.commit(other, 'FIX_X', u'x\n', 'X: fix pushed from elsewhere')
        self.git(other, 'push', '-q', 'origin', 'fb2')
        return x

    def upstream_moves(self, name='UW', msg='Y: upstream change'):
        uw = self.clone(name, branch='main', url=self.U)
        y = self.commit(uw, name + '.txt', u'y\n', msg)
        self.git(uw, 'push', '-q', 'origin', 'main')
        return y

    def sync(self, *args):
        return subprocess.run(['bash', SCRIPT, '--no-test'] + list(args), cwd=self.L,
                              env=self.env, capture_output=True, text=True)

    def origin_fb2(self):
        return self.git(self.O, 'rev-parse', 'fb2')

    def on_origin_fb2(self, commit):
        return subprocess.run(['git', 'merge-base', '--is-ancestor', commit, 'fb2'],
                              cwd=self.O, env=self.env).returncode == 0


@pytest.fixture
def repos(tmp_path):
    return Repos(tmp_path)


@pytest.mark.parametrize('args', [['--push'], ['--push', '--merge']])
def test_sync_refuses_to_drop_commits_pushed_elsewhere(repos, args):
    repos.commit(repos.L, 'LOCAL', u'l\n', 'Z: local commit')
    x = repos.push_from_elsewhere()
    repos.upstream_moves()
    before = repos.origin_fb2()
    r = repos.sync(*args)
    assert r.returncode != 0, r.stdout
    assert 'pushed from elsewhere' in r.stderr
    assert 'X: fix pushed from elsewhere' in r.stderr
    assert repos.origin_fb2() == before and repos.on_origin_fb2(x)


def test_sync_nothing_to_sync_fast_forwards_instead_of_force_pushing(repos):
    "fb2 only behind origin's: fast-forward it, push nothing."
    x = repos.push_from_elsewhere()
    r = repos.sync('--push')
    assert r.returncode == 0, r.stderr
    assert 'fast-forwarding fb2' in r.stdout
    assert 'nothing to sync' in r.stdout
    assert 'forced update' not in r.stdout + r.stderr
    assert repos.on_origin_fb2(x)
    assert repos.git(repos.L, 'rev-parse', 'fb2') == repos.origin_fb2()


def test_sync_rebase_pushes_with_lease_on_fetched_origin(repos):
    old = repos.origin_fb2()
    y = repos.upstream_moves()
    r = repos.sync()
    assert r.returncode == 0, r.stderr
    assert 'git push --force-with-lease=fb2:%s origin fb2' % old in r.stdout
    ## something is pushed after the fetch: the printed push is refused
    x = repos.push_from_elsewhere()
    p = subprocess.run(['git', 'push', '--force-with-lease=fb2:%s' % old, 'origin', 'fb2'],
                       cwd=repos.L, env=repos.env, capture_output=True, text=True)
    assert p.returncode != 0 and 'stale info' in p.stderr
    assert repos.on_origin_fb2(x)

    ## sync again: X isn't known locally, so it stops
    r = repos.sync('--push')
    assert r.returncode != 0 and 'pushed from elsewhere' in r.stderr
    assert repos.on_origin_fb2(x)


def test_sync_rebase_push(repos):
    y = repos.upstream_moves()
    r = repos.sync('--push')
    assert r.returncode == 0, r.stderr
    assert repos.origin_fb2() == repos.git(repos.L, 'rev-parse', 'fb2')
    assert repos.on_origin_fb2(y)
    assert repos.git(repos.O, 'log', '-1', '--format=%s', 'fb2') == 'F: fork commit'


def test_sync_twice_before_pushing(repos):
    """A rebase that wasn't pushed, upstream moves on, sync again: the
    old origin fb2 is only in the backup, which is fine."""
    repos.upstream_moves('UW1', 'Y1')
    r = repos.sync()
    assert r.returncode == 0, r.stderr
    y2 = repos.upstream_moves('UW2', 'Y2')
    r = repos.sync('--push')
    assert r.returncode == 0, r.stderr
    assert repos.on_origin_fb2(y2)
    assert repos.origin_fb2() == repos.git(repos.L, 'rev-parse', 'fb2')

    ## and once more with upstream unchanged: nothing to push
    r = repos.sync('--push')
    assert r.returncode == 0 and 'nothing to sync' in r.stdout
    assert 'git push' not in r.stdout


def test_sync_merge_never_forces(repos):
    y = repos.upstream_moves()
    r = repos.sync('--merge')
    assert r.returncode == 0, r.stderr
    assert 'force' not in r.stdout
    assert 'git push origin fb2' in r.stdout
    r = subprocess.run(['git', 'push', 'origin', 'fb2'], cwd=repos.L, env=repos.env,
                       capture_output=True, text=True)
    assert r.returncode == 0 and 'forced update' not in r.stderr
    assert repos.on_origin_fb2(y)


def test_sync_merge_after_unpushed_rebase_stops(repos):
    repos.upstream_moves('UW1', 'Y1')
    assert repos.sync().returncode == 0          # rebase, not pushed
    repos.upstream_moves('UW2', 'Y2')
    r = repos.sync('--merge', '--push')
    assert r.returncode != 0 and "--merge doesn't do" in r.stderr


def test_sync_continue_after_conflict_uses_fetched_lease(repos):
    "--continue (no fetch) still checks origin's fb2 and leases on it."
    old = repos.origin_fb2()
    ## the fork and upstream change the same file
    repos.commit(repos.L, 'README', u'fork\n', 'G: fork edits README')
    uw = repos.clone('UW', branch='main', url=repos.U)
    repos.commit(uw, 'README', u'upstream 2\n', 'Y: upstream edits README')
    repos.git(uw, 'push', '-q', 'origin', 'main')
    r = repos.sync()
    assert r.returncode != 0 and 'stopped on a conflict' in r.stderr
    repos.write(repos.L, 'README', u'resolved\n')
    repos.git(repos.L, 'add', 'README')
    subprocess.run(['git', '-c', 'core.editor=true', 'rebase', '--continue'], cwd=repos.L,
                   env=repos.env, check=True, capture_output=True)
    r = repos.sync('--continue')
    assert r.returncode == 0, r.stderr
    assert 'git push --force-with-lease=fb2:%s origin fb2' % old in r.stdout
