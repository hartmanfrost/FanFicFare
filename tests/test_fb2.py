# -*- coding: utf-8 -*-
"""FB2 output: writer validity, HTML conversion, reading FB2 back for
update, and CLI update/conversion between FB2 and EPUB.

Everything runs offline against a staged adapter (see
tests/adapters/update_harness.py); chapter downloads are counted so
updates can be checked to reuse the chapters already in the file.
"""
import argparse
import base64
import io
import os
import re
import shutil
from datetime import datetime

import pytest

from fanficfare import cli
from fanficfare import fb2utils
from fanficfare.configurable import Configuration
from fanficfare.epubutils import get_update_data as epub_get_update_data
from fanficfare.fb2utils import HtmlToFb2, fb2_section_to_html, section_content
from fanficfare.updatedata import detect_format, get_update_data, converted_filename
from fanficfare.writers.writer_epub import EpubWriter
from fanficfare.writers.writer_fb2 import FB2Writer

from tests.adapters.update_harness import CH, STORY_URL, StagedSiteAdapter

DEFAULTS_INI = os.path.join(os.path.dirname(cli.__file__), 'defaults.ini')
XSD_DIR = os.path.join(os.path.dirname(__file__), 'fb2xsd')
FB2NS = '{http://www.gribuser.ru/xml/fictionbook/2.0}'

# 1x1 transparent png
PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')

PERSONAL = (
    '[defaults]\n'
    'update_check_recent_chapters:0\n'
    'include_images:false\n'
    'is_adult:true\n')

RICH_CHAPTER = u'''
<div class="part_text">Первая строка
Вторая строка, <i>курсив</i> и <b>жирный</b> и <s>зачёркнутый</s>.



После пустой строки.</div>
<hr/>
<h3>Заголовок внутри главы</h3>
<p>Text with <a href="https://example.org/x?a=1&amp;b=2">a link</a> &amp; a &lt;tag&gt;.</p>
<p>&nbsp;</p>
<blockquote><p>Цитата.</p><footer>Автор цитаты</footer></blockquote>
<div class="poem"><p>Строка один<br/>Строка два</p><p>Второй куплет</p></div>
<p>Control\x0bchar and <em><strong>nested</strong></em><unclosed>tags
'''


class CountingAdapter(StagedSiteAdapter):
    """Staged adapter that counts chapter downloads, runs chapter text
    through utf8FromSoup like real adapters, and reports a fresh
    dateUpdated so writes aren't skipped as 'file is newer'."""
    cover_url = None

    def extractChapterUrlsAndMetadata(self):
        StagedSiteAdapter.extractChapterUrlsAndMetadata(self)
        self.story.setMetadata('title', u'Тестовая история')
        self.story.setMetadata('author', u'Автор')
        self.story.setMetadata('langcode', 'ru')
        self.story.setMetadata('dateUpdated', datetime.now())
        self.story.setMetadata('series', u'Серия [2]')
        self.story.addToList('genre', 'Fantasy')
        self.story.addToList('genre', 'Humor')
        if self.cover_url:
            self.setCoverImage(STORY_URL, self.cover_url)

    def getChapterTextNum(self, url, index):
        self.fetched.append(url)
        return self.utf8FromSoup(url, self.make_soup(self.content[url]))


def make_config(fileform='fb2', personal=PERSONAL):
    configuration = Configuration(['example.com'], fileform, lightweight=True)
    configuration.read(DEFAULTS_INI)
    configuration.read_file(io.StringIO(personal))
    return configuration


def chapter_list(nums):
    return [(u'Глава %d' % n, CH % n) for n in nums]


def make_adapter(configuration, content, cover_url=None):
    adapter = CountingAdapter(configuration, STORY_URL)
    adapter.site_chapters = chapter_list(sorted(content))
    adapter.content = dict((CH % n, html) for n, html in content.items())
    adapter.fetched = []
    adapter.cover_url = cover_url
    return adapter


def body_of(n):
    return u'<p>Текст главы %d.</p><p>Second <i>paragraph</i> %d.</p>' % (n, n)


def write_fb2(adapter):
    out = io.BytesIO()
    FB2Writer(adapter.configuration, adapter).writeStory(outstream=out)
    return out.getvalue()


def sections(fb2bytes):
    "chapter section xml strings, for comparing two writes."
    text = fb2bytes.decode('utf-8')
    return re.findall(r'<section id="ch\d+">.*?</section>', text, flags=re.S)


@pytest.fixture
def schemas(tmp_path):
    lxml_etree = pytest.importorskip('lxml.etree')
    strict = lxml_etree.XMLSchema(lxml_etree.parse(os.path.join(XSD_DIR, 'FictionBook.xsd')))
    ## 'lax': the same schema with the genres readers use for fan
    ## fiction added.
    laxdir = tmp_path / 'laxxsd'
    shutil.copytree(XSD_DIR, str(laxdir))
    genres = laxdir / 'FictionBookGenres.xsd'
    genres.write_text(genres.read_text(encoding='utf-8').replace(
        '<xs:enumeration value="antique"/>',
        '<xs:enumeration value="antique"/><xs:enumeration value="fanfiction"/>'
        '<xs:enumeration value="network_literature"/>'), encoding='utf-8')
    lax = lxml_etree.XMLSchema(lxml_etree.parse(str(laxdir / 'FictionBook.xsd')))

    def validate(data, strict_schema=False):
        schema = strict if strict_schema else lax
        ok = schema.validate(lxml_etree.fromstring(data))
        return ok, [str(e) for e in schema.error_log]
    return validate


##########################################################################
## Writer

