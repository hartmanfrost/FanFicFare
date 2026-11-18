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

"""FictionBook 2 (FB2) helpers.

* HtmlToFb2 flattens chapter (X)HTML into FB2 block elements.  It is
  used by writers/writer_fb2.py.
* fb2_section_to_html() turns an FB2 <section> back into HTML that
  HtmlToFb2 converts to the same FB2 again, so updating a story
  stored as FB2 does not degrade the chapters already in it.
* get_update_data() reads an FB2 written by FanFicFare back for
  update, returning the same tuple as epubutils.get_update_data().

FanFicFare keeps what it needs for updates (chapter URLs and the
per-chapter data the EPUB writer stores in its fff_chapter_data meta
tags, original image URLs, the update log, ...) as JSON in a
<custom-info info-type="fanficfare-data"> element, which is valid
FB2.  FB2 files without it (written by other programs) can still be
read for their story URL, but have no reusable chapters.
"""

import base64
import html
import json
import logging
import re
import warnings
import zipfile
from io import BytesIO
from urllib.parse import unquote
from xml.etree import ElementTree

import bs4

from .htmlheuristics import was_run_marker as REPLACE_BR_WITH_P_MARKER

logger = logging.getLogger(__name__)

FB2_NS = "http://www.gribuser.ru/xml/fictionbook/2.0"
XLINK_NS = "http://www.w3.org/1999/xlink"

## info-type of the <custom-info> element holding FanFicFare's own
## data.  The JSON inside carries a version number, 'v'.
FFF_DATA_INFO_TYPE = "fanficfare-data"
FFF_DATA_VERSION = 1

FAILED_CHAPTER_URL = "chapter url removed due to failure"

## Characters that are not allowed in XML 1.0 documents.
_XML_ILLEGAL = re.compile(u'[\x00-\x08\x0b\x0c\x0e-\x1f￾￿\ud800-\udfff]')

## HTML whitespace.  Deliberately *not* \s, which would also collapse
## non-breaking spaces.
_HTML_WS_RUN = re.compile(u'[ \t\n\r\f]+')
_LINE_WS_RUN = re.compile(u'[ \t\r\f]+')

MIME_EXT = {
    'image/jpeg': 'jpg',
    'image/jpg': 'jpg',
    'image/png': 'png',
    'image/gif': 'gif',
    'image/svg+xml': 'svg',
    'image/webp': 'webp',
    'image/avif': 'avif',
}

EXT_MIME = {
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'png': 'image/png',
    'gif': 'image/gif',
    'svg': 'image/svg+xml',
    'webp': 'image/webp',
    'avif': 'image/avif',
}

def xtext(s):
    "Escape text for XML element content, dropping XML-illegal characters."
    s = _XML_ILLEGAL.sub(u'', u"%s" % s)
    return s.replace(u'&', u'&amp;').replace(u'<', u'&lt;').replace(u'>', u'&gt;')

def xattr(s):
    "Quoted, escaped XML attribute value."
    return u'"' + xtext(s).replace(u'"', u'&quot;') + u'"'

def ncname(s, prefix='id'):
    "Make s usable as an xs:ID / NCName."
    s = re.sub(r'[^A-Za-z0-9_.-]', '_', u"%s" % s)
    if not re.match(r'[A-Za-z_]', s):
        s = prefix + '_' + s
    return s

INLINE_MAP = {
    'b': 'strong', 'strong': 'strong',
    'i': 'emphasis', 'em': 'emphasis', 'cite': 'emphasis', 'dfn': 'emphasis',
    'var': 'emphasis', 'u': 'emphasis', 'ins': 'emphasis',
    's': 'strikethrough', 'strike': 'strikethrough', 'del': 'strikethrough',
    'sub': 'sub', 'sup': 'sup',
    'code': 'code', 'tt': 'code', 'kbd': 'code', 'samp': 'code',
}
INLINE_FB2 = ('strong', 'emphasis', 'strikethrough', 'sub', 'sup', 'code')
HEADINGS = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
BLOCKS = {'p', 'div', 'section', 'article', 'header', 'footer', 'aside', 'main',
          'nav', 'address', 'center', 'figure', 'figcaption', 'pre', 'ul', 'ol',
          'li', 'dl', 'dt', 'dd', 'table', 'thead', 'tbody', 'tfoot', 'tr',
          'caption', 'body', 'html', 'form', 'fieldset', 'details', 'summary',
          'blockquote', 'hr', 'td', 'th'}
SKIP = {'script', 'style', 'head', 'title', 'meta', 'link', 'iframe', 'noscript',
        'fff_hide_noscript', 'svg', 'object', 'embed', 'button', 'input',
        'select', 'textarea', 'template'}

