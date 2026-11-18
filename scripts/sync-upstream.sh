#!/usr/bin/env bash
# Bring the fork's fb2 branch up to date with upstream FanFicFare.
#
#   scripts/sync-upstream.sh [--merge] [--no-test] [--push]
#   scripts/sync-upstream.sh --continue [--no-test] [--push]
#
#   (default)   rebase fb2 onto upstream/main
#   --merge     merge upstream/main into fb2 instead (no force-push needed)
#   --continue  after resolving a conflict and finishing the rebase or merge
#               by hand: only test and print (or run) the pushes
#   --no-test   skip the unit tests and the plugin build
#   --push      run the pushes instead of printing them
#
# Steps:
#  1. Refuse to run with uncommitted changes to tracked files, or with a
#     rebase or merge in progress (except with --continue after it is done).
#  2. git fetch --no-tags from upstream (the remote is added if missing).
#     No tags: upstream's v* tags must not reach origin, where a pushed v*
#     tag starts an ash app-ci run.
#  3. Fast-forward the local main to upstream/main; main stays a plain copy
#     of upstream's.
#  4. Save the current fb2 as refs/backup/fb2/<UTC time>, then rebase or
#     merge. git rerere is turned on in the repository config (if unset), so
#     a resolved conflict is resolved the same way at the next sync. On a
#     conflict it stops and says how to go on.
#  5. Run the unit tests and build the plugin zip with the pinned packages of
#     the image build (docker/calibre-plugin/requirements-build.txt), via uv.
#  6. Print the pushes: fb2 (with --force-with-lease after a rebase) and main.
#
# Environment: UPSTREAM_REMOTE (upstream), UPSTREAM_URL
# (https://github.com/JimmXinu/FanFicFare.git), UPSTREAM_BRANCH (main),
# BRANCH (fb2), ORIGIN (origin), MAIN (main), SYNC_PYTHON (3.14, for uv).
set -euo pipefail

UPSTREAM_REMOTE=${UPSTREAM_REMOTE:-upstream}
UPSTREAM_URL=${UPSTREAM_URL:-https://github.com/JimmXinu/FanFicFare.git}
UPSTREAM_BRANCH=${UPSTREAM_BRANCH:-main}
BRANCH=${BRANCH:-fb2}
ORIGIN=${ORIGIN:-origin}
MAIN=${MAIN:-main}
SYNC_PYTHON=${SYNC_PYTHON:-3.14}

mode=rebase test=1 push=0 cont=0
for arg in "$@"; do
  case "$arg" in
    --merge) mode=merge ;;
    --rebase) mode=rebase ;;
    --continue) cont=1 ;;
    --no-test) test=0 ;;
    --push) push=1 ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg (see --help)" >&2; exit 2 ;;
  esac
done

say() { printf '\n== %s\n' "$*"; }
die() { printf 'sync-upstream: %s\n' "$*" >&2; exit 1; }

cd "$(git rev-parse --show-toplevel)"
git_dir=$(git rev-parse --git-dir)
upstream_ref="refs/remotes/$UPSTREAM_REMOTE/$UPSTREAM_BRANCH"

in_progress() {
  [ -d "$git_dir/rebase-merge" ] || [ -d "$git_dir/rebase-apply" ] || [ -f "$git_dir/MERGE_HEAD" ]
}

plugin_version() {
  # 4.63.4.1 = __version__ + FB2_FORK_REVISION in calibre-plugin/__init__.py
  local v r
  v=$(git show "$1:calibre-plugin/__init__.py" | sed -n 's/^__version__ = (\(.*\))$/\1/p' | tr -d ' ' | tr ',' '.')
  r=$(git show "$1:calibre-plugin/__init__.py" | sed -n 's/^FB2_FORK_REVISION = \([0-9]*\)$/\1/p')
  echo "${v:-?}.${r:-?}"
}