def test_writer_valid_rich_chapter(schemas):
    adapter = make_adapter(make_config(), {1: RICH_CHAPTER, 2: body_of(2), 3: u'<div></div>'})
    data = write_fb2(adapter)
    ok, errors = schemas(data)
    assert ok, errors
    text = data.decode('utf-8')
    assert u'<book-title>Тестовая история</book-title>' in text
    assert u'<author><nickname>Автор</nickname>' in text
    assert u'<lang>ru</lang>' in text
    assert u'<sequence name="Серия" number="2"/>' in text
    assert u'<genre>fanfiction</genre><genre>sf_fantasy</genre><genre>humor</genre>' in text
    assert u'<src-url>%s</src-url>' % STORY_URL in text
    assert u'<p>Первая строка</p>' in text
    assert u'<emphasis>курсив</emphasis>' in text
    assert u'<strong>жирный</strong>' in text
    assert u'<strikethrough>зачёркнутый</strikethrough>' in text
    assert u'<empty-line/>' in text
    assert u'<subtitle>* * *</subtitle>' in text
    assert u'<subtitle>Заголовок внутри главы</subtitle>' in text
    assert u'<a l:href="https://example.org/x?a=1&amp;b=2">a link</a> &amp; a &lt;tag&gt;' in text
    assert u'<cite><p>Цитата.</p><text-author>Автор цитаты</text-author></cite>' in text
    assert u'<poem><stanza><v>Строка один</v><v>Строка два</v></stanza>' \
        u'<stanza><v>Второй куплет</v></stanza></poem>' in text
    assert u'Controlchar' in text
    ## the empty chapter is still a valid section
    assert u'<section id="ch0003"><title><p>Глава 3</p></title>\n<empty-line/>' in text


def test_writer_strict_valid_with_listed_genre(schemas):
    personal = PERSONAL + '[fb2]\nfb2_default_genre:sf_fantasy\n'
    adapter = make_adapter(make_config(personal=personal), {1: RICH_CHAPTER})
    ok, errors = schemas(write_fb2(adapter), strict_schema=True)
    assert ok, errors


def test_writer_images_and_cover(schemas, tmp_path):
    img = tmp_path / 'pic.png'
    img.write_bytes(PNG)
    cover = tmp_path / 'cover.png'
    cover.write_bytes(PNG)
    personal = PERSONAL.replace('include_images:false', 'include_images:true') + \
        'no_image_processing:true\n'
    content = {1: u'<p><img src="%s" alt="pic"/>Text after image.</p>' % img.as_uri(),
               2: body_of(2)}
    adapter = make_adapter(make_config(personal=personal), content,
                           cover_url=cover.as_uri())
    data = write_fb2(adapter)
    ok, errors = schemas(data)
    assert ok, errors
    text = data.decode('utf-8')
    assert re.search(r'<coverpage><image l:href="#cover\.png"/></coverpage>', text)
    ## section starts with the image: image goes in the section image slot
    assert re.search(r'<section id="ch0001"><title><p>Глава 1</p></title>\n'
                     r'<image l:href="#ffdl-[0-9a-f-]+\.png" alt="pic"/>\n<p>Text after image.</p>', text)
    assert text.count('<binary ') == 2

    upd = fb2utils.get_update_data(io.BytesIO(data))
    (source, filecount, soups, images, oldcover, bookmark, logfile, urlsoups, datamaps) = upd
    assert img.as_uri() in images
    assert images[img.as_uri()][1] == PNG
    assert oldcover[3] == 'OEBPS/images/cover.png'
    assert oldcover[4] == 'image/png'
    assert oldcover[5] == PNG
    assert urlsoups[CH % 1].find('img')['src'] == img.as_uri()


def test_metaonly_and_annotation(schemas):
    adapter = make_adapter(make_config(), {1: body_of(1)})
    adapter.getStoryMetadataOnly()
    adapter.story.setMetadata('description',
                              u'<p>Описание <img src="x.png"/> с <b>разметкой</b></p>'
                              u'<div class="epigraph"><p>e</p></div>')
    out = io.BytesIO()
    FB2Writer(adapter.configuration, adapter).writeStory(outstream=out, metaonly=True)
    ok, errors = schemas(out.getvalue())
    assert ok, errors
    text = out.getvalue().decode('utf-8')
    assert u'<annotation><p>Описание с <strong>разметкой</strong></p><cite><p>e</p></cite></annotation>' in text
    assert adapter.fetched == []


##########################################################################
## HTML -> FB2 conversion

@pytest.mark.parametrize('html, expected', [
    (u'<p>a<br/>b<br/><br/>c<br/><br/><br/>d</p>',
     [u'<p>a</p>', u'<p>b</p>', u'<p>c</p>', u'<empty-line/>', u'<p>d</p>']),
    (u'<p>  spaced \t out\n text&nbsp;&nbsp;nbsp  </p>',
     [u'<p>spaced out text\xa0\xa0nbsp</p>']),
    (u'<p>x <i> </i>y</p>', [u'<p>x y</p>']),
    (u'<p><i>one<br/>two</i></p>',
     [u'<p><emphasis>one</emphasis></p>', u'<p><emphasis>two</emphasis></p>']),
    (u'<p><a href="http://a/"><a href="http://b/">nested</a></a></p>',
     ## html5lib closes the first <a>
     [u'<p><a l:href="http://b/">nested</a></p>']),
    (u'<p><a href="/relative">rel</a> <a href="javascript:x()">js</a></p>',
     [u'<p>rel js</p>']),
    (u'<blockquote><blockquote><p>deep</p></blockquote></blockquote>',
     [u'<cite><p>deep</p></cite>']),
    (u'<blockquote><p class="text-author">A</p><p>q</p></blockquote>',
     [u'<cite><p>A</p><p>q</p></cite>']),
    (u'<blockquote class="epigraph"><h3>T</h3><p>e</p><p class="text-author">A</p></blockquote>',
     [u'<epigraph><p>T</p><p>e</p><text-author>A</text-author></epigraph>']),
    (u'<ul><li>one</li><li>two</li></ul>', [u'<p>• one</p>', u'<p>• two</p>']),
    (u'<pre>l1\nl2</pre>', [u'<p>l1</p>', u'<p>l2</p>']),
    (u'<script>x</script><style>y</style><p>z</p>', [u'<p>z</p>']),
    (u'<div class="poem">just text</div>',
     [u'<poem><stanza><v>just text</v></stanza></poem>']),
    (u'<div class="poem"><div class="stanza"></div></div>', []),
    (u'<p>unterminated <b>bold', [u'<p>unterminated <strong>bold</strong></p>']),
])
def test_html_to_fb2(html, expected):
    assert HtmlToFb2().convert(html) == expected