## CSS classes HtmlToFb2 maps to FB2 structures.  The fb2_* ones are
## what fb2_section_to_html() emits, so FB2 -> HTML -> FB2 is stable;
## the others are common in hand-made HTML.
EMPTY_LINE_CLASSES = {'fb2_empty_line'}
SUBTITLE_CLASSES = {'fb2_subtitle'}
POEM_CLASSES = {'fb2_poem', 'poem', 'verse'}
POEM_TITLE_CLASSES = {'fb2_poem_title'}
STANZA_CLASSES = {'fb2_stanza', 'stanza'}
EPIGRAPH_CLASSES = {'fb2_epigraph', 'epigraph'}
TEXT_AUTHOR_CLASSES = {'fb2_text_author', 'text-author', 'text_author'}

_STANZA_BREAK = u'\x00stanza-break'

def _classes(tag):
    c = tag.get('class') or []
    if isinstance(c, str):
        c = c.split()
    return set(c)

def _tidy_inline(body):
    "Drop empty inline elements and collapse runs of spaces."
    prev = None
    while prev != body:
        prev = body
        body = re.sub(r'<(strong|emphasis|strikethrough|sub|sup|code)>( *)</\1>', r'\2', body)
        body = re.sub(r'<a l:href="[^"]*">( *)</a>', r'\1', body)
    return re.sub(u' {2,}', u' ', body)


