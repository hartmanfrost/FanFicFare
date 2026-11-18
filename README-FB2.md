# FanFicFare FB2

A fork of [FanFicFare](https://github.com/JimmXinu/FanFicFare) (branch
`fb2`) that makes **FB2 (FictionBook 2)** a full output format, including
update, in both the command line tool and the calibre plugin. Everything
else is upstream FanFicFare. Internals and the list of every EPUB-specific
place in the plugin are in [docs/FB2.md](docs/FB2.md).

## What the fork adds

- **FB2 output**: `-f fb2` on the command line, `fb2` as the plugin's
  output format. The FB2 is a single XML file with the chapters as
  sections, images and the cover embedded, metadata in `<description>`.
  It validates against the FB2 2.1 schema, except that the default genre
  `fanfiction` is not in that schema's genre list. Set
  `fb2_default_genre:sf_fantasy` if strict validation matters.
- **FB2 update**: an FB2 written by FanFicFare keeps what an update needs
  (chapter URLs and titles, image URLs, the log page, the calibre
  bookmark) in `<custom-info info-type="fanficfare-data">`, so an update
  fetches only new chapters, as with EPUB.
- **Conversion without refetching**: updating an EPUB into FB2 reuses the
  EPUB's chapters and writes an FB2 next to it; the EPUB is not touched.
  FB2 into EPUB works the same way. This is how an existing EPUB library
  is converted.
- **FB2 files from other programs** (for example calibre's own
  conversions) have no FanFicFare data. Updating one is a full download
  that replaces the file.
- `.fb2.zip` output with `zip_output:true` in `[fb2]`.
- **calibre plugin "FanFicFare FB2"**:
  - `fb2` in the output format lists; it is the default for libraries
    with no saved FanFicFare settings.
  - The "Update EPUB if New Chapters" and "Update EPUB Always" modes also
    update FB2; the labels are unchanged.
  - Updating an EPUB-only book with fb2 output converts it and adds the
    FB2 to the same book.
  - The calibre cover and story URL are read from FB2 too.
  - A renamed plugin, so calibre never offers upstream FanFicFare as an
    "update" that would remove FB2.
- **ficbook.net**: `[ficbook.net:fb2]` maps ficbook tags to FB2 genres.
  `replace_text_formatting` stays off for fb2: upstream turns it on in
  `[ficbook.net:epub]`, and it drops italics and bold from the chapter
  text. EPUBs made with it on have already lost that formatting, and
  converting them keeps the loss; download those again with `-f fb2`
  (and `--force` if the FB2 already exists).

Not done, EPUB only: removing "new" chapter marks (`--unnew`), the update
log page, anthologies (EpubMerge), Smarten Punctuation and cover
injection. FB2 has no footnotes body: author notes come out as `<cite>`.

## Install the calibre plugin

1. **Remove upstream FanFicFare first** (Preferences > Plugins >
   FanFicFare > Remove plugin, or `calibre-customize -r FanFicFare`) and
   restart calibre. The two cannot be installed together. The fork keeps
   upstream's settings namespace, action name and import name, so library
   settings, the toolbar button, shortcuts and Action Chains carry over.
2. Get the zip, either
   - from the image (see below):

     ```sh
     docker run --rm ghcr.io/hartmanfrost/fanficfare-calibre-plugin - > FanFicFare-FB2.zip
     ```

     (`docker login ghcr.io` first if the package is private), or
   - build it from a checkout. With translations, as the image does:

     ```sh
     uv run --no-project --with-requirements docker/calibre-plugin/requirements-build.txt \
         python docker/calibre-plugin/build_plugin.py --out dist-plugin
     ```

     or without them (English UI only): `python makeplugin.py`, with a
     Python that has zlib.
3. Preferences > Plugins > Load plugin from file, or
   `calibre-customize -a FanFicFare-FB2.zip`. Restart calibre.
   `calibre-customize -l` lists it as `FanFicFare FB2 (4, 63, 4, 1)`: the
   upstream version plus the fork revision.
4. For an existing library, choose `fb2` under FanFicFare FB2 >
   Customize plugin > Basic > Default Output Format.

From the command line the plugin runs as
`calibre-debug --run-plugin "FanFicFare FB2" -- <fanficfare options>`.

## Command line

```sh
uv venv && uv pip install -e .          # or: pip install git+https://github.com/hartmanfrost/FanFicFare@fb2
```