@pytest.mark.parametrize('inner, expected', [
    ## 3+ newlines are a blank line whether text or a block follows
    (u'A</p>\n\n\nB', [u'<p>A</p>', u'<empty-line/>', u'<p>B</p>']),
    (u'A</p>\n\n\n<p>B</p>', [u'<p>A</p>', u'<empty-line/>', u'<p>B</p>']),
    (u'A\n\n\n<p>B</p>', [u'<p>A</p>', u'<empty-line/>', u'<p>B</p>']),
    (u'<p>A\n\n\n</p><p>B</p>', [u'<p>A</p>', u'<empty-line/>', u'<p>B</p>']),
    ## ficbook's scene markers: the same on both sides
    (u'<p>A</p>\n\n\n<p style="text-align:center">***</p>\n\n\n<p>B</p>',
     [u'<p>A</p>', u'<empty-line/>', u'<p>***</p>', u'<empty-line/>', u'<p>B</p>']),
    (u'A\n\n\n<hr/>B', [u'<p>A</p>', u'<empty-line/>', u'<subtitle>* * *</subtitle>', u'<p>B</p>']),
    (u'A\n\n\n<h3>T</h3>', [u'<p>A</p>', u'<empty-line/>', u'<subtitle>T</subtitle>']),
    (u'A\n\n\n<ul><li>x</li></ul>', [u'<p>A</p>', u'<empty-line/>', u'<p>• x</p>']),
    (u'A\n\n\n<blockquote>q</blockquote>\n\n\nB',
     [u'<p>A</p>', u'<empty-line/>', u'<cite><p>q</p></cite>', u'<empty-line/>', u'<p>B</p>']),
    ## one or two newlines only end the paragraph
    (u'A</p>\n<p>B</p>', [u'<p>A</p>', u'<p>B</p>']),
    (u'A</p>\n\n<p>B</p>', [u'<p>A</p>', u'<p>B</p>']),
    ## nothing after them: dropped
    (u'<p>A</p>\n\n\n', [u'<p>A</p>']),
    (u'A\n\n\n', [u'<p>A</p>']),
])
def test_html_to_fb2_blank_lines_before_blocks(inner, expected):
    assert HtmlToFb2().convert(u'<div class="part_text">%s</div>' % inner) == expected


def test_html_to_fb2_br_before_block():
    assert HtmlToFb2().convert(u'<p>A<br/><br/><br/></p><p>B</p>') == \
        [u'<p>A</p>', u'<empty-line/>', u'<p>B</p>']
    assert HtmlToFb2().convert(u'<p>A<br/><br/><br/></p>') == [u'<p>A</p>']


def test_html_to_fb2_images_in_poem():
    "An image in a poem goes after it (a <v> can't hold a block image)."
    imgmap = {'images/a.png': 'a.png'}
    for cls in ('poem', 'verse'):
        html = (u'<div class="%s"><p>Строка один<br/><img src="images/a.png" alt="рисунок"/>'
                u'<br/>Строка два</p><p><img src="images/a.png"/></p></div>' % cls)
        assert HtmlToFb2(imgmap=imgmap).convert(html) == [
            u'<poem><stanza><v>Строка один</v><v>Строка два</v></stanza></poem>',
            u'<image l:href="#a.png" alt="рисунок"/>', u'<image l:href="#a.png"/>']
    ## annotations have no images: alt text, as before
    assert HtmlToFb2(imgmap=imgmap, allow_images=False).convert(
        u'<div class="poem"><p>x<br/><img src="images/a.png" alt="ALT"/></p></div>') == \
        [u'<poem><stanza><v>x</v><v>[ALT]</v></stanza></poem>']


def test_writer_image_in_poem_is_referenced(schemas, tmp_path):
    img = tmp_path / 'pic.png'
    img.write_bytes(PNG)
    personal = PERSONAL.replace('include_images:false', 'include_images:true') + \
        'no_image_processing:true\n'
    content = {1: u'<p>Before.</p><div class="verse"><p>Строка один<br/>'
                  u'<img src="%s" alt="рисунок"/><br/>Строка два</p></div>' % img.as_uri()}
    adapter = make_adapter(make_config(personal=personal), content)
    data = write_fb2(adapter)
    ok, errors = schemas(data)
    assert ok, errors
    text = data.decode('utf-8')
    binaries = set(re.findall(r'<binary id="([^"]+)"', text))
    referenced = set(re.findall(r'<image l:href="#([^"]+)"', text))
    assert binaries and binaries == referenced
    ## and reading it back, then writing again, gives the same section
    adapter2 = make_adapter(make_config(personal=personal), content)
    (adapter2.oldchapters, adapter2.oldimgs, adapter2.oldcover,
     adapter2.calibrebookmark, adapter2.logfile, adapter2.oldchaptersmap,
     adapter2.oldchaptersdata) = get_update_data(io.BytesIO(data))[2:9]
    assert sections(write_fb2(adapter2)) == sections(data)
    assert adapter2.fetched == []