class HtmlToFb2(object):
    """Flatten (X)HTML into a list of FB2 block elements (as strings).

    imgmap: {img src: binary id} for images that are included.
    allow_images: False for <annotation>, which can't hold images.
    prewrap_classes: classes that mean CSS white-space:pre-wrap, so a
    raw newline is a line break (ficbook's 'part_text').
    hr_text: <hr> becomes <subtitle>hr_text</subtitle>, or
    <empty-line/> when hr_text is empty.
    linkmap: {chapter url: '#section_id'} for internalize_text_links.

    Line breaks: one or two <br> (or raw newlines in pre-wrap text)
    start a new paragraph, three or more also add an <empty-line/>,
    whether text or a block element (<p>***</p>) comes after them.
    """

    def __init__(self, imgmap=None, allow_images=True,
                 prewrap_classes=('part_text', 'text-preline'),
                 hr_text=u'* * *', linkmap=None, line_mode=False):
        self.imgmap = imgmap or {}
        self.allow_images = allow_images
        self.prewrap_classes = set(prewrap_classes or ())
        self.hr_text = hr_text
        self.linkmap = linkmap or {}
        ## line_mode: used for poem stanzas, every break ends a line
        ## and blocks are returned as <p> (renamed <v> by the caller).
        self.line_mode = line_mode
        self.blocks = []
        self.cur = []           # inline fragments of the open paragraph
        self.stack = []         # open inline tags: (name, opentag)
        self.ptag = ['p']       # p, subtitle or text-author
        self.pending_breaks = 0
        self.in_cite = 0

    def _sub(self, **kw):
        args = dict(imgmap=self.imgmap, allow_images=self.allow_images,
                    prewrap_classes=self.prewrap_classes, hr_text=self.hr_text,
                    linkmap=self.linkmap)
        args.update(kw)
        return HtmlToFb2(**args)

    # -- paragraph management
    def _has_content(self):
        return bool(re.sub(r'<[^>]+>', '', u''.join(self.cur)).strip()) or \
            any(f.startswith(u'<image') for f in self.cur)

    def flush(self):
        if self._has_content():
            closes = u''.join(u'</%s>' % n for n, _ in reversed(self.stack))
            body = _tidy_inline(u''.join(self.cur) + closes).strip()
            tag = self.ptag[-1]
            if body:
                self.blocks.append(u'<%s>%s</%s>' % (tag, body, tag))
        self.cur = [o for _, o in self.stack]

    def _end_block(self):
        """End the open paragraph at a block element boundary.

        Three or more line breaks pending here (a blank line, such as
        the newlines before ficbook's <p>***</p> scene markers) stay
        pending, so whatever comes next, text or a block element, gets
        the same <empty-line/> before it.  Breaks still pending at the
        end of the text are dropped."""
        if self.line_mode or self.pending_breaks < 3:
            self.pending_breaks = 0
        self.flush()

    def _start_block(self):
        "Before a block element: end the open paragraph, then add the pending blank line."
        self._end_block()
        self._apply_breaks()

    def _apply_breaks(self):
        if self.pending_breaks:
            n = self.pending_breaks
            self.pending_breaks = 0
            self.flush()
            if self.line_mode:
                if n >= 2:
                    self.blocks.append(_STANZA_BREAK)
            elif n >= 3:
                self.blocks.append(u'<empty-line/>')

    def _empty_line(self):
        self._start_block()
        if self.line_mode:
            self.blocks.append(_STANZA_BREAK)
        else:
            self.blocks.append(u'<empty-line/>')

    def add_text(self, s, prewrap):
        if prewrap:
            for part in re.split(r'(\r?\n)', s):
                if part in ('\n', '\r\n'):
                    self.pending_breaks += 1
                elif part:
                    if part.strip():
                        self._apply_breaks()
                        self.cur.append(xtext(_LINE_WS_RUN.sub(u' ', part)))
                    elif not self.pending_breaks:
                        self.cur.append(u' ')
        else:
            t = _HTML_WS_RUN.sub(u' ', s)
            if t.strip():
                self._apply_breaks()
            if t:
                self.cur.append(xtext(t))

    # -- tree walk
    def is_prewrap(self, tag, inherited):
        if inherited or tag.name == 'pre':
            return True
        if _classes(tag) & self.prewrap_classes:
            return True
        style = tag.get('style') or ''
        return 'pre-wrap' in style or 'pre-line' in style

    def walk(self, node, prewrap=False):
        for child in list(node.children):
            self.handle(child, prewrap)

    def _link_target(self, tag):
        for attr in ('data-orighref', 'href'):
            href = tag.get(attr) or ''
            if href in self.linkmap:
                return self.linkmap[href]
        href = tag.get('href') or ''
        if href.startswith(('http://', 'https://', 'mailto:')):
            return href
        return None

    def handle(self, child, prewrap=False):
        if isinstance(child, (bs4.element.Comment, bs4.element.Doctype,
                              bs4.element.ProcessingInstruction,
                              bs4.element.Declaration, bs4.element.CData)):
            return
        if isinstance(child, bs4.element.NavigableString):
            self.add_text(u"%s" % child, prewrap)
            return
        name = (child.name or '').lower()
        if name in SKIP:
            return
        classes = _classes(child)
        pw = self.is_prewrap(child, prewrap)
        if classes & EMPTY_LINE_CLASSES:
            self._empty_line()
        elif name == 'br':
            self.pending_breaks += 1
        elif name == 'hr':
            self._start_block()
            if self.line_mode:
                self.blocks.append(_STANZA_BREAK)
            elif self.hr_text:
                self.blocks.append(u'<subtitle>%s</subtitle>' % xtext(self.hr_text))
            else:
                self.blocks.append(u'<empty-line/>')
        elif name == 'img':
            src = child.get('src', '')
            if self.allow_images and src in self.imgmap:
                self._apply_breaks()
                self.flush()
                alt = child.get('alt')
                self.blocks.append(u'<image l:href="#%s"%s/>' % (
                        self.imgmap[src], (u' alt=%s' % xattr(alt)) if alt else u''))
            elif child.get('alt'):
                self.add_text(u'[%s]' % child['alt'], False)
        elif name in INLINE_MAP:
            fb = INLINE_MAP[name]
            o = u'<%s>' % fb
            self.cur.append(o)
            self.stack.append((fb, o))
            self.walk(child, pw)
            self.stack.pop()
            self.cur.append(u'</%s>' % fb)
        elif name == 'a':
            href = self._link_target(child)
            if href and not any(n == 'a' for n, _ in self.stack):
                o = u'<a l:href=%s>' % xattr(href)
                self.cur.append(o)
                self.stack.append(('a', o))
                self.walk(child, pw)
                self.stack.pop()
                self.cur.append(u'</a>')
            else:
                self.walk(child, pw)
        elif classes & POEM_CLASSES and not self.line_mode:
            self._poem(child, pw)
        elif classes & EPIGRAPH_CLASSES:
            self._container(child, pw, 'epigraph')
        elif name == 'blockquote':
            self._container(child, pw, 'cite')
        elif (classes & SUBTITLE_CLASSES or name in HEADINGS) and not self.line_mode:
            self._paragraph_as(child, pw, 'subtitle')
        elif self.in_cite and (classes & TEXT_AUTHOR_CLASSES or name == 'footer') \
                and not self.line_mode:
            self._paragraph_as(child, pw, 'text-author')
        elif name == 'p' and not self.line_mode and self._is_nbsp_only(child):
            ## <p>&nbsp;</p> is a deliberate blank line.
            self._empty_line()
        elif name in ('td', 'th'):
            self.walk(child, pw)
            self.cur.append(u' ')
        elif name in BLOCKS or name in HEADINGS or \
                classes & (STANZA_CLASSES | POEM_CLASSES | SUBTITLE_CLASSES |
                           TEXT_AUTHOR_CLASSES):
            self._start_block()
            if name == 'li':
                self.cur.append(u'• ')
            self.walk(child, pw)
            self._end_block()
        else:
            # span, font, unknown: transparent
            self.walk(child, pw)

    def _is_nbsp_only(self, tag):
        text = tag.get_text()
        return u'\xa0' in text and not text.strip() and not tag.find('img')

    def _paragraph_as(self, child, pw, ptag):
        self._start_block()
        self.ptag.append(ptag)
        self.walk(child, pw)
        self._end_block()
        self.ptag.pop()

    def _container(self, child, pw, kind):
        "<cite> or <epigraph>.  Nested ones are flattened."
        self._start_block()
        if self.in_cite or self.line_mode:
            self.walk(child, pw)
            self._end_block()
            return
        start = len(self.blocks)
        self.in_cite += 1
        self.walk(child, pw)
        self._end_block()
        self.in_cite -= 1
        inner = self.blocks[start:]
        del self.blocks[start:]
        imgs = [b for b in inner if b.startswith(u'<image')]
        inner = [b for b in inner if not b.startswith(u'<image')]
        if kind == 'epigraph':
            ## epigraphType has no subtitle.
            inner = [re.sub(r'^<subtitle>(.*)</subtitle>$', r'<p>\1</p>', b, flags=re.S)
                     for b in inner]
        inner = fix_text_authors(inner)
        if any(not b.startswith(u'<empty-line') for b in inner):
            self.blocks.append(u'<%s>%s</%s>' % (kind, u''.join(inner), kind))
        self.blocks.extend(imgs)

    def _lines(self, nodes, pw):
        sub = self._sub(line_mode=True)
        for n in nodes:
            sub.handle(n, pw)
        sub._end_block()
        return sub.blocks

    def _poem(self, child, pw):
        self._start_block()
        title = []
        parts = []          # (kind, xml) kind: stanza/subtitle
        authors = []
        pending = []        # loose inline nodes, an implicit stanza
        ## images in the poem: a <v> can't hold a block image, so
        ## they go after the poem, as _container does for <cite>.
        images = []

        def lines_of(nodes):
            blocks = self._lines(nodes, pw)
            images.extend(b for b in blocks if b.startswith(u'<image'))
            return blocks

        def add_stanzas(blocks):
            stanza = []
            for b in blocks + [_STANZA_BREAK]:
                if b == _STANZA_BREAK:
                    if stanza:
                        parts.append(('stanza', u'<stanza>%s</stanza>' % u''.join(stanza)))
                    stanza = []
                elif b.startswith(u'<p>'):
                    stanza.append(u'<v>%s</v>' % b[3:-4])

        def flush_pending():
            if pending:
                add_stanzas(lines_of(pending))
                del pending[:]

        for c in list(child.children):
            if not isinstance(c, bs4.element.Tag):
                pending.append(c)
                continue
            cname = (c.name or '').lower()
            ccls = _classes(c)
            if cname in SKIP:
                continue
            if cname not in BLOCKS and cname not in HEADINGS and \
                    not ccls & (POEM_TITLE_CLASSES | TEXT_AUTHOR_CLASSES |
                                SUBTITLE_CLASSES | STANZA_CLASSES | EMPTY_LINE_CLASSES):
                pending.append(c)
                continue
            flush_pending()
            blocks = lines_of([c])
            lines = [b[3:-4] for b in blocks if b.startswith(u'<p>')]
            if not lines:
                continue
            if ccls & POEM_TITLE_CLASSES or (cname in HEADINGS and not parts):
                title.extend(u'<p>%s</p>' % l for l in lines)
            elif ccls & TEXT_AUTHOR_CLASSES or cname == 'footer':
                authors.extend(u'<text-author>%s</text-author>' % l for l in lines)
            elif ccls & SUBTITLE_CLASSES or cname in HEADINGS:
                parts.extend(('subtitle', u'<subtitle>%s</subtitle>' % l) for l in lines)
            else:
                add_stanzas(blocks)
        flush_pending()

        if not any(k == 'stanza' for k, _ in parts):
            ## nothing poem-like found, keep the text as paragraphs
            ## (with its images, so the list above isn't used).
            self.walk(child, pw)
            self._end_block()
            return
        self.blocks.append(u'<poem>%s%s%s</poem>' % (
                (u'<title>%s</title>' % u''.join(title)) if title else u'',
                u''.join(x for _, x in parts), u''.join(authors)))
        self.blocks.extend(images)

    def convert(self, htmltext):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            soup = bs4.BeautifulSoup(htmltext or u'', 'html5lib')
        root = soup.find('body') or soup
        self.walk(root)
        self._end_block()
        self.pending_breaks = 0
        return [b for b in self.blocks if b != _STANZA_BREAK]


