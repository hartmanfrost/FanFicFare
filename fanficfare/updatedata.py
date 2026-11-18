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

import os
import zipfile

from . import epubutils
from . import fb2utils

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
