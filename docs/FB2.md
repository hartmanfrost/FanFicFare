# FB2 in the FanFicFare FB2 fork

This fork adds FB2 (FictionBook 2) as a full output format, with
update support, to the FanFicFare CLI and calibre plugin.

## Core (fanficfare/)

- `writers/writer_fb2.py` writes FB2. The settings live in `[fb2]` in
  `defaults.ini`/`plugin-defaults.ini`.
- What an update needs is stored in
  `<custom-info info-type="fanficfare-data">`: each chapter's URL,
  original title and data, image URLs, the log page and the calibre
  bookmark. That keeps the file valid FB2.
- `fb2utils.py` reads FB2 back for update. `updatedata.py` reads an
  EPUB or an FB2 by its content, and picks which existing file to update
  from (`choose_update_source`).
- CLI:
  - `-u`/`-U` take FB2 files.
  - `-u book.epub -f fb2` converts with no chapter refetch, and
    `-u book.fb2 -f epub` converts back.
  - An FB2 made by another program (no FanFicFare data) gets a full
    download.

## calibre plugin

### Install

- The plugin is named **FanFicFare FB2**, version 4.63.4.1 (upstream
  version + fork revision).
- calibre's plugin updater pairs plugins with its index by name, so it
  never offers upstream FanFicFare as an "update" of the fork.
- **Uninstall upstream FanFicFare first.** Both use the import name
  `fanficfare_plugin` and bundle their own `fanficfare`. With both
  installed, calibre 9.15 loads a mix of the two and neither works. The
  fork then fails with a message saying so, if calibre loaded the
  fork's copy of the code.
- The library settings namespace and the action name `FanFicFare`
  (toolbar, shortcuts, Action Chains) are unchanged, so existing
  settings carry over.
- CLI use: `calibre-debug --run-plugin "FanFicFare FB2" -- ...`
- Build: `python makeplugin.py` (Python with zlib, e.g. a uv venv).
  - The repository has only `.po` files and the build skips them, so a
    zip built this way has an English UI.

### How updates choose a file

The "Update EPUB if New Chapters" and "Update EPUB Always" modes work
for **epub and fb2** output; the labels are unchanged. The file to
update from:

| Output format | Book has | Update reads | Result |
|---|---|---|---|
| fb2 | FB2 from FanFicFare | the FB2 | FB2 updated; only new chapters are fetched |
| fb2 | EPUB only (or FB2 not from FanFicFare + EPUB) | the EPUB | conversion: FB2 written and added to the same book, no chapter refetch, **always written**, even without new chapters; EPUB kept |
| fb2 | only an FB2 not from FanFicFare (e.g. calibre's conversion) | nothing | full download, the FB2 is replaced |
| epub | EPUB | the EPUB | as upstream |
| epub | FanFicFare FB2 only (or EPUB without chapters + FB2) | the FB2 | conversion to EPUB, always written |
| mobi, html, txt | - | - | update modes not offered, as upstream |

- Once a book has both files, the file in the output format is used.
- An EPUB with no recognizable chapters still gives upstream's "Use
  Overwrite" error if no FB2 is usable.
- Overwrite modes use the same choice, only to keep the log page.

### Every EPUB-specific site, and what was done

| Where | What | Decision |
|---|---|---|
| `__init__.py` | plugin name, version | renamed to `FanFicFare FB2`, version 4.63.4.1; the `__version__` line is kept for `version_update.py`; refuses to load next to upstream |
| `fff_plugin.py` `genesis` | `"%d.%d.%d" % version` | `'.'.join`, so a 4-number version works |
| `prefs.py` `fileform` default | `epub` | **`fb2`**; affects only libraries with no saved FanFicFare settings |
| `prefs.py` UPDATE/UPDATEALWAYS ("Update EPUB …") | labels and saved values | unchanged: they are saved in settings, compared with combo text and translated; they now mean EPUB or FB2 |
| `dialogs.py` (2), `config.py` (1) | output format combos | `fb2` added |
| `dialogs.py`, `config.py` `set_collisions` | update modes only for epub | for `UPDATE_FORMATS` (epub, fb2) |
| `fff_plugin.py` `check_valid_collision`, `prep_download_loop` | "Cannot update non-epub format" | allowed for epub and fb2; message text unchanged |
| `fff_plugin.py` `formmapping` | calibre format names | `fb2: FB2` |
| `fff_plugin.py` `prep_download_loop` | checked `has_format(fileform)` but read `EPUB`; copied the EPUB only for epub output | uses `get_update_source()`, which calls `choose_update_source`. The chosen file is copied with its own suffix to `book['epub_for_update']` (the key name is kept), and its format goes in `book['update_format']`. A conversion skips "Already contains" |
| `jobs.py` | `epubutils.get_update_data` | `updatedata.get_update_data` (EPUB or FB2) |
| `jobs.py` | include_images only for epub, html | also fb2 (images and cover go into FB2 binaries) |
| `jobs.py` | "Already contains" in the job (bgmeta) and "nothing changed" exit | skipped for conversions, so the new format is always written |
| `jobs.py` | "Existing epub contains … / doesn't recognize chapters in existing epub" | text unchanged (translations) |
| `jobs.py`, `config.py` | Smarten Punctuation "(EPUB only)" | stays EPUB only (calibre polish handles EPUB/AZW3) |
| `wordcount.py` | names say EPUB | unchanged; calibre's `EbookIterator` reads FB2 (checked: 32,956 words for the FB2 vs 32,936 for the EPUB) |
| `fff_plugin.py` `update_metadata` calibre cover | from the EPUB | from the EPUB or FB2 just written (calibre's FB2 reader returns the coverpage) |
| `fff_plugin.py` `gc_polish_cover` | inject the generated cover into the EPUB | stays EPUB only (polish) |
| `fff_plugin.py` `get_story_url` | url/uri identifier, then EPUB `dc:source`, then html/zip/txt scan | adds the FB2 `src-url` after the EPUB, and the links in an FB2 (e.g. calibre's conversion of an FFF EPUB) with "Search inside ebooks for Story URL". calibre's FB2 metadata reader gives no url identifier |
| `fff_plugin.py` unnew ("Remove 'New' Chapter Marks") | EPUB | stays EPUB only (no FB2 unnew yet). Books with only an FB2 are skipped. `mark_new_chapters` is off by default |
| anthologies (EpubMerge): menus, `prep_anthology_downloads`, merge, old anthology cover | EPUB | stay EPUB only; `dialogs.py` now really forces `fileform='epub'` for anthologies (`==` → `=`) |
| `fff_plugin.py` `add_book_or_update_format`, `deleteotherforms`, `autoconvert` | per `formmapping[fileform]` | unchanged. With fb2 output: the FB2 is added to the book and the EPUB stays unless "Delete other existing formats" is on. **autoconvert** with calibre's output format EPUB would replace FanFicFare's EPUB with calibre's conversion of the FB2; harmless for FB2 updates, but don't combine it with wanting FanFicFare EPUBs |
| default `options={'fileform':'epub',…}` arguments, `fff_util` `fileform="epub"` defaults | defaults only | unchanged (callers pass the format) |
| config tooltips "Update Calibre Cover (from EPUB)", "Search inside EPUB, ZIP(HTML) or TXT" | text | unchanged (translations); they apply to FB2 too |

### Not done

- No FB2 unnew, update log page (`include_logpage`) or footnotes.
- Smarten punctuation and cover injection by polish stay EPUB only.
- Translations aren't compiled by `makeplugin.py`.