def fix_text_authors(blocks):
    "text-author is only allowed at the end of cite/epigraph/poem."
    last_other = -1
    for i, b in enumerate(blocks):
        if not b.startswith(u'<text-author>'):
            last_other = i
    return [re.sub(r'^<text-author>(.*)</text-author>$', r'<p>\1</p>', b, flags=re.S)
            if i < last_other else b
            for i, b in enumerate(blocks)]

def _epigraph_to_cite(block):
    return u'<cite>' + block[len(u'<epigraph>'):-len(u'</epigraph>')] + u'</cite>'

def section_content(blocks):
    """Arrange blocks as sectionType wants them: epigraphs first, then
    an optional image, then at least one content element that is not
    an image.  Epigraphs after other content become cites."""
    blocks = list(blocks)
    lead = []
    while blocks and blocks[0].startswith(u'<epigraph>'):
        lead.append(blocks.pop(0))
    blocks = [_epigraph_to_cite(b) if b.startswith(u'<epigraph>') else b
              for b in blocks]
    image = []
    if blocks and blocks[0].startswith(u'<image'):
        image.append(blocks.pop(0))
    if not blocks or blocks[0].startswith(u'<image'):
        blocks.insert(0, u'<empty-line/>')
    return lead + image + blocks

def annotation_content(blocks):
    "annotationType: no images, no epigraphs."
    return [_epigraph_to_cite(b) if b.startswith(u'<epigraph>') else b
            for b in blocks if not b.startswith(u'<image')]