def test_html_to_fb2_hr_text_and_images():
    assert HtmlToFb2(hr_text='').convert(u'<p>a</p><hr/><p>b</p>') == \
        [u'<p>a</p>', u'<empty-line/>', u'<p>b</p>']
    conv = HtmlToFb2(imgmap={'images/a.jpg': 'a.jpg'}, allow_images=False)
    assert conv.convert(u'<p><img src="images/a.jpg" alt="ALT"/></p>') == [u'<p>[ALT]</p>']


def test_section_content_rules():
    assert section_content([]) == [u'<empty-line/>']
    assert section_content([u'<image l:href="#a"/>']) == [u'<image l:href="#a"/>', u'<empty-line/>']
    assert section_content([u'<epigraph><p>e</p></epigraph>', u'<p>x</p>',
                            u'<epigraph><p>f</p></epigraph>']) == \
        [u'<epigraph><p>e</p></epigraph>', u'<p>x</p>', u'<cite><p>f</p></cite>']


def _fb2_roundtrip(adapter, html):
    "blocks of html, and blocks after FB2 -> HTML -> utf8FromSoup."
    from xml.etree import ElementTree
    b1 = section_content(HtmlToFb2().convert(html))
    el = ElementTree.fromstring(
        u'<section xmlns:l="http://www.w3.org/1999/xlink">%s</section>' % u''.join(b1))
    soup = fb2utils.make_soup(u'<html><body>%s</body></html>' %
                              fb2_section_to_html(el)).find('body')
    b2 = section_content(HtmlToFb2().convert(adapter.utf8FromSoup(None, soup)))
    return b1, b2


@pytest.mark.parametrize('extra', [
    '',
    'remove_empty_p:true\nreplace_br_with_p:true\n',
])
def test_fb2_html_fixed_point(extra):
    """FB2 -> HTML -> FB2 must give the same FB2, or every update would
    change chapters already in the file."""
    adapter = make_adapter(make_config(personal=PERSONAL + extra), {1: u''})
    for html in (RICH_CHAPTER,
                 u'<blockquote class="epigraph"><p>e</p><p class="text-author">A</p></blockquote><p>x</p>',
                 u'<div class="poem"><h4>Title</h4><p>a<br/>b</p><p class="text-author">P</p></div>',
                 u'<p>a</p><p>&nbsp;</p><p>&nbsp;</p><p>b</p>',
                 u'<div class="part_text"><p>a</p>\n\n\n<p>***</p>\n\n\n\n<p>b</p>\n\n\n</div>'):
        b1, b2 = _fb2_roundtrip(adapter, html)
        assert b1 == b2


##########################################################################
## FB2 read back

def test_roundtrip_chapters_and_metadata():
    adapter = make_adapter(make_config(), {n: body_of(n) for n in (1, 2, 3)})
    first = write_fb2(adapter)
    assert detect_format(io.BytesIO(first)) == 'fb2'

    (source, filecount, soups, images, oldcover, bookmark, logfile,
     urlsoups, datamaps) = get_update_data(io.BytesIO(first))
    assert source == STORY_URL
    assert filecount == 3
    assert list(urlsoups) == [CH % n for n in (1, 2, 3)]
    assert datamaps[CH % 2]['title'] == u'Глава 2'
    assert datamaps[CH % 2]['url'] == CH % 2
    assert 'fb2_id' not in datamaps[CH % 2]
    assert u'Текст главы 2.' in urlsoups[CH % 2].get_text()
    assert oldcover is None and images == {}

    ## updating with those chapters downloads nothing and writes the
    ## same chapters again.
    adapter2 = make_adapter(make_config(), {n: body_of(n) for n in (1, 2, 3)})
    (adapter2.oldchapters, adapter2.oldimgs, adapter2.oldcover,
     adapter2.calibrebookmark, adapter2.logfile, adapter2.oldchaptersmap,
     adapter2.oldchaptersdata) = get_update_data(io.BytesIO(first))[2:9]
    second = write_fb2(adapter2)
    assert adapter2.fetched == []
    assert sections(second) == sections(first)


def test_read_zip_and_entities_and_cp1251(tmp_path):
    adapter = make_adapter(make_config(personal=PERSONAL + '[fb2]\nzip_output:true\n'),
                           {1: body_of(1)})
    out = io.BytesIO()
    FB2Writer(adapter.configuration, adapter).writeStory(outstream=out)
    assert out.getvalue()[:2] == b'PK'
    assert detect_format(io.BytesIO(out.getvalue())) == 'fb2'
    assert get_update_data(io.BytesIO(out.getvalue()))[1] == 1

    foreign = (u'<?xml version="1.0" encoding="windows-1251"?>\n'
               u'<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" '
               u'xmlns:xlink="http://www.w3.org/1999/xlink"><description><title-info>'
               u'<book-title>Книга&nbsp;&mdash;</book-title></title-info></description>'
               u'<body><section><p><a xlink:href="https://example.com/story/1">Ссылка</a></p>'
               u'</section></body></FictionBook>').encode('cp1251')
    data = fb2utils.get_update_data(io.BytesIO(foreign))
    assert data[0] is None and data[1] == 0 and data[7] == {}
    assert fb2utils.get_story_url_from_fb2_html(io.BytesIO(foreign)) == 'https://example.com/story/1'
    root = fb2utils.parse_fb2(io.BytesIO(foreign))
    assert root.find('description/title-info/book-title').text == u'Книга\xa0—'


