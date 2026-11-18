# -*- coding: utf-8 -*-

"""updatedata.choose_update_source(): which existing file of a book
(EPUB and/or FB2) an update reads its chapters from."""

import io

import pytest

from fanficfare.updatedata import (
    choose_update_source, update_source_order, get_dcsource_chaptercount)

from tests.test_fb2 import fresh_file


def chooser(fileform, counts):
    """choose_update_source over a book with counts {fmt: chapters or
    an exception to raise}.  Returns (result, formats whose chapters
    were counted)."""
    counted = []

    def get_chaptercount(fmt):
        counted.append(fmt)
        if isinstance(counts[fmt], Exception):
            raise counts[fmt]
        return counts[fmt]

    result = choose_update_source(fileform, lambda fmt: fmt in counts, get_chaptercount)
    return result, counted


def test_update_source_order():
    assert update_source_order('fb2') == ['fb2', 'epub']
    assert update_source_order('epub') == ['epub', 'fb2']
    assert update_source_order('mobi') == []
    assert update_source_order('html') == []


@pytest.mark.parametrize('fileform, counts, expected, counted', [
    ## same format first, the other one isn't even read.
    ('fb2', {'fb2': 5, 'epub': 5}, ('fb2', 5), ['fb2']),
    ('epub', {'fb2': 5, 'epub': 5}, ('epub', 5), ['epub']),
    ## no file in the output format: convert from the other.
    ('fb2', {'epub': 7}, ('epub', 7), ['epub']),
    ('epub', {'fb2': 7}, ('fb2', 7), ['fb2']),
    ## FB2 from another program (no chapter data): never used.
    ('fb2', {'fb2': 0, 'epub': 4}, ('epub', 4), ['fb2', 'epub']),
    ('fb2', {'fb2': 0}, (None, None), ['fb2']),
    ('epub', {'fb2': 0}, (None, None), ['fb2']),
    ## unreadable FB2: skipped, not an error.
    ('fb2', {'fb2': ValueError('broken'), 'epub': 3}, ('epub', 3), ['fb2', 'epub']),
    ('fb2', {'fb2': ValueError('broken')}, (None, None), ['fb2']),
    ## EPUB without chapters is kept as the answer only when nothing
    ## else has chapters, so the caller still says "different source".
    ('epub', {'epub': 0}, ('epub', 0), ['epub']),
    ('epub', {'epub': 0, 'fb2': 6}, ('fb2', 6), ['epub', 'fb2']),
    ('fb2', {'epub': 0, 'fb2': 0}, ('epub', 0), ['fb2', 'epub']),
    ## nothing to update from: full download.
    ('fb2', {}, (None, None), []),
    ## formats that can't be updated never read anything.
    ('mobi', {'epub': 5, 'fb2': 5}, (None, None), []),
    ('txt', {'epub': 5}, (None, None), []),
])
def test_choose_update_source(fileform, counts, expected, counted):
    assert chooser(fileform, counts) == (expected, counted)


def test_choose_update_source_broken_epub_raises():
    "As before FB2: a broken EPUB is an error for the caller to report."
    with pytest.raises(ValueError):
        chooser('epub', {'epub': ValueError('broken')})
    with pytest.raises(ValueError):
        chooser('fb2', {'epub': ValueError('broken')})


def test_choose_update_source_real_files(tmp_path):
    "With the real readers, as the calibre plugin calls it."
    files = {
        'epub': fresh_file(tmp_path, 'epub', [1, 2, 3]).read_bytes(),
        'fb2': fresh_file(tmp_path, 'fb2', [1, 2]).read_bytes(),
    }
    foreign = (b'<?xml version="1.0" encoding="utf-8"?>\n'
               b'<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
               b'<description><title-info><book-title>T</book-title></title-info>'
               b'<document-info><program-used>calibre 9.14.0</program-used></document-info>'
               b'</description><body><section><p>text</p></section></body></FictionBook>')

    def run(fileform, book):
        return choose_update_source(
            fileform, lambda fmt: fmt in book,
            lambda fmt: get_dcsource_chaptercount(io.BytesIO(book[fmt]))[1])

    assert run('fb2', files) == ('fb2', 2)
    assert run('epub', files) == ('epub', 3)
    assert run('fb2', {'epub': files['epub']}) == ('epub', 3)
    assert run('fb2', {'fb2': foreign, 'epub': files['epub']}) == ('epub', 3)
    assert run('fb2', {'fb2': foreign}) == (None, None)
    assert run('epub', {'fb2': b'<FictionBook><not xml'}) == (None, None)


def test_preserve_deleted_chapters_on_conversion():
    from fanficfare.updatedata import preserve_deleted_chapters_on_conversion
    from tests.test_fb2 import make_adapter, make_config
    adapter = make_adapter(make_config(), {1: u'x'})
    ## looked up (and cached) before the conversion is known
    assert not adapter.preserve_deleted_chapters()
    assert preserve_deleted_chapters_on_conversion(adapter) is True
    assert adapter.preserve_deleted_chapters()

    ## with a chapter range: off, and no ConflictingOptions
    adapter = make_adapter(make_config(), {1: u'x', 2: u'y'})
    adapter.setChaptersRange('1', '1')
    assert preserve_deleted_chapters_on_conversion(adapter) is False
    assert not adapter.preserve_deleted_chapters()
