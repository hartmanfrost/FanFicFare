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

FanFicFare keeps what it needs for updates (chapter URLs and the
per-chapter data the EPUB writer stores in its fff_chapter_data meta
tags, original image URLs, the update log, ...) as JSON in a
<custom-info info-type="fanficfare-data"> element, which is valid
FB2.
"""

import logging
import re
import warnings

import bs4

logger = logging.getLogger(__name__)

FB2_NS = "http://www.gribuser.ru/xml/fictionbook/2.0"
XLINK_NS = "http://www.w3.org/1999/xlink"

## info-type of the <custom-info> element holding FanFicFare's own
## data.  The JSON inside carries a version number, 'v'.
FFF_DATA_INFO_TYPE = "fanficfare-data"
FFF_DATA_VERSION = 1

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
    start a new paragraph, three or more also add an <empty-line/>.
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
        self.pending_breaks = 0
        self.flush()

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
        self._end_block()
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
            self._end_block()
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
            self._end_block()
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
        self._end_block()
        self.ptag.append(ptag)
        self.walk(child, pw)
        self._end_block()
        self.ptag.pop()

    def _container(self, child, pw, kind):
        "<cite> or <epigraph>.  Nested ones are flattened."
        self._end_block()
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
        sub = self._sub(allow_images=False, line_mode=True)
        for n in nodes:
            sub.handle(n, pw)
        sub._end_block()
        return sub.blocks

    def _poem(self, child, pw):
        self._end_block()
        title = []
        parts = []          # (kind, xml) kind: stanza/subtitle
        authors = []
        pending = []        # loose inline nodes, an implicit stanza

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
                add_stanzas(self._lines(pending, pw))
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
            blocks = self._lines([c], pw)
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
            ## nothing poem-like found, keep the text as paragraphs.
            self.walk(child, pw)
            self._end_block()
            return
        self.blocks.append(u'<poem>%s%s%s</poem>' % (
                (u'<title>%s</title>' % u''.join(title)) if title else u'',
                u''.join(x for _, x in parts), u''.join(authors)))

    def convert(self, htmltext):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            soup = bs4.BeautifulSoup(htmltext or u'', 'html5lib')
        root = soup.find('body') or soup
        self.walk(root)
        self._end_block()
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