##########################################################################
## FB2 -> HTML

def _local(tag):
    if not isinstance(tag, str):
        return ''
    return tag.rsplit('}', 1)[-1]

def _href(el):
    for k, v in el.attrib.items():
        if _local(k) == 'href':
            return v
    return None

def _esc(s):
    return html.escape(s or u'', quote=False)

def _attr(s):
    return html.escape(s or u'', quote=True)

class _Fb2HtmlContext(object):
    def __init__(self, imgurls=None, idurls=None):
        ## binary id -> url used in <img src>
        self.imgurls = imgurls or {}
        ## section id -> chapter url, to undo internalize_text_links
        self.idurls = idurls or {}

    def img(self, el, block=False):
        href = (_href(el) or u'').lstrip(u'#')
        url = self.imgurls.get(href)
        if not url:
            return u''
        alt = el.get('alt')
        tag = u'<img src="%s" longdesc="%s"%s/>' % (
            _attr(url), _attr(url), (u' alt="%s"' % _attr(alt)) if alt else u'')
        if block:
            return u'<div class="fb2_image">%s</div>' % tag
        return tag

def _inline_html(el, ctx):
    out = [_esc(el.text)]
    for c in el:
        out.append(_inline_elem(c, ctx))
        out.append(_esc(c.tail))
    return u''.join(out)

_INLINE_HTML = {'strong': 'strong', 'emphasis': 'em', 'strikethrough': 's',
                'sub': 'sub', 'sup': 'sup', 'code': 'code', 'style': 'span'}

def _inline_elem(el, ctx):
    name = _local(el.tag)
    if name in _INLINE_HTML:
        t = _INLINE_HTML[name]
        return u'<%s>%s</%s>' % (t, _inline_html(el, ctx), t)
    if name == 'a':
        href = _href(el) or u''
        if href.startswith(u'#') and href[1:] in ctx.idurls:
            href = ctx.idurls[href[1:]]
        if href.startswith(u'#'):
            ## links into other bodies (footnotes): keep the text.
            return _inline_html(el, ctx)
        return u'<a href="%s">%s</a>' % (_attr(href), _inline_html(el, ctx))
    if name == 'image':
        return ctx.img(el)
    return _inline_html(el, ctx)

def _blocks_html(parent, ctx, skip=('title',)):
    out = []
    for c in parent:
        name = _local(c.tag)
        if name in skip:
            continue
        out.append(_block_html(c, ctx))
    return u'\n'.join(x for x in out if x)