def test_story_url_from_calibre_converted_fb2_links():
    """calibre writes '=' in link targets as %3d: such a link is still
    found (with the real URL check, not a monkeypatched one)."""
    def fb2(href):
        return io.BytesIO((
            u'<?xml version="1.0" encoding="UTF-8"?>\n'
            u'<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" '
            u'xmlns:l="http://www.w3.org/1999/xlink"><description><title-info>'
            u'<book-title>T</book-title></title-info></description>'
            u'<body><section><p><a l:href="https://example.org/nope">x</a> '
            u'<a l:href="%s">Story</a></p></section></body></FictionBook>' % href).encode('utf-8'))
    find = fb2utils.get_story_url_from_fb2_html
    assert find(fb2(u'http://test1.com?sid%3d3001'), cli._is_story_url) == \
        u'http://test1.com?sid=3001'
    assert find(fb2(u'http://test1.com?sid=3001'), cli._is_story_url) == \
        u'http://test1.com?sid=3001'
    ## accepted as it is: returned as it is, not unquoted
    assert find(fb2(u'https://ficbook.net/readfic/1%2D2'), lambda u: True) == \
        u'https://example.org/nope'
    assert find(fb2(u'https://ficbook.net/readfic/1%2D2'),
                lambda u: 'ficbook' in u) == u'https://ficbook.net/readfic/1%2D2'
    assert find(fb2(u'http://test1.com?nothing%3d1'), cli._is_story_url) is None


def test_converted_filename():
    assert converted_filename('a/b.epub', 'fb2') == 'a/b.fb2'
    assert converted_filename('a/b.fb2', 'epub') == 'a/b.epub'
    assert converted_filename('a/b.fb2.zip', 'epub') == 'a/b.epub'
    assert converted_filename('a/b.c', 'fb2') == 'a/b.c.fb2'


##########################################################################
## CLI update and conversion

def make_options(**overrides):
    opts = dict(update=True, updatealways=False, force=False, metaonly=False,
                unnew=False, normalize=False, list=False, downloadlist=None,
                nooutput=False, format='epub', format_explicit=False,
                interactive=False, jsonmeta=False, jsonmetafile=None,
                nometachapters=False, updatecover=False, save_cache=False,
                progressbar=False, mozillacookies=None, begin=None, end=None,
                configfile=None, options=None)
    opts.update(overrides)
    return argparse.Namespace(**opts)


def run_cli(monkeypatch, capsys, arg, content, personal=PERSONAL, cover_url=None,
            **options):
    """cli.do_download(arg) against a site serving content.  Returns
    (adapter, printed output, warnings)."""
    made = []

    def get_adapter(config, url):
        adapter = make_adapter(config, content, cover_url=cover_url)
        made.append(adapter)
        return adapter

    monkeypatch.setattr(cli.adapters, 'getConfigSectionsFor', lambda url: ['example.com'])
    monkeypatch.setattr(cli.adapters, 'getAdapter', get_adapter)
    monkeypatch.setattr(cli.adapters, 'getNormalStoryURL',
                        lambda url: url if url.startswith(STORY_URL) else None)
    monkeypatch.setattr(cli, 'call', lambda *args, **kwargs: 0)
    warned = []
    cli.do_download(arg, make_options(**options), open(DEFAULTS_INI).read(), personal,
                    warn=warned.append, fail=warned.append)
    return made[-1] if made else None, capsys.readouterr().out, warned


def fresh_file(tmp_path, fileform, nums, name='story', content=None, personal=PERSONAL,
               ext=None):
    content = content or {n: body_of(n) for n in nums}
    adapter = make_adapter(make_config(fileform, personal), content)
    adapter.getStory()
    path = tmp_path / ('%s.%s' % (name, ext or fileform))
    writer = FB2Writer if fileform == 'fb2' else EpubWriter
    with open(str(path), 'wb') as out:
        writer(adapter.configuration, adapter).writeStory(outstream=out)
    return path


def test_cli_update_fb2_no_new_chapters_fetches_nothing(monkeypatch, capsys, tmp_path):
    ## RICH_CHAPTER has entities, control chars and every construct the
    ## converter knows; the -U rewrite below must not change it.
    content = {1: RICH_CHAPTER, 2: body_of(2), 3: body_of(3)}
    path = fresh_file(tmp_path, 'fb2', [1, 2, 3], content=content)
    before = path.read_bytes()
    adapter, output, warned = run_cli(monkeypatch, capsys, str(path), content)
    assert 'already contains 3 chapters.' in output
    assert adapter.fetched == []
    assert path.read_bytes() == before
    assert warned == []

    ## -U rewrites the file, still without downloading chapters.
    adapter, output, warned = run_cli(monkeypatch, capsys, str(path), content,
                                      updatealways=True)
    assert 'Do update - fb2(3) vs url(3)' in output
    assert adapter.fetched == []
    assert detect_format(str(path)) == 'fb2'
    assert sections(path.read_bytes()) == sections(before)


def test_cli_update_fb2_new_chapter_fetches_only_it(monkeypatch, capsys, tmp_path):
    path = fresh_file(tmp_path, 'fb2', [1, 2, 3])
    adapter, output, warned = run_cli(monkeypatch, capsys, str(path),
                                      {n: body_of(n) for n in (1, 2, 3, 4)})
    assert 'Do update - fb2(3) vs url(4)' in output
    assert adapter.fetched == [CH % 4]
    data = get_update_data(str(path))
    assert data[1] == 4
    assert list(data[7]) == [CH % n for n in (1, 2, 3, 4)]


