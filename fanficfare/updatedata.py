# -*- coding: utf-8 -*-

# Copyright 2026 FanFicFare team
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Read an existing story file back for update, whatever its format.

The functions here take the same arguments and return the same
values as the epubutils functions of the same names, but also accept
FB2 files (see fb2utils).
"""

import logging
import os
import zipfile

from . import epubutils
from . import fb2utils

logger = logging.getLogger(__name__)

## Formats that can be read back for update (and written by update).
UPDATE_FORMATS = ('epub', 'fb2')

FORMAT_EXTS = {'epub': '.epub', 'fb2': '.fb2'}

def _head(inputio, size=None):
    if hasattr(inputio, 'read'):
        if hasattr(inputio, 'seek'):
            inputio.seek(0)
        data = inputio.read() if size is None else inputio.read(size)
        if hasattr(inputio, 'seek'):
            inputio.seek(0)
        return data
    with open(inputio, 'rb') as f:
        return f.read() if size is None else f.read(size)

def detect_format(inputio):
    """'epub', 'fb2' or None.  By content, not by file name."""
    head = _head(inputio, 4096)
    if head[:2] == b'PK':
        try:
            ## works equally well with inputio as a path or a stream
            names = zipfile.ZipFile(inputio).namelist()
        except zipfile.BadZipFile:
            return None
        finally:
            if hasattr(inputio, 'seek'):
                inputio.seek(0)
        if 'META-INF/container.xml' in names:
            return 'epub'
        if any(n.lower().endswith('.fb2') for n in names):
            return 'fb2'
        return None
    if fb2utils.is_fb2_data(head):
        return 'fb2'
    return None

def _module(inputio):
    fmt = detect_format(inputio)
    if fmt == 'fb2':
        return fb2utils
    ## anything else gets the epub reader and its errors, as before.
    return epubutils

def get_update_data(inputio, getfilecount=True, getsoups=True):
    return _module(inputio).get_update_data(inputio,
                                            getfilecount=getfilecount,
                                            getsoups=getsoups)

def get_dcsource(inputio):
    return _module(inputio).get_dcsource(inputio)

def get_dcsource_chaptercount(inputio):
    return _module(inputio).get_dcsource_chaptercount(inputio)

def get_cover_img(inputio):
    return _module(inputio).get_cover_img(inputio)

def converted_filename(filename, fileform):
    """filename with its .epub/.fb2(.zip) extension replaced by the one
    for fileform, for writing a file read in one format as another."""
    base = filename
    if base.lower().endswith('.zip'):
        base = base[:-4]
    root, ext = os.path.splitext(base)
    if ext.lower() in ('.epub', '.fb2'):
        base = root
    return base + FORMAT_EXTS.get(fileform, '.' + fileform)

def update_source_order(fileform):
    """Formats to look for, in order, as the existing file to update
    when writing fileform: the same format first, then the other one.
    Empty for formats that can't be updated."""
    if fileform not in UPDATE_FORMATS:
        return []
    return [fileform] + [f for f in UPDATE_FORMATS if f != fileform]

def choose_update_source(fileform, has_format, get_chaptercount):
    """Pick which existing file of a book to update from when writing
    fileform, for callers (the calibre plugin) that can have the same
    story in several formats.

    has_format(fmt) -> bool: the book has a file in format fmt.
    get_chaptercount(fmt) -> int: chapters FanFicFare can reuse from
    that file (get_dcsource_chaptercount()[1]); only called for
    formats the book has.

    Returns (fmt, chaptercount), or (None, None) when there is no file
    to update from and the story should be downloaded in full.

    - The first format in update_source_order(fileform) with reusable
      chapters wins: FB2 output reuses an FB2, else an EPUB, and
      writing the other format from it is a conversion.
    - An FB2 without FanFicFare's chapter data (made by another
      program) or that can't be read is never used.
    - An EPUB without recognizable chapters is used only when nothing
      better is found, so the caller can report it as before
      ('no_chapters': "probably from a different source").  A broken
      EPUB raises, as before.
    """
    fallback = (None, None)
    for fmt in update_source_order(fileform):
        if not has_format(fmt):
            continue
        try:
            count = get_chaptercount(fmt) or 0
        except Exception:
            if fmt == 'epub':
                raise
            logger.warning("Existing %s can't be read for update, not used." % fmt, exc_info=True)
            continue
        if count:
            return (fmt, count)
        if fmt == 'epub' and fallback[0] is None:
            fallback = (fmt, count)
    return fallback