run_tests() {
  command -v uv >/dev/null || die "uv not found; install it, or use --no-test and test by hand"
  local reqs=docker/calibre-plugin/requirements-build.txt out
  out=$(mktemp -d)
  say "unit tests (uv, Python $SYNC_PYTHON, $reqs)"
  uv run --no-project --python "$SYNC_PYTHON" --with-requirements "$reqs" \
    python -m pytest -q -p no:cacheprovider tests || die "unit tests failed; fix them before pushing"
  say "plugin zip"
  uv run --no-project --python "$SYNC_PYTHON" --with-requirements "$reqs" \
    python docker/calibre-plugin/build_plugin.py --out "$out" || die "plugin build failed"
  rm -rf "$out"
}

show_pushes() {
  local lease=$1 cmds=()
  if [ "$lease" = 1 ]; then
    cmds+=("git push --force-with-lease=$BRANCH $ORIGIN $BRANCH")
  else
    cmds+=("git push $ORIGIN $BRANCH")
  fi
  cmds+=("git push $ORIGIN $MAIN")
  if [ "$push" = 1 ]; then
    for c in "${cmds[@]}"; do say "$c"; $c; done
  else
    say "not pushed; to publish (an fb2 push that touches the plugin builds the image):"
    printf '  %s\n' "${cmds[@]}"
  fi
}

# 1 when the fork's fb2 on origin is no longer an ancestor of the local fb2
# (a rebase rewrote it), so the push needs --force-with-lease.
lease_needed() {
  if git rev-parse -q --verify "refs/remotes/$ORIGIN/$BRANCH" >/dev/null &&
     ! git merge-base --is-ancestor "refs/remotes/$ORIGIN/$BRANCH" "$BRANCH"; then
    echo 1
  else
    echo 0
  fi
}

# --continue: the rebase or merge was finished by hand.
if [ "$cont" = 1 ]; then
  in_progress && die "a rebase or merge is still in progress: finish it first (git rebase --continue / git commit)"
  [ "$(git symbolic-ref --short HEAD 2>/dev/null)" = "$BRANCH" ] || die "not on $BRANCH"
  git merge-base --is-ancestor "$upstream_ref" "$BRANCH" || die "$BRANCH does not contain $upstream_ref yet"
  if [ "$test" = 1 ]; then run_tests; fi
  say "$BRANCH: plugin version $(plugin_version "$BRANCH")"
  show_pushes "$(lease_needed)"
  exit 0
fi

# 1. checks
in_progress && die "a rebase or merge is in progress; finish or abort it (or use --continue once done)"
if ! git diff --quiet || ! git diff --cached --quiet; then
  die "uncommitted changes to tracked files; commit or stash them first"
fi
git rev-parse -q --verify "refs/heads/$BRANCH" >/dev/null || die "no local branch $BRANCH"

# 2. fetch
if ! git remote get-url "$UPSTREAM_REMOTE" >/dev/null 2>&1; then
  say "adding remote $UPSTREAM_REMOTE = $UPSTREAM_URL"
  git remote add "$UPSTREAM_REMOTE" "$UPSTREAM_URL"
  git config "remote.$UPSTREAM_REMOTE.tagOpt" --no-tags
fi
say "fetching $UPSTREAM_REMOTE/$UPSTREAM_BRANCH (no tags)"
git fetch --no-tags "$UPSTREAM_REMOTE" "+refs/heads/$UPSTREAM_BRANCH:$upstream_ref"
if git remote get-url "$ORIGIN" >/dev/null 2>&1; then
  # Refresh origin/fb2, so --force-with-lease compares with what is on GitHub now.
  git fetch --no-tags "$ORIGIN" "+refs/heads/$BRANCH:refs/remotes/$ORIGIN/$BRANCH" 2>/dev/null || true
fi

# 3. main = upstream/main
if git rev-parse -q --verify "refs/heads/$MAIN" >/dev/null; then
  git merge-base --is-ancestor "refs/heads/$MAIN" "$upstream_ref" ||
    die "local $MAIN has commits that are not in $upstream_ref; $MAIN must stay a copy of upstream"
  if [ "$(git symbolic-ref --short HEAD 2>/dev/null)" = "$MAIN" ]; then
    git merge --ff-only -q "$upstream_ref"
  else
    git update-ref "refs/heads/$MAIN" "$upstream_ref"
  fi