def test_cli_update_fb2_by_url(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    personal = PERSONAL + 'output_filename: story${formatext}\n'
    fresh_file(tmp_path, 'fb2', [1, 2])
    adapter, output, warned = run_cli(monkeypatch, capsys, STORY_URL,
                                      {n: body_of(n) for n in (1, 2, 3)},
                                      personal=personal, format='fb2', format_explicit=True)
    assert 'Updating story.fb2, URL: %s' % STORY_URL in output
    assert adapter.fetched == [CH % 3]
    assert get_update_data('story.fb2')[1] == 3


def test_cli_convert_epub_to_fb2_reuses_chapters(monkeypatch, capsys, tmp_path, schemas):
    epub = fresh_file(tmp_path, 'epub', [1, 2, 3])
    before = epub.read_bytes()
    adapter, output, warned = run_cli(monkeypatch, capsys, str(epub),
                                      {n: body_of(n) for n in (1, 2, 3)},
                                      format='fb2', format_explicit=True)
    fb2 = tmp_path / 'story.fb2'
    assert 'Converting %s to fb2: %s' % (epub, fb2) in output
    assert 'Do update - epub(3) vs url(3)' in output
    assert adapter.fetched == []
    assert epub.read_bytes() == before, 'source epub must not be touched'
    ok, errors = schemas(fb2.read_bytes())
    assert ok, errors
    data = get_update_data(str(fb2))
    assert data[1] == 3
    assert list(data[7]) == [CH % n for n in (1, 2, 3)]
    assert u'Текст главы 3.' in data[7][CH % 3].get_text()
    assert warned == []


def test_cli_convert_epub_to_fb2_by_url(monkeypatch, capsys, tmp_path):
    "-u URL -f fb2 with only the EPUB on disk converts it."
    monkeypatch.chdir(tmp_path)
    personal = PERSONAL + 'output_filename: story${formatext}\n'
    fresh_file(tmp_path, 'epub', [1, 2])
    adapter, output, warned = run_cli(monkeypatch, capsys, STORY_URL,
                                      {n: body_of(n) for n in (1, 2, 3)},
                                      personal=personal, format='fb2', format_explicit=True)
    assert 'Converting story.epub to fb2: story.fb2' in output
    assert adapter.fetched == [CH % 3]
    assert get_update_data('story.fb2')[1] == 3


def test_cli_convert_fb2_to_epub(monkeypatch, capsys, tmp_path):
    fb2 = fresh_file(tmp_path, 'fb2', [1, 2])
    adapter, output, warned = run_cli(monkeypatch, capsys, str(fb2),
                                      {n: body_of(n) for n in (1, 2)},
                                      format='epub', format_explicit=True)
    assert adapter.fetched == []
    epub = tmp_path / 'story.epub'
    data = epub_get_update_data(str(epub))
    assert data[1] == 2
    assert list(data[7]) == [CH % 1, CH % 2]


def test_cli_cover_kept_on_update_and_conversion(monkeypatch, capsys, tmp_path):
    cover = tmp_path / 'cover.png'
    cover.write_bytes(PNG)
    personal = PERSONAL.replace('include_images:false', 'include_images:true') + \
        'no_image_processing:true\n'
    content = {n: body_of(n) for n in (1, 2)}
    adapter = make_adapter(make_config('epub', personal), content, cover_url=cover.as_uri())
    adapter.getStory()
    epub = tmp_path / 'story.epub'
    with open(str(epub), 'wb') as out:
        EpubWriter(adapter.configuration, adapter).writeStory(outstream=out)
    ## the cli sets never_make_cover on update, so the cover can only
    ## come from the old file.
    adapter, output, warned = run_cli(monkeypatch, capsys, str(epub), content,
                                      personal=personal, cover_url=cover.as_uri(),
                                      format='fb2', format_explicit=True)
    fb2 = tmp_path / 'story.fb2'
    assert fb2utils.get_cover_img(str(fb2)) == ('image/png', PNG)
    adapter, output, warned = run_cli(monkeypatch, capsys, str(fb2), content,
                                      personal=personal, cover_url=cover.as_uri(),
                                      updatealways=True)
    assert fb2utils.get_cover_img(str(fb2)) == ('image/png', PNG)


def test_cli_update_preserves_deleted_chapter_in_fb2(monkeypatch, capsys, tmp_path):
    personal = PERSONAL + 'update_preserve_deleted_chapters:true\n'
    path = fresh_file(tmp_path, 'fb2', [1, 2, 3])
    adapter, output, warned = run_cli(monkeypatch, capsys, str(path),
                                      {n: body_of(n) for n in (1, 3, 4)},
                                      personal=personal)
    assert adapter.fetched == [CH % 4]
    data = get_update_data(str(path))
    assert list(data[7]) == [CH % n for n in (1, 2, 3, 4)]
    assert data[8][CH % 2]['title'] == u'Глава 2'


def foreign_fb2_bytes(cover=False):
    "An FB2 without FanFicFare data, as calibre's conversion of an FFF EPUB."
    return (
        u'<?xml version="1.0" encoding="UTF-8"?>\n'
        u'<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" '
        u'xmlns:l="http://www.w3.org/1999/xlink"><description><title-info>'
        u'<genre>sf_fantasy</genre><author><first-name/><last-name>X</last-name></author>'
        u'<book-title>T</book-title>%s<lang>ru</lang></title-info>'
        u'<document-info><program-used>calibre</program-used></document-info></description>'
        u'<body><section><p><a l:href="https://example.com/authors/1">by</a> '
        u'<a l:href="%s">Story</a></p></section>'
        u'<section><p>Old text</p></section></body>%s</FictionBook>' % (
            u'<coverpage><image l:href="#cover.png"/></coverpage>' if cover else u'',
            STORY_URL,
            u'<binary id="cover.png" content-type="image/png">%s</binary>' %
            base64.b64encode(PNG).decode('ascii') if cover else u'')).encode('utf-8')


def test_cli_update_foreign_fb2_downloads_everything(monkeypatch, capsys, tmp_path):
    "FB2 without FanFicFare data (eg calibre's conversion): full download."
    path = tmp_path / 'foreign.fb2'
    path.write_bytes(foreign_fb2_bytes())
    adapter, output, warned = run_cli(monkeypatch, capsys, str(path),
                                      {n: body_of(n) for n in (1, 2)})
    assert 'has no FanFicFare chapter data' in output
    assert adapter.fetched == [CH % 1, CH % 2]
    data = get_update_data(str(path))
    assert data[0] == STORY_URL and data[1] == 2


def test_cli_update_foreign_fb2_keeps_its_cover(monkeypatch, capsys, tmp_path):
    """-u sets never_make_cover, so the cover of the FB2 being replaced
    is the only one there is: keep it, by file and by URL."""
    path = tmp_path / 'story.fb2'
    path.write_bytes(foreign_fb2_bytes(cover=True))
    assert fb2utils.get_cover_img(str(path)) == ('image/png', PNG)
    adapter, output, warned = run_cli(monkeypatch, capsys, str(path),
                                      {n: body_of(n) for n in (1, 2)})
    assert adapter.fetched == [CH % 1, CH % 2]
    assert fb2utils.get_cover_img(str(path)) == ('image/png', PNG)

    monkeypatch.chdir(tmp_path)
    path.write_bytes(foreign_fb2_bytes(cover=True))
    adapter, output, warned = run_cli(monkeypatch, capsys, STORY_URL,
                                      {n: body_of(n) for n in (1, 2)},
                                      personal=PERSONAL + 'output_filename: story${formatext}\n',
                                      format='fb2', format_explicit=True)
    assert adapter.fetched == [CH % 1, CH % 2]
    assert get_update_data('story.fb2')[1] == 2
    assert fb2utils.get_cover_img('story.fb2') == ('image/png', PNG)


def test_cli_update_by_url_foreign_fb2_downloads_everything(monkeypatch, capsys, tmp_path):
    "-u URL with only an FB2 from another program: as -u that file."
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'story.fb2').write_bytes(foreign_fb2_bytes())
    adapter, output, warned = run_cli(monkeypatch, capsys, STORY_URL,
                                      {n: body_of(n) for n in (1, 2)},
                                      personal=PERSONAL + 'output_filename: story${formatext}\n',
                                      format='fb2', format_explicit=True)
    assert 'story.fb2 has no FanFicFare chapter data' in output
    assert warned == []
    assert adapter.fetched == [CH % 1, CH % 2]
    assert get_update_data('story.fb2')[1] == 2