def _block_html(el, ctx):
    name = _local(el.tag)
    if name == 'p':
        return u'<p>%s</p>' % _inline_html(el, ctx)
    if name == 'subtitle':
        return u'<h4 class="fb2_subtitle">%s</h4>' % _inline_html(el, ctx)
    if name == 'empty-line':
        return u'<div class="fb2_empty_line"></div>'
    if name == 'text-author':
        return u'<p class="fb2_text_author">%s</p>' % _inline_html(el, ctx)
    if name == 'v':
        return u'<p class="fb2_v">%s</p>' % _inline_html(el, ctx)
    if name == 'image':
        return ctx.img(el, block=True)
    if name == 'cite':
        return u'<blockquote class="fb2_cite">\n%s\n</blockquote>' % _blocks_html(el, ctx)
    if name == 'epigraph':
        return u'<blockquote class="fb2_epigraph">\n%s\n</blockquote>' % _blocks_html(el, ctx)
    if name == 'poem':
        out = []
        for c in el:
            cname = _local(c.tag)
            if cname == 'title':
                out.append(u'\n'.join(u'<p class="fb2_poem_title">%s</p>' % _inline_html(p, ctx)
                                      for p in c if _local(p.tag) == 'p'))
            elif cname == 'date':
                out.append(u'<p class="fb2_text_author">%s</p>' % _inline_html(c, ctx))
            else:
                out.append(_block_html(c, ctx))
        return u'<div class="fb2_poem">\n%s\n</div>' % u'\n'.join(x for x in out if x)
    if name == 'stanza':
        out = []
        for c in el:
            cname = _local(c.tag)
            if cname == 'title':
                out.extend(u'<p class="fb2_v">%s</p>' % _inline_html(p, ctx)
                           for p in c if _local(p.tag) == 'p')
            elif cname in ('subtitle', 'v'):
                out.append(u'<p class="fb2_v">%s</p>' % _inline_html(c, ctx))
        return u'<div class="fb2_stanza">\n%s\n</div>' % u'\n'.join(out)
    if name == 'table':
        rows = []
        for tr in el:
            cells = []
            for td in tr:
                t = 'th' if _local(td.tag) == 'th' else 'td'
                cells.append(u'<%s>%s</%s>' % (t, _inline_html(td, ctx), t))
            rows.append(u'<tr>%s</tr>' % u''.join(cells))
        return u'<table>%s</table>' % u''.join(rows)
    if name == 'section':
        ## nested sections, only in FB2 from other programs.
        out = []
        for c in el:
            if _local(c.tag) == 'title':
                out.append(u'\n'.join(u'<h3>%s</h3>' % _inline_html(p, ctx)
                                      for p in c if _local(p.tag) == 'p'))
            else:
                out.append(_block_html(c, ctx))
        return u'\n'.join(x for x in out if x)
    if name == 'annotation':
        return u'<div>\n%s\n</div>' % _blocks_html(el, ctx)
    ## unknown: keep any text
    text = _inline_html(el, ctx)
    return (u'<p>%s</p>' % text) if text.strip() else u''

## Attribute of the <body> of the chapter soups get_update_data()
## returns, so code comparing them with freshly downloaded chapters
## knows they come from an FB2 (see is_fb2_readback()).  The body tag
## isn't part of the chapter HTML written out again.
FB2_READBACK_ATTR = 'data-fff-readback'

def is_fb2_readback(soup):
    "True for a chapter soup read back from an FB2 by get_update_data()."
    return isinstance(soup, bs4.element.Tag) and soup.get(FB2_READBACK_ATTR) == 'fb2'

def comparable_text(html_or_soup, prewrap_classes=('part_text', 'text-preline'),
                    hr_text=u'* * *'):
    """The text of chapter HTML as it is in an FB2, for telling whether
    a chapter changed on the site (update_check_recent_chapters) when
    the stored copy was read back from an FB2.

    The FB2 has the chapter in paragraphs: pre-wrap line breaks split,
    <hr> as a subtitle, list items with bullets.  Its plain text joins
    them differently from the text of the site's HTML, so both sides go
    through HtmlToFb2 (prewrap_classes and hr_text as the writer's
    fb2_prewrap_classes and fb2_hr_text), which gives the read-back
    chapter its same FB2 again.  Images count by their alt text."""
    if isinstance(html_or_soup, bytes):
        html_or_soup = html_or_soup.decode('utf-8', 'replace')
    blocks = HtmlToFb2(allow_images=False, prewrap_classes=prewrap_classes,
                       hr_text=hr_text).convert(u'%s' % (html_or_soup or u''))
    text = html.unescape(re.sub(r'<[^>]+>', u'', u'\n'.join(blocks)))
    return re.sub(r'\s+', u' ', text).strip()

def fb2_section_to_html(section, imgurls=None, idurls=None):
    """HTML for the content of an FB2 <section> (without its title).

    imgurls: {binary id: url to use as img src}
    idurls: {section id: chapter url} to turn internal links back into
    chapter URLs.

    The HTML starts with replace_br_with_p's marker: it's already in
    paragraphs, and running that again would drop the empty lines.
    """
    return u'<!-- %s -->\n%s' % (REPLACE_BR_WITH_P_MARKER,
                                 _blocks_html(section, _Fb2HtmlContext(imgurls, idurls)))


##########################################################################
## Reading FB2 files

_XML_ENTITIES = ('amp', 'lt', 'gt', 'quot', 'apos')