| Command | What it does |
|---|---|
| `fanficfare -f fb2 URL` | new download as FB2 (`output_filename`, by default `<title>-<site>_<id>.fb2`) |
| `fanficfare -u story.fb2` | update: fetches only chapters that are new on the site |
| `fanficfare -u URL -f fb2` | update the FB2 that `output_filename` names for URL; if it has no FanFicFare data (or doesn't exist) and an EPUB of that name does, convert the EPUB; an FB2 without FanFicFare data and no EPUB: full download, replacing it |
| `fanficfare -U story.fb2` | rewrite even without new chapters, still without refetching old ones; as upstream, a file newer than the story's last update is skipped unless `always_overwrite:true` |
| `fanficfare -u story.epub -f fb2` | convert: writes `story.fb2` from the EPUB's chapters plus any new ones; `story.epub` is not changed; always writes. If `story.fb2` is already a FanFicFare FB2 (converted before), it is updated instead, as by `-u story.fb2` |
| `fanficfare -u story.fb2 -f epub` | convert back to EPUB |
| `fanficfare -u other.fb2` | an FB2 without FanFicFare data (from another program): full download, replaces the file, keeps its cover |
| `fanficfare -o zip_output=true -f fb2 URL` | `.fb2.zip`; `-u story.fb2.zip` updates it in place |

Without `-f`, `-u`/`-U` keep the format of the given file. A conversion
still fetches the story's page for the metadata and chapter list, but no
chapters it already has. It also keeps the chapters the site has removed
since, as `update_preserve_deleted_chapters:true` does (not with a
chapter range), instead of refusing because the file has more chapters
than the site. Later updates of such a story compare chapter counts as
usual, so turn `update_preserve_deleted_chapters` on for it.
Converting a folder:

```sh
for f in library/*.epub; do fanficfare --non-interactive -u "$f" -f fb2; done
```

Running the loop again (after an interruption, say) updates the FB2s it
already wrote instead of converting them again. To convert an EPUB again,
delete its FB2 first; `--force` is not the way, it downloads every
chapter again.

Settings go in `personal.ini` under `[fb2]` or `[<site>:fb2]`, for
example `[ficbook.net:fb2]`. The documented defaults are in the `[fb2]`
section of `fanficfare/defaults.ini`:

| Key | Default | Meaning |
|---|---|---|
| `fb2_default_genre` | `fanfiction` | first `<genre>`; `sf_fantasy` for strict schema validity |
| `fb2_genre_map` | a few English genres | `site genre=>fb2 genre` lines, added after the default genre |
| `fb2_prewrap_classes` | `part_text, text-preline` | classes whose raw line breaks become paragraphs (ficbook) |
| `fb2_hr_text` | `* * *` | text of the `<subtitle>` that replaces `<hr>`; empty gives an empty line |
| `fb2_src_lang` | unset | `<src-lang>` for translations |
| `fb2_tocpage_title` | `Table of Contents` | with `include_tocpage:true` |
| `zip_output` | `false` | `.fb2.zip` |

`include_images`, the cover settings, `update_preserve_deleted_chapters`
and `force_update_epub_always` work for fb2 as they do for epub.

## The image: `ghcr.io/hartmanfrost/fanficfare-calibre-plugin`

`docker/calibre-plugin/Dockerfile` builds a small busybox image with the
plugin zip, for a calibre pod's initContainer:

- `/FanFicFare.zip`, `/FanFicFare.zip.sha256`, `/FanFicFare.version`
  (`FanFicFare FB2 4.63.4.1`);
- entrypoint `/copy-plugin.sh`:
  - no arguments (the CMD, `/plugins/`): writes `/plugins/FanFicFare.zip`;
  - `DIR...`: writes `DIR/FanFicFare.zip` for each directory;
  - `-`: the zip to stdout;
  - `--version`: name, version and sha256.

  Each copy goes through a temporary name and a rename. The image runs as
  root, like upstream busybox.

```yaml
initContainers:
  - name: fff-plugin
    image: ghcr.io/hartmanfrost/fanficfare-calibre-plugin:latest@sha256:<digest>
    args: ["/plugins/"]            # optional, the same as the CMD
    volumeMounts:
      - name: plugins              # an emptyDir shared with the calibre container
        mountPath: /plugins
```

calibre then installs it as its own user:
`CALIBRE_CONFIG_DIRECTORY=... calibre-customize -a /plugins/FanFicFare.zip`.

How the build works:

1. The build stage (`python:3.14.10-slim-trixie`, pinned by digest)
   installs the exact packages in
   `docker/calibre-plugin/requirements-build.txt`. That is the only step
   that uses the network.
2. It runs the unit tests. A failing test means no image.
3. `build_plugin.py` compiles the translations, runs `makeplugin.py` on a
   copy of the sources, and rewrites the zip with sorted entries, a fixed
   date and fixed modes. The same commit gives the same zip, so the
   image's sha256 can be checked against a local `build_plugin.py` run.
4. The final stage is `busybox:1.37.0`, pinned by digest.

To bump the pins, edit `requirements-build.txt` (run the tests with it),
or look up a new base digest with
`docker buildx imagetools inspect python:3.14.N-slim-trixie` and use the
index digest.

Build locally from the repository root:

```sh
docker build -f docker/calibre-plugin/Dockerfile -t fanficfare-calibre-plugin .
docker run --rm fanficfare-calibre-plugin --version
```

### CI (ash app-ci)

`.ash-ci.yaml` makes the ash cluster CI (app-ci, through the `argoash`
GitHub App) build the image:

| Event | Result |
|---|---|
| push to the default branch that changes a file under `paths` | builds and pushes `:latest` and `:<40-char commit sha>` (and the BuildKit cache `:buildcache`) |
| push that changes only docs, tests or scripts | nothing is built |
| pull request from a branch of this repository | builds without pushing (tests run) |
| pull request from a fork | skipped |
| push of a `v*` tag | most likely nothing: a tag push should list no changed files, so `paths` filters it out (not tried) |

Every build has a new digest, and Image Updater follows `:latest` by
digest; each new digest restarts the calibre pod. That is why `paths`
lists only what goes into the image.

There is no GitHub Actions workflow; the CI starts from the App's
webhook, and app-ci builds only pushes to the default branch that change
a file under `paths`. So the first `:latest` needs this order:

1. Push `fb2`. app-ci skips that push: `fb2` isn't the default branch
   yet, and GitHub can't make it one before it exists.
2. Set the repository's **default branch to `fb2`**
   (`gh repo edit hartmanfrost/FanFicFare --default-branch fb2`) and
   install the `argoash` App on the repository
   (github.com/settings/installations > argoash > Repository access).
   Neither sends a push, so nothing is built yet.
3. Push a commit to `fb2` that changes a file under `paths`, for example
   a comment in `.ash-ci.yaml`. An empty commit, or one that touches only
   docs, builds nothing.

Until then there is no `:latest` digest for the calibre initContainer to
pin, and Image Updater has nothing to follow.

## Keeping up with upstream

```sh
scripts/sync-upstream.sh            # rebase fb2 onto upstream main, test, print the pushes
scripts/sync-upstream.sh --merge    # merge instead of rebase (never force-pushes)
scripts/sync-upstream.sh --push     # also run the pushes
```

What it does:

1. It refuses to run with uncommitted changes.
2. It fetches `upstream` without tags and adds the remote if it is
   missing. Upstream's `v*` tags stay off the fork, because a pushed `v*`
   tag starts a CI run. It also fetches the fork's `fb2`. If that has
   commits the local `fb2` never had (pushed from another clone), it
   stops and lists them; bring them in first. If the local `fb2` is only
   behind, it is fast-forwarded.
3. It fast-forwards the local `main` to upstream's.
4. It saves `fb2` as `refs/backup/fb2/<time>`, then rebases `fb2` onto
   `upstream/main`.
5. It runs the unit tests and the plugin build with the image's pinned
   packages, through `uv`.
6. It prints the pushes: `git push origin main`, and for `fb2`, after a
   rebase, `git push --force-with-lease=fb2:<the fb2 fetched in step 2>
   origin fb2`, which git refuses if anything was pushed to `fb2` since.
   Otherwise (`--merge`, or nothing rebased) it is a plain
   `git push origin fb2`.

On a conflict it stops. Resolve the conflict, finish the rebase
(`git rebase --continue`), then run `scripts/sync-upstream.sh --continue`
to test and print the pushes. git rerere is turned on in the repository,
so the same conflict is resolved automatically at the next sync.
Conflicts are most likely in `calibre-plugin/fff_plugin.py`, `jobs.py`,
`dialogs.py`, `config.py` and `__init__.py`; the core changes are mostly
new files.

Versions follow upstream by themselves: the plugin version is
`__version__ + (FB2_FORK_REVISION,)` in `calibre-plugin/__init__.py`, so
an upstream bump to 4.64.0 gives 4.64.0.1. Increase `FB2_FORK_REVISION`
when the fork changes without an upstream bump, so calibre shows a new
version. Once the sync is pushed, app-ci builds a new image if the plugin
changed.

## Licensing

`fanficfare/` (including `writers/writer_fb2.py`, `fb2utils.py` and
`updatedata.py`) is Apache-2.0, like upstream's core. `calibre-plugin/` is
GPLv3, so the plugin zip is GPLv3; this public repository is its source.
The FB2 schemas in `tests/fb2xsd` are BSD-licensed (gribuser).