else
  git branch "$MAIN" "$upstream_ref"
fi
say "$MAIN = $UPSTREAM_REMOTE/$UPSTREAM_BRANCH = $(git log -1 --format='%h %s' "$upstream_ref")"

old_base=$(git merge-base "$BRANCH" "$upstream_ref")
if [ "$old_base" = "$(git rev-parse "$upstream_ref")" ]; then
  say "$BRANCH already contains $UPSTREAM_REMOTE/$UPSTREAM_BRANCH; nothing to sync"
  if [ "$test" = 1 ]; then run_tests; fi
  if [ "$(git rev-parse "$BRANCH")" != "$(git rev-parse -q --verify "refs/remotes/$ORIGIN/$BRANCH" || true)" ]; then
    show_pushes "$(lease_needed)"
  fi
  exit 0
fi
new_count=$(git rev-list --count "$old_base..$upstream_ref")
say "upstream commits new to $BRANCH: $new_count"
git log --oneline --no-decorate -n 30 "$old_base..$upstream_ref"
if [ "$new_count" -gt 30 ]; then echo "... and $((new_count - 30)) more"; fi

# 4. backup, then rebase or merge
backup="refs/backup/$BRANCH/$(date -u +%Y%m%dT%H%M%SZ)"
git update-ref "$backup" "refs/heads/$BRANCH"
say "saved $BRANCH ($(git rev-parse --short "$BRANCH")) as $backup"
git checkout -q "$BRANCH"
# rerere records a resolution when the rebase/merge is finished by hand,
# so it has to be on in the repository config, not only for this command.
if [ -z "$(git config --get rerere.enabled || true)" ]; then
  git config rerere.enabled true
  git config rerere.autoUpdate true
  say "turned on git rerere in this repository (rerere.enabled, rerere.autoUpdate)"
fi

conflict() {
  local fix="Fix the files git lists as conflicted, then 'git add' them."
  if [ -z "$(git diff --name-only --diff-filter=U)" ]; then
    fix="rerere already resolved and staged every conflict the way it was resolved before: check 'git diff --cached'."
  fi
  local rr="rerere is off (rerere.enabled=false), so resolve the same conflicts again at the next sync."
  if [ "$(git config --get rerere.enabled)" = true ]; then
    rr="rerere is on in this repository, so the resolution is reused at the next sync."
  fi
  cat >&2 <<EOF

sync-upstream: the $mode stopped on a conflict.
  - $fix
  - $1
  - Then run: scripts/sync-upstream.sh --continue
  - To give up instead: $2
    ($BRANCH is also saved as $backup)
  $rr
  Conflicts usually land in calibre-plugin/{fff_plugin,jobs,dialogs,config,__init__}.py.
EOF
  exit 1
}

if [ "$mode" = rebase ]; then
  say "rebasing $BRANCH onto $UPSTREAM_REMOTE/$UPSTREAM_BRANCH"
  git rebase "$upstream_ref" ||
    conflict "Continue with: git rebase --continue (repeat for each stop)" "git rebase --abort"
else
  say "merging $UPSTREAM_REMOTE/$UPSTREAM_BRANCH into $BRANCH"
  git merge --no-ff --no-edit \
    -m "Merge upstream $UPSTREAM_BRANCH ($(git log -1 --format=%h "$upstream_ref")) into $BRANCH" "$upstream_ref" ||
    conflict "Finish with: git commit --no-edit" "git merge --abort"
fi

say "$BRANCH: $(git log -1 --format='%h %s'), plugin version $(plugin_version "$BRANCH")"
echo "fork commits on top of upstream: $(git rev-list --count "$upstream_ref..$BRANCH")"

# 5. tests
if [ "$test" = 1 ]; then run_tests; fi

# 6. pushes
show_pushes "$(lease_needed)"