def _fix_entities(data):
    "Replace HTML named entities, which are not defined in FB2/XML."
    def repl(m):
        if m.group(1) in _XML_ENTITIES:
            return m.group(0)
        u = html.unescape(m.group(0))
        if u == m.group(0):
            return u'&amp;' + m.group(0)[1:]
        return xtext(u)
    return re.sub(r'&([A-Za-z][A-Za-z0-9]*);', repl, data)

def _read_bytes(inputio):
    if hasattr(inputio, 'read'):
        if hasattr(inputio, 'seek'):
            inputio.seek(0)
        data = inputio.read()
    else:
        with open(inputio, 'rb') as f:
            data = f.read()
    if data[:2] == b'PK':
        ## .fb2.zip: one fb2 file in a zip.
        zf = zipfile.ZipFile(BytesIO(data))
        names = [n for n in zf.namelist() if n.lower().endswith('.fb2')]
        if not names:
            raise ValueError("No .fb2 file found in zip")
        data = zf.read(names[0])
    return data

def is_fb2_data(data):
    "True if bytes data (the start of a file is enough) look like FB2."
    head = data[:4096]
    if head[:2] == b'PK':
        try:
            zf = zipfile.ZipFile(BytesIO(data))
            names = zf.namelist()
            return 'META-INF/container.xml' not in names and \
                any(n.lower().endswith('.fb2') for n in names)
        except Exception:
            return False
    for enc in ('utf-8', 'utf-16'):
        try:
            if u'<FictionBook' in head.decode(enc, 'ignore'):
                return True
        except Exception:
            pass
    return b'<FictionBook' in head

def parse_fb2(inputio):
    """Parse an FB2 file (path, file object, .fb2 or .fb2.zip) into an
    ElementTree root element with namespaces removed from tag names."""
    data = _read_bytes(inputio)
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        ## FB2 from other programs sometimes use HTML entities.
        m = re.match(br'<\?xml[^>]*encoding=["\']([A-Za-z0-9_.-]+)["\']', data)
        enc = m.group(1).decode('ascii') if m else 'utf-8'
        text = data.decode(enc, 'replace')
        text = re.sub(r'^<\?xml[^>]*\?>', '', text)
        root = ElementTree.fromstring(_fix_entities(text).encode('utf-8'))
    for el in root.iter():
        if isinstance(el.tag, str) and '}' in el.tag:
            el.tag = _local(el.tag)
    return root

def _first_body(root):
    for body in root.findall('body'):
        if body.get('name') != 'notes':
            return body
    return None

def get_fff_data(root):
    "FanFicFare's custom-info JSON, or {}."
    for ci in root.iter('custom-info'):
        if ci.get('info-type') == FFF_DATA_INFO_TYPE:
            try:
                data = json.loads(ci.text or '{}')
                if isinstance(data, dict):
                    return data
            except ValueError as e:
                logger.warning("Failed to parse FB2 %s custom-info: %s" % (FFF_DATA_INFO_TYPE, e))
    return {}

def _src_url(root, fffdata):
    for el in root.iter('src-url'):
        if el.text and el.text.strip():
            return el.text.strip()
    return (fffdata.get('story') or {}).get('storyUrl')

def _binaries(root):
    "{id: (content-type, bytes)}"
    retval = {}
    for b in root.iter('binary'):
        bid = b.get('id')
        if not bid:
            continue
        try:
            retval[bid] = (b.get('content-type') or '',
                           base64.b64decode(re.sub(r'\s+', '', b.text or '')))
        except Exception as e:
            logger.warning("FB2 binary %s could not be decoded: %s" % (bid, e))
    return retval

