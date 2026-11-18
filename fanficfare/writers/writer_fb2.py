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

"""FictionBook 2 writer.

Writes the FictionBook 2.0 namespace, valid against the FB2 2.1 XSD
(except for the 'fanfiction' genre, which readers and catalogs know
but the 2004 genre list does not; see fb2_default_genre).

FanFicFare's update data goes into <custom-info
info-type="fanficfare-data"> so the file can be updated later without
downloading old chapters again, see fb2utils.get_update_data().
"""

import base64
import datetime
import json
import logging
import os.path
import re
from html import unescape

from .base_writer import BaseStoryWriter
from ..fb2utils import (FB2_NS, XLINK_NS, FFF_DATA_INFO_TYPE, FFF_DATA_VERSION,
                        MIME_EXT, HtmlToFb2, section_content, annotation_content,
                        xtext, xattr, ncname)

logger = logging.getLogger(__name__)

## Story metadata copied into the custom-info JSON, mostly so other
## tools (and the calibre plugin) can identify the story.
STORY_DATA_ENTRIES = ('storyUrl', 'site', 'storyId', 'title', 'author',
                      'authorId', 'authorUrl', 'status', 'numChapters',
                      'numWords', 'datePublished', 'dateUpdated', 'version')


class FB2Writer(BaseStoryWriter):

    @staticmethod
    def getFormatName():
        return 'fb2'

    @staticmethod
    def getFormatExt():
        return '.fb2'

    def __init__(self, config, story):
        BaseStoryWriter.__init__(self, config, story)
        self.imgmap = {}
        self.linkmap = {}

    # ---- helpers
    def conv(self, htmltext, allow_images=True):
        "chapter/metadata HTML -> list of FB2 block element strings."
        return HtmlToFb2(self.imgmap,
                         allow_images=allow_images,
                         prewrap_classes=self.getConfigList('fb2_prewrap_classes',
                                                            ['part_text', 'text-preline']),
                         hr_text=self.getConfig('fb2_hr_text', u'* * *'),
                         linkmap=self.linkmap).convert(htmltext or u'')

    def _plain(self, val):
        return xtext(unescape(u"%s" % val).strip())

    def _person_xml(self, tag, names, urls=()):
        out = []
        for i, name in enumerate(names):
            name = unescape(u"%s" % name).strip()
            if not name:
                continue
            hp = u''
            if i < len(urls) and urls[i]:
                hp = u'<home-page>%s</home-page>' % xtext(urls[i])
            out.append(u'<%s><nickname>%s</nickname>%s</%s>' % (tag, xtext(name), hp, tag))
        return u''.join(out)

    def _authors_xml(self):
        authors = self.story.getList('author', removeallentities=True) or \
            [self.getMetadata('author')]
        retval = self._person_xml('author', authors, self.story.getList('authorUrl'))
        return retval or u'<author><nickname>Unknown</nickname></author>'

    def _genre_codes(self):
        """fb2_default_genre plus any of the story's genres (and
        categories) matched by fb2_genre_map lines: sitegenre=>fb2code"""
        mapping = {}
        for line in self.getConfig('fb2_genre_map').splitlines():
            if '=>' in line:
                k, v = line.split('=>', 1)
                k, v = k.strip().lower(), v.strip()
                if k and v:
                    mapping[k] = v
        codes = []
        default = self.getConfig('fb2_default_genre', 'fanfiction').strip()
        if default:
            codes.append(default)
        for entry in ('genre', 'category'):
            for g in self.story.getList(entry, removeallentities=True):
                for c in re.split(r'[\s,]+', mapping.get(g.strip().lower(), '')):
                    if c and c not in codes:
                        codes.append(c)
        if not codes:
            codes.append('unrecognised')
        return codes

    def _date_xml(self, d, tag='date', textfmt='%Y'):
        if not d:
            return u''
        return u'<%s value="%s">%s</%s>' % (tag, d.strftime('%Y-%m-%d'),
                                             d.strftime(textfmt), tag)

    def _sequence_xml(self):
        series = self.story.getMetadata('series', removeallentities=True)
        if not series:
            return u''
        num = u''
        m = re.match(r'^(.*) \[([0-9.]+)\]$', series)
        if m:
            series = m.group(1)
            try:
                num = u' number="%d"' % int(float(m.group(2)))
            except ValueError:
                pass
        return u'<sequence name=%s%s/>' % (xattr(unescape(series)), num)

    def _titlepage_section(self):
        entries = self.getConfigList('titlepage_entries') + \
            self.getConfigList('extra_titlepage_entries')
        blocks = []
        for entry in entries:
            show_empty = entry.endswith('.SHOW_EMPTY')
            if show_empty:
                entry = entry[:-len('.SHOW_EMPTY')]
            if not self.isValidMetaEntry(entry):
                continue
            val = self.story.getMetadata(entry)
            if not val and not show_empty:
                continue
            label = xtext(self.get_label(entry))
            vblocks = annotation_content(self.conv(val, allow_images=False))
            if len(vblocks) == 1 and vblocks[0].startswith(u'<p>'):
                blocks.append(u'<p><strong>%s:</strong> %s' % (label, vblocks[0][3:]))
            else:
                blocks.append(u'<p><strong>%s:</strong></p>' % label)
                blocks.extend(vblocks)
        if not blocks:
            return u''
        return u'<section id="fff_titlepage">%s</section>\n' % u''.join(section_content(blocks))

    def _tocpage_section(self, chapters):
        blocks = []
        for chap, sid in chapters:
            blocks.append(u'<p><a l:href="#%s">%s</a></p>' % (
                    sid, self._plain(chap['tocchapter'] or chap['chapter'])))
        if not blocks:
            return u''
        return u'<section id="fff_tocpage"><title><p>%s</p></title>%s</section>\n' % (
            xtext(self.getConfig('fb2_tocpage_title', 'Table of Contents')),
            u''.join(blocks))

    def _collect_images(self):
        """Fill self.imgmap and return (binaries, images_json, coverid)."""
        binaries = []       # (id, mime, data)
        images_json = {}    # id -> original image url
        used_ids = set()
        coverid = None

        def new_id(name, prefix='img'):
            bid = ncname(name, prefix)
            base, n = bid, 1
            while bid in used_ids:
                bid = '%s_%d' % (base, n)
                n += 1
            used_ids.add(bid)
            return bid

        ## Same rule as the EPUB writer: keep the cover of the file
        ## being updated if use_old_cover, or if there's no new cover.
        self.use_oldcover = bool(self.story.oldcover) and \
            ((self.getConfig('use_old_cover') and
              self.story.getMetadata('cover_image') != 'force') or
             not self.story.cover)
        if self.use_oldcover:
            (oldcoverhtmlhref, oldcoverhtmltype, oldcoverhtmldata,
             oldcoverimghref, oldcoverimgtype, oldcoverimgdata) = self.story.oldcover
            if oldcoverimgdata:
                ext = MIME_EXT.get(oldcoverimgtype or '', '') or \
                    os.path.splitext(oldcoverimghref or '')[1].lstrip('.') or 'jpg'
                coverid = new_id('cover.%s' % ext)
                binaries.append((coverid, oldcoverimgtype or 'image/jpeg', oldcoverimgdata))
                self.story.setMetadata('cover_image', 'old')

        if self.getConfig('include_images'):
            for imginfo in self.story.getImgUrls():
                newsrc = imginfo['newsrc']
                is_cover = bool(self.story.cover) and newsrc == self.story.cover
                if is_cover and self.use_oldcover:
                    continue
                bid = new_id(newsrc.split('/')[-1])
                self.imgmap[newsrc] = bid
                binaries.append((bid, imginfo['mime'], imginfo['data']))
                if imginfo.get('url'):
                    images_json[bid] = imginfo['url']
                if is_cover:
                    coverid = bid
        return binaries, images_json, coverid

    def _fff_data(self, chapters_json, images_json):
        story = {}
        for entry in STORY_DATA_ENTRIES:
            val = self.story.getMetadataRaw(entry)
            if isinstance(val, (datetime.date, datetime.datetime)):
                val = val.isoformat()
            if val not in (None, '', []):
                story[entry] = val
        data = {'v': FFF_DATA_VERSION,
                'story': story,
                'chapters': chapters_json,
                'images': images_json}
        if self.story.logfile:
            data['logfile'] = self.story.logfile
        if self.story.calibrebookmark:
            bm = self.story.calibrebookmark
            if not isinstance(bm, bytes):
                bm = bm.encode('utf-8')
            data['calibrebookmark'] = base64.b64encode(bm).decode('ascii')
        return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)

    # ---- main
    def writeStoryImpl(self, out):
        binaries, images_json, coverid = self._collect_images()

        chapters = [(chap, u'ch%s' % chap['index04'])
                    for chap in self.story.getChapters() if chap['html']]
        if self.getConfig('internalize_text_links'):
            self.linkmap = dict((chap['url'], u'#' + sid) for chap, sid in chapters
                                if chap['url'])

        now = datetime.datetime.now()
        dpub = self.story.getMetadataRaw('datePublished')
        langcode = self.story.getMetadata('langcode') or 'en'

        w = []
        w.append(u'<?xml version="1.0" encoding="UTF-8"?>\n')
        w.append(u'<FictionBook xmlns="%s" xmlns:l="%s">\n' % (FB2_NS, XLINK_NS))
        w.append(u'<description>\n<title-info>\n')
        w.append(u''.join(u'<genre>%s</genre>' % xtext(c) for c in self._genre_codes()))
        w.append(u'\n' + self._authors_xml() + u'\n')
        w.append(u'<book-title>%s</book-title>\n' % self._plain(self.getMetadata('title')))

        if self.story.getMetadata('description'):
            ablocks = annotation_content(self.conv(self.story.getMetadata('description'),
                                                   allow_images=False))
            if ablocks:
                w.append(u'<annotation>%s</annotation>\n' % u''.join(ablocks))

        keywords = u', '.join(self.story.getSubjectTags(removeallentities=True))
        if keywords:
            w.append(u'<keywords>%s</keywords>\n' % xtext(keywords))
        w.append(self._date_xml(dpub))
        if coverid:
            w.append(u'<coverpage><image l:href="#%s"/></coverpage>' % coverid)
        w.append(u'<lang>%s</lang>' % xtext(langcode))
        if self.getConfig('fb2_src_lang'):
            w.append(u'<src-lang>%s</src-lang>' % xtext(self.getConfig('fb2_src_lang')))
        w.append(self._person_xml('translator',
                                  self.story.getList('translator', removeallentities=True)))
        w.append(self._sequence_xml())
        w.append(u'\n</title-info>\n<document-info>\n')
        w.append(u'<author><nickname>FanFicFare</nickname>'
                 u'<home-page>https://github.com/JimmXinu/FanFicFare</home-page></author>')
        w.append(u'<program-used>FanFicFare %s</program-used>' %
                 xtext(self.getMetadata('version')))
        w.append(self._date_xml(now, textfmt='%Y-%m-%d'))
        if self.getMetadata('storyUrl'):
            w.append(u'<src-url>%s</src-url>' % xtext(self.getMetadata('storyUrl')))
        uid = u'fanficfare-uid:%s-u%s-s%s' % (
            self.getMetadata('site'),
            self.story.getList('authorId')[0] if self.story.getList('authorId') else u'',
            self.getMetadata('storyId'))
        w.append(u'<id>%s</id>' % xtext(re.sub(r'\s+', '_', uid)))
        w.append(u'<version>1.0</version>')
        w.append(u'\n</document-info>\n')
        publisher = self.getMetadata('publisher') or self.getMetadata('site')
        if publisher or dpub:
            w.append(u'<publish-info>')
            if publisher:
                w.append(u'<publisher>%s</publisher>' % self._plain(publisher))
            if dpub:
                w.append(u'<year>%s</year>' % dpub.strftime('%Y'))
            w.append(u'</publish-info>\n')

        body = []
        body.append(u'<body>\n<title><p>%s</p><p>%s</p></title>\n' % (
                self._plain(self.getMetadata('title')),
                self._plain(self.getMetadata('author'))))
        if self.getConfig('include_titlepage'):
            body.append(self._titlepage_section())
        if self.includeToCPage():
            body.append(self._tocpage_section(chapters))

        chapters_json = []
        for chap, sid in chapters:
            blocks = section_content(self.conv(chap['html']))
            body.append(u'<section id="%s"><title><p>%s</p></title>\n%s\n</section>\n' % (
                    sid, self._plain(chap['chapter']), u'\n'.join(blocks)))
            data = dict(chap)
            del data['html']
            data['fb2_id'] = sid
            chapters_json.append(data)
        if len(body) == 1:
            ## bodyType needs a section, eg with --meta-only and no titlepage.
            body.append(u'<section><empty-line/></section>\n')
        body.append(u'</body>\n')

        w.append(u'<custom-info info-type="%s">%s</custom-info>\n' % (
                FFF_DATA_INFO_TYPE, xtext(self._fff_data(chapters_json, images_json))))
        w.append(u'</description>\n')
        w.extend(body)
        for bid, mime, data in binaries:
            w.append(u'<binary id="%s" content-type=%s>%s</binary>\n' % (
                    bid, xattr(mime), base64.b64encode(data).decode('ascii')))
        w.append(u'</FictionBook>\n')
        self._write(out, u''.join(w))
