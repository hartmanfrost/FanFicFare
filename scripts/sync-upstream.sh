#!/usr/bin/env bash
# Bring the fork's fb2 branch up to date with upstream FanFicFare.
#
#   scripts/sync-upstream.sh [--merge] [--no-test] [--push]
#   scripts/sync-upstream.sh --continue [--no-test] [--push]
#
#   (default)   rebase fb2 onto upstream/main
#   --merge     merge upstream/main into fb2 instead (never force-pushes)
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
#     tag starts an ash app-ci run. Also fetch origin's fb2. If it has
#     commits the local fb2 never had (pushed from another clone), stop,
#     or fast-forward fb2 when it is simply behind: they must not be
#     overwritten.
#  3. Fast-forward the local main to upstream/main; main stays a plain copy
#     of upstream's.
#  4. Save the current fb2 as refs/backup/fb2/<UTC time>, then rebase or
#     merge. git rerere is turned on in the repository config (if unset), so
#     a resolved conflict is resolved the same way at the next sync. On a
#     conflict it stops and says how to go on.
#  5. Run the unit tests and build the plugin zip with the pinned packages of
#     the image build (docker/calibre-plugin/requirements-build.txt), via uv.
#  6. Print the pushes: fb2 and main. After a rebase that rewrote what
#     origin has, the fb2 push is --force-with-lease=fb2:<origin's fb2 as
#     fetched in step 2>, so it fails if anything was pushed since.
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

# $1: the commit origin's fb2 must still be at for a forced push (see
# lease_for_push), or empty for a plain push.
show_pushes() {
  local lease=$1 cmds=()
  if [ -n "$lease" ]; then
    cmds+=("git push --force-with-lease=$BRANCH:$lease $ORIGIN $BRANCH")
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

# origin's fb2 as last fetched; empty when origin has none.
origin_tip() {
  git rev-parse -q --verify "refs/remotes/$ORIGIN/$BRANCH" || true
}

# Whether commit $1 is in the local history of fb2: in fb2, in a backup
# made by this script, or in an earlier fb2 of its reflog. After a rebase
# that wasn't pushed yet, origin's fb2 is only in the backup.
known_locally() {
  local c=$1 r
  git merge-base --is-ancestor "$c" "$BRANCH" && return 0
  for r in $( { git for-each-ref --format='%(objectname)' "refs/backup/$BRANCH/"
                git rev-list -g -n 500 "refs/heads/$BRANCH" 2>/dev/null || true; } | sort -u); do
    git merge-base --is-ancestor "$c" "$r" && return 0
  done
  return 1
}

# Stop unless every commit of origin's fb2 is in the local history (or
# fast-forward fb2 when it is only behind), so a push never drops commits
# pushed from elsewhere.
check_origin() {
  local o
  o=$(origin_tip)
  [ -n "$o" ] || return 0
  known_locally "$o" && return 0
  if [ "$1" = ff ] && git merge-base --is-ancestor "$BRANCH" "$o"; then
    say "$ORIGIN/$BRANCH has $(git rev-list --count "$BRANCH..$o") commit(s) the local $BRANCH doesn't: fast-forwarding $BRANCH"
    if [ "$(git symbolic-ref --short HEAD 2>/dev/null)" = "$BRANCH" ]; then
      git merge --ff-only -q "$o"
    else
      git update-ref "refs/heads/$BRANCH" "$o" "$(git rev-parse "$BRANCH")"
    fi
    return 0
  fi
  echo "commits on $ORIGIN/$BRANCH that the local $BRANCH never had:" >&2
  git log --oneline --no-decorate --cherry-pick --right-only "$BRANCH...$o" >&2 || true
  die "$ORIGIN/$BRANCH has commits pushed from elsewhere (above). Bring them into $BRANCH first, e.g. 'git rebase $ORIGIN/$BRANCH' (or 'git reset --hard $ORIGIN/$BRANCH' if the local $BRANCH has nothing to keep), then sync again."
}

# The --force-with-lease value for the fb2 push: origin's fb2 as fetched,
# when the local fb2 no longer contains it (a rebase rewrote it; see
# check_origin). Empty: a plain push, which git refuses unless it is a
# fast-forward.
lease_for_push() {
  local o
  o=$(origin_tip)
  if [ -n "$o" ] && ! git merge-base --is-ancestor "$o" "$BRANCH"; then
    echo "$o"
  fi
}

# --continue: the rebase or merge was finished by hand.
if [ "$cont" = 1 ]; then
  in_progress && die "a rebase or merge is still in progress: finish it first (git rebase --continue / git commit)"
  [ "$(git symbolic-ref --short HEAD 2>/dev/null)" = "$BRANCH" ] || die "not on $BRANCH"
  git merge-base --is-ancestor "$upstream_ref" "$BRANCH" || die "$BRANCH does not contain $upstream_ref yet"
  # origin's fb2 is the one fetched by the run that stopped (no fetch here).
  check_origin no-ff
  if [ "$test" = 1 ]; then run_tests; fi
  say "$BRANCH: plugin version $(plugin_version "$BRANCH")"
  show_pushes "$(lease_for_push)"
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
  # Refresh origin/fb2: what is on GitHub now. (It fails when origin has
  # no fb2 yet.)
  git fetch --no-tags "$ORIGIN" "+refs/heads/$BRANCH:refs/remotes/$ORIGIN/$BRANCH" 2>/dev/null || true
fi
check_origin ff
if [ "$mode" = merge ] && [ -n "$(lease_for_push)" ]; then
  die "the local $BRANCH no longer contains $ORIGIN/$BRANCH (an earlier rebase that wasn't pushed?); publishing it needs a force-push, which --merge doesn't do. Run without --merge, or reset $BRANCH to $ORIGIN/$BRANCH."
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
  if [ "$(git rev-parse "$BRANCH")" != "$(origin_tip)" ]; then
    show_pushes "$(lease_for_push)"
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

# 6. pushes (a merge keeps origin's fb2 as an ancestor: a plain push)
show_pushes "$(lease_for_push)"