def _ext_for(bid, mime):
    ext = bid.rsplit('.', 1)[-1].lower() if '.' in bid else ''
    if ext in ('jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'avif'):
        return ext
    return MIME_EXT.get((mime or '').lower(), 'jpg')

def _cover_id(root):
    for cp in root.iter('coverpage'):
        for img in cp:
            href = _href(img)
            if href:
                return href.lstrip('#')
    return None

def make_soup(data):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return bs4.BeautifulSoup(data, 'html5lib')

## The EPUB writer needs a cover page when the cover image of an FB2
## is carried over into an EPUB.
COVER_XHTML = u'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en"><head><title>Cover</title><style type="text/css" title="override_css">
@page {padding: 0pt; margin:0pt}
body { text-align: center; padding:0pt; margin: 0pt; }
div { margin: 0pt; padding: 0pt; }
</style></head><body class="fff_coverpage"><div>
<img src="%s" alt="cover"/>
</div></body></html>
'''

def get_update_data(inputio,
                    getfilecount=True,
                    getsoups=True):
    """Read an FB2 written by FanFicFare back for update.

    Returns the same tuple as epubutils.get_update_data():
    (source, filecount, soups, images, oldcover, calibrebookmark,
     logfile, urlsoups, datamaps)

    FB2 files without FanFicFare's custom-info have no reusable
    chapters: filecount is 0 and soups/urlsoups are empty.
    """
    root = parse_fb2(inputio)
    fffdata = get_fff_data(root)
    source = _src_url(root, fffdata)

    chapters = [c for c in fffdata.get('chapters') or []
                if isinstance(c, dict) and c.get('url') != FAILED_CHAPTER_URL]
    filecount = len(chapters) if getfilecount else 0
    soups = []
    images = {}
    urlsoups = {}
    datamaps = {}
    oldcover = None
    calibrebookmark = None
    logfile = fffdata.get('logfile')

    if getsoups:
        binaries = _binaries(root)
        coverid = _cover_id(root)
        imgjson = fffdata.get('images') or {}
        ## url each binary is known by: its original URL when
        ## FanFicFare recorded one.
        imgurls = {}
        for bid, (mime, data) in binaries.items():
            imgurls[bid] = imgjson.get(bid) or ('fb2binary:%s' % bid)

        if coverid and coverid in binaries:
            mime, data = binaries[coverid]
            ext = _ext_for(coverid, mime)
            oldcover = ('OEBPS/cover.xhtml',
                        'application/xhtml+xml',
                        (COVER_XHTML % ('images/cover.%s' % ext)).encode('utf-8'),
                        'OEBPS/images/cover.%s' % ext,
                        EXT_MIME[ext],
                        data)

        sections = {}
        body = _first_body(root)
        if body is not None:
            for sec in body.iter('section'):
                if sec.get('id'):
                    sections.setdefault(sec.get('id'), sec)
        idurls = dict((c.get('fb2_id'), c.get('url')) for c in chapters if c.get('fb2_id'))

        used = set()
        for chap in chapters:
            sec = sections.get(chap.get('fb2_id'))
            if sec is None:
                logger.warning("Chapter section %s not found in FB2, skipping." % chap.get('fb2_id'))
                filecount -= 1 if getfilecount else 0
                continue
            for img in sec.iter('image'):
                used.add((_href(img) or '').lstrip('#'))
            bodysoup = make_soup(u'<html><body %s="fb2">%s</body></html>' % (
                    FB2_READBACK_ATTR, fb2_section_to_html(sec, imgurls, idurls))).find('body')
            url = chap.get('url')
            if url and url not in urlsoups:
                urlsoups[url] = bodysoup
            data = dict(chap)
            data.pop('fb2_id', None)
            datamaps[url] = data
            soups.append(bodysoup)

        for bid, (mime, data) in binaries.items():
            if bid == coverid and bid not in used:
                ## the cover is carried by oldcover.
                continue
            ## only the extension of this name matters, see
            ## story.load_oldimgs()
            ext = _ext_for(bid, mime)
            name = bid if bid.lower().endswith('.' + ext) else '%s.%s' % (bid, ext)
            images[imgurls[bid]] = ('images/%s' % name, data)

        if fffdata.get('calibrebookmark'):
            try:
                calibrebookmark = base64.b64decode(fffdata['calibrebookmark'])
            except Exception:
                pass

    return (source, filecount, soups, images, oldcover, calibrebookmark,
            logfile, urlsoups, datamaps)

def get_dcsource(inputio):
    root = parse_fb2(inputio)
    return _src_url(root, get_fff_data(root))

def get_dcsource_chaptercount(inputio):
    return get_update_data(inputio, getfilecount=True, getsoups=False)[:2]

def get_story_url_from_fb2_html(inputio, _is_good_url=None):
    """First link in the FB2 accepted by _is_good_url.  For FB2 files
    from other programs (calibre's conversion of an FFF EPUB keeps the
    title page links), which have no src-url.

    calibre percent-encodes '=' in link targets ('?sid%3d3001'), so a
    link that isn't accepted as it is is tried once more unquoted, and
    returned unquoted if that one is accepted."""
    root = parse_fb2(inputio)
    for el in root.iter('a'):
        href = _href(el)
        if not href or not href.startswith('http'):
            continue
        if _is_good_url is None or _is_good_url(href):
            return href
        unquoted = unquote(href)
        if unquoted != href and _is_good_url(unquoted):
            return unquoted
    return None

def get_cover_img(inputio):
    "(content-type, data) of the cover image, or (None, None)."
    root = parse_fb2(inputio)
    coverid = _cover_id(root)
    binaries = _binaries(root)
    if coverid in binaries:
        return binaries[coverid]
    return None, None