def test_cli_update_by_url_skips_foreign_fb2_for_epub(monkeypatch, capsys, tmp_path):
    """-u URL -f fb2 with an FB2 from another program and a FanFicFare
    EPUB of the same name: convert the EPUB (as the plugin does)."""
    monkeypatch.chdir(tmp_path)
    fresh_file(tmp_path, 'epub', [1, 2])
    (tmp_path / 'story.fb2').write_bytes(foreign_fb2_bytes())
    adapter, output, warned = run_cli(monkeypatch, capsys, STORY_URL,
                                      {n: body_of(n) for n in (1, 2, 3)},
                                      personal=PERSONAL + 'output_filename: story${formatext}\n',
                                      format='fb2', format_explicit=True)
    assert 'Converting story.epub to fb2: story.fb2' in output
    assert warned == []
    assert adapter.fetched == [CH % 3]
    assert list(get_update_data('story.fb2')[7]) == [CH % n for n in (1, 2, 3)]


def test_cli_update_by_url_prefers_fffs_fb2_over_epub(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    fresh_file(tmp_path, 'epub', [1])
    fresh_file(tmp_path, 'fb2', [1, 2])
    adapter, output, warned = run_cli(monkeypatch, capsys, STORY_URL,
                                      {n: body_of(n) for n in (1, 2, 3)},
                                      personal=PERSONAL + 'output_filename: story${formatext}\n',
                                      format='fb2', format_explicit=True)
    assert 'Updating story.fb2, URL' in output and 'Converting' not in output
    assert adapter.fetched == [CH % 3]


def test_cli_convert_again_updates_the_converted_file(monkeypatch, capsys, tmp_path):
    """Running '-u story.epub -f fb2' again (an interrupted batch) updates
    story.fb2 from itself: nothing fetched again, nothing lost."""
    epub = fresh_file(tmp_path, 'epub', [1, 2])
    fb2 = tmp_path / 'story.fb2'
    adapter, output, warned = run_cli(monkeypatch, capsys, str(epub),
                                      {n: body_of(n) for n in (1, 2, 3)},
                                      format='fb2', format_explicit=True)
    assert adapter.fetched == [CH % 3]
    before = fb2.read_bytes()
    adapter, output, warned = run_cli(monkeypatch, capsys, str(epub),
                                      {n: body_of(n) for n in (1, 2, 3)},
                                      format='fb2', format_explicit=True)
    assert 'story.fb2 already has FanFicFare chapter data: updating it instead of converting' in output
    assert 'already contains 3 chapters.' in output
    assert adapter.fetched == []
    assert fb2.read_bytes() == before

    ## chapter 3 removed from the site: story.fb2 keeps it, as -u
    ## story.fb2 would, instead of being rewritten from the EPUB.
    adapter, output, warned = run_cli(monkeypatch, capsys, str(epub),
                                      {n: body_of(n) for n in (1, 2)},
                                      format='fb2', format_explicit=True)
    assert warned and 'more than source' in warned[0]
    assert list(get_update_data(str(fb2))[7]) == [CH % n for n in (1, 2, 3)]


def test_cli_convert_from_epub_over_foreign_fb2(monkeypatch, capsys, tmp_path):
    "An FB2 from another program next to the EPUB is converted over."
    epub = fresh_file(tmp_path, 'epub', [1, 2])
    (tmp_path / 'story.fb2').write_bytes(foreign_fb2_bytes())
    adapter, output, warned = run_cli(monkeypatch, capsys, str(epub),
                                      {n: body_of(n) for n in (1, 2)},
                                      format='fb2', format_explicit=True)
    assert 'Converting' in output
    assert adapter.fetched == []
    assert get_update_data(str(tmp_path / 'story.fb2'))[1] == 2


@pytest.mark.parametrize('updatealways', [False, True])
def test_cli_convert_keeps_chapters_the_site_removed(monkeypatch, capsys, tmp_path, updatealways):
    """A conversion only changes the format: chapters the site no longer
    has are kept (no 'more than source' refusal), nothing is fetched."""
    epub = fresh_file(tmp_path, 'epub', [1, 2, 3])
    adapter, output, warned = run_cli(monkeypatch, capsys, str(epub),
                                      {n: body_of(n) for n in (1, 3)},
                                      format='fb2', format_explicit=True,
                                      updatealways=updatealways)
    assert warned == []
    assert adapter.fetched == []
    data = get_update_data(str(tmp_path / 'story.fb2'))
    assert list(data[7]) == [CH % n for n in (1, 2, 3)]
    assert data[8][CH % 2]['title'] == u'Глава 2'
    assert u'Текст главы 2.' in data[7][CH % 2].get_text()


def test_cli_convert_keeps_removed_chapters_and_adds_new(monkeypatch, capsys, tmp_path):
    epub = fresh_file(tmp_path, 'epub', [1, 2, 3])
    adapter, output, warned = run_cli(monkeypatch, capsys, str(epub),
                                      {n: body_of(n) for n in (1, 3, 4)},
                                      format='fb2', format_explicit=True)
    assert adapter.fetched == [CH % 4]
    assert list(get_update_data(str(tmp_path / 'story.fb2'))[7]) == \
        [CH % n for n in (1, 2, 3, 4)]


def test_cli_same_format_update_still_refuses_fewer_chapters(monkeypatch, capsys, tmp_path):
    "Not a conversion: upstream's 'more than source' as before."
    epub = fresh_file(tmp_path, 'epub', [1, 2, 3])
    before = epub.read_bytes()
    adapter, output, warned = run_cli(monkeypatch, capsys, str(epub),
                                      {n: body_of(n) for n in (1, 3)})
    assert warned and 'contains 3 chapters, more than source: 2.' in warned[0]
    assert epub.read_bytes() == before


def test_cli_convert_with_chapter_range(monkeypatch, capsys, tmp_path):
    """A chapter range can't be combined with preserving deleted
    chapters (ConflictingOptions), so a conversion with one doesn't
    preserve them and counts chapters in the range, as an update does."""
    epub = fresh_file(tmp_path, 'epub', [1, 2, 3])
    adapter, output, warned = run_cli(monkeypatch, capsys, str(epub),
                                      {n: body_of(n) for n in (1, 2, 3)},
                                      format='fb2', format_explicit=True, begin='1', end='3')
    assert warned == []
    assert adapter.fetched == []
    assert not adapter.preserve_deleted_chapters()
    assert list(get_update_data(str(tmp_path / 'story.fb2'))[7]) == [CH % n for n in (1, 2, 3)]


def test_cli_update_unreadable_fb2_fails_cleanly(monkeypatch, capsys, tmp_path):
    path = tmp_path / 'broken.fb2'
    path.write_bytes(b'<?xml version="1.0"?><FictionBook><body><section><p>unclosed')
    adapter, output, warned = run_cli(monkeypatch, capsys, str(path), {1: body_of(1)})
    assert adapter is None
    assert warned and 'Failed to read file' in warned[0]


def test_cli_validate_update_formats():
    parser = cli.mkParser(False)
    for argv in (['-u', 'x.epub'], ['-u', '-f', 'fb2', 'x.fb2'], ['-f', 'fb2', 'http://x']):
        options, args = parser.parse_args(argv)
        cli.expandOptions(options)
        cli.validateOptions(parser, options, args)
    options, args = parser.parse_args(['-u', '-f', 'mobi', 'x.epub'])
    cli.expandOptions(options)
    with pytest.raises(SystemExit):
        cli.validateOptions(parser, options, args)
    options, args = parser.parse_args(['x'])
    cli.expandOptions(options)
    assert options.format == 'epub' and options.format_explicit is False


def test_cli_update_fb2_mark_new_chapters(monkeypatch, capsys, tmp_path):
    personal = PERSONAL + 'mark_new_chapters:true\n'
    path = fresh_file(tmp_path, 'fb2', [1, 2])
    adapter, output, warned = run_cli(monkeypatch, capsys, str(path),
                                      {n: body_of(n) for n in (1, 2, 3)},
                                      personal=personal)
    assert adapter.fetched == [CH % 3]
    text = path.read_text(encoding='utf-8')
    titles = re.findall(r'<section id="ch\d+"><title><p>(.*?)</p>', text)
    assert titles == [u'Глава 1', u'Глава 2', u'(new) Глава 3']
    datamaps = get_update_data(str(path))[8]
    assert datamaps[CH % 3]['mark_new'] is True
    assert datamaps[CH % 1]['mark_new'] is False


def test_cli_update_fb2_zip_in_place(monkeypatch, capsys, tmp_path):
    personal = PERSONAL + '[fb2]\nzip_output:true\n'
    path = fresh_file(tmp_path, 'fb2', [1, 2], personal=personal, ext='fb2.zip')
    assert path.read_bytes()[:2] == b'PK'
    adapter, output, warned = run_cli(monkeypatch, capsys, str(path),
                                      {n: body_of(n) for n in (1, 2, 3)})
    assert adapter.fetched == [CH % 3]
    assert path.read_bytes()[:2] == b'PK'
    assert detect_format(str(path)) == 'fb2'
    assert get_update_data(str(path))[1] == 3
    assert sorted(os.listdir(str(tmp_path))) == ['story.fb2.zip']
