"""Offline tests for adapter_ficbooknet against saved ficbook.net story pages.

The fixtures in tests/fixtures_ficbooknet/ are trimmed copies (just the
section.chapter-info story hat and parts list) of real pages fetched
2026-11-18, both old numeric story ids and new UUID style ids:

  3405280      numeric, completed, Harry Potter books and films: two
               /fanfiction/ fandoms that ficbook labels "(кроссовер)",
               but one canon
  9139455      numeric, completed, has a cover
  11757889     numeric, frozen, direction Смешанная
  019ef3f4-... UUID, in progress, "Вселенная:" only (no "Фэндом:")
  019afb02-... UUID, completed, "Вселенная:" only
  0191af22-... UUID, "Вселенная:" and "Фэндом:" both present
  018a176a-... UUID, series and nine fandoms
  01a1e596-... UUID, frozen one-shot (no parts list), direction Джен

and, only for the crossover tests:

  10504608     numeric, Naruto and the Harry Potter books, no
               "Кроссовер" tag of the author's
  019c00bf-... UUID, "Вселенная:" Голодные игры and "Фэндом:" Boku no
               Hero Academia, the author tagged it "Кроссовер"
"""
import os
from unittest.mock import patch

import pytest

import fanficfare
from fanficfare.adapters.adapter_ficbooknet import FicBookNetAdapter, fandom_canon
from fanficfare.configurable import Configuration

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'fixtures_ficbooknet')
DEFAULTS_INI = os.path.join(os.path.dirname(fanficfare.__file__), 'defaults.ini')

HP_UNIVERSE = 'Гарри Поттер (Harry Potter)'
ROULING = 'Роулинг Джоан «Гарри Поттер»'

COF = '019ef3f4-465e-7a54-bae1-7692233cac44'
BACK = '019afb02-093f-747e-b5ed-175c13970b6b'
ROSES = '0191af22-76e7-7bed-9982-62c0d971f1c5'
JOURNEY = '018a176a-d430-7019-bc67-ccfe6a09d40e'
ONESHOT = '01a1e596-0c02-7eb2-9bf1-6f8925d6ceba'
NARUTO = '10504608'
TAGGED = '019c00bf-9493-72f9-87ab-0e579157673f'

EXPECTED = {
    '3405280': dict(
        title='Жребий брошен', author=['kat.shelfner'],
        category=[ROULING, 'Гарри Поттер'], universe=None,
        classification='Гет', rating='R', status='Completed',
        likes=414, reviews=173, numCollections=219, follows=1074, numAwards=2,
        numWords=167072, pages=477, numChapters=50,
        datePublished='2015-07-17 18:17', dateUpdated='2020-11-20 16:22',
        cover=None),
    '9139455': dict(
        title='Да не Гарри я!', author=['Babach'],
        category=[ROULING], universe=None,
        classification='Гет', rating='PG-13', status='Completed',
        likes=3226, reviews=569, numCollections=1544, follows=3538, numAwards=3,
        numWords=243650, pages=543, numChapters=62,
        datePublished='2020-03-11 08:05', dateUpdated='2022-01-13 09:30',
        cover='https://assets.teinon.net/fanfic-covers/1C1Ps9ScEf1MLpPPXanvD6rpoOnhwIVc.jpg'),
    '11757889': dict(
        title='Стертые знаки', author=['EmerGency.'],
        category=['Нора Сакавич «Всё ради игры»'], universe=None,
        classification='Смешанная', rating='NC-17', status='Frozen',
        likes=2, reviews=None, numCollections=None, follows=2, numAwards=None,
        numWords=1176, pages=4, numChapters=2,
        datePublished='2022-02-11 17:33', dateUpdated='2022-02-11 20:15',
        cover=None),
    COF: dict(
        title='Convergence of Fates — Переплетение судеб', author=['KiLev'],
        category=[HP_UNIVERSE], universe=HP_UNIVERSE,
        classification='Гет', rating='NC-17', status='In-Progress',
        likes=214, reviews=329, numCollections=106, follows=259, numAwards=2,
        numWords=447641, pages=1185, numChapters=73,
        datePublished='2026-06-24 10:00', dateUpdated='2026-10-21 07:33',
        cover=None),
    BACK: dict(
        title='Back? Not Really - Вернулся? Не совсем.', author=['KiLev'],
        category=[HP_UNIVERSE], universe=HP_UNIVERSE,
        classification='Гет', rating='NC-17', status='Completed',
        likes=511, reviews=191, numCollections=198, follows=342, numAwards=2,
        numWords=165527, pages=469, numChapters=59,
        datePublished='2025-12-09 00:23', dateUpdated='2026-01-28 09:00',
        cover=None),
    ROSES: dict(
        title='Когда розы снова зацветут', author=['amallie'],
        category=[ROULING], universe=HP_UNIVERSE,
        classification='Гет', rating='NC-17', status='Completed',
        likes=387, reviews=426, numCollections=175, follows=333, numAwards=5,
        numWords=644832, pages=1420, numChapters=109,
        datePublished='2024-09-01 23:00', dateUpdated='2026-06-06 14:02',
        cover=None),
    JOURNEY: dict(
        title='Гарри Поттер и путешествие между мирами. 1 Том.', author=['Goverson'],
        category=[ROULING, 'Властелин Колец', 'Boku no Hero Academia',
                  'Fate/Grand Order', 'Honkai Impact 3rd', 'Azur Lane',
                  'Arknights', 'Genshin Impact',
                  'Kage no Jitsuryokusha ni Naritakute!'], universe=None,
        classification='Гет', rating='NC-17', status='Completed',
        likes=1229, reviews=743, numCollections=390, follows=1242, numAwards=1,
        numWords=184693, pages=355, numChapters=37,
        datePublished='2023-09-11 17:11', dateUpdated='2025-03-26 10:28',
        cover=None),
    ONESHOT: dict(
        title='Генералы дарят бриллианты...', author=['ULIK'],
        category=[HP_UNIVERSE], universe=HP_UNIVERSE,
        classification='Джен', rating='PG-13', status='Frozen',
        likes=3, reviews=None, numCollections=None, follows=None, numAwards=None,
        numWords=363, pages=1, numChapters=1,
        datePublished='2026-11-16 21:21', dateUpdated='2026-11-16 21:21',
        cover=None),
}

DATE_FORMAT = '%Y-%m-%d %H:%M'


def read_fixture(story_id):
    with open(os.path.join(FIXTURE_DIR, story_id + '.html'), encoding='utf-8') as f:
        return f.read()


def new_adapter(story_id):
    ## defaults.ini has the ficbook.net extra_valid_entries (likes,
    ## classification, etc), without it those metadata read as None.
    configuration = Configuration(['ficbook.net'], 'EPUB')
    with open(DEFAULTS_INI, encoding='utf-8') as f:
        configuration.read_file(f)
    return FicBookNetAdapter(configuration, 'https://ficbook.net/readfic/' + story_id)


def make_adapter(story_id, html=None):
    adapter = new_adapter(story_id)
    if html is None:
        html = read_fixture(story_id)
    with patch.object(FicBookNetAdapter, 'get_request', return_value=html), \
         patch.object(FicBookNetAdapter, 'setDescription'), \
         patch.object(FicBookNetAdapter, 'setCoverImage') as set_cover:
        adapter.extractChapterUrlsAndMetadata()
    adapter.set_cover = set_cover
    return adapter


@pytest.fixture(scope='module')
def adapters():
    return {story_id: make_adapter(story_id) for story_id in EXPECTED}


@pytest.mark.parametrize('story_id', list(EXPECTED))
def test_metadata(adapters, story_id):
    story = adapters[story_id].story
    expected = EXPECTED[story_id]
    for key in ('title', 'author', 'category', 'universe', 'classification',
                'rating', 'status', 'likes', 'reviews', 'numCollections',
                'follows', 'numAwards', 'numWords', 'pages', 'numChapters'):
        assert story.getMetadataRaw(key) == expected[key], key
    for key in ('datePublished', 'dateUpdated'):
        assert story.getMetadataRaw(key).strftime(DATE_FORMAT) == expected[key], key
    assert story.getMetadataRaw('language') == 'Russian'
    assert story.getMetadataRaw('storyId') == story_id


@pytest.mark.parametrize('story_id', list(EXPECTED))
def test_counts_are_integers(adapters, story_id):
    story = adapters[story_id].story
    for key in ('likes', 'reviews', 'numCollections', 'follows', 'numAwards',
                'numWords', 'pages'):
        value = story.getMetadataRaw(key)
        assert value is None or (isinstance(value, int) and value > 0), key
    assert isinstance(story.getMetadataRaw('likes'), int)


@pytest.mark.parametrize('story_id', list(EXPECTED))
def test_direction_is_plain_text(adapters, story_id):
    direction = adapters[story_id].story.getMetadata('classification')
    assert direction == EXPECTED[story_id]['classification']
    assert '<' not in direction and '\n' not in direction


@pytest.mark.parametrize('story_id', list(EXPECTED))
def test_fandom_found(adapters, story_id):
    category = adapters[story_id].story.getMetadataRaw('category')
    assert category == EXPECTED[story_id]['category']
    assert category, 'no fandom found'


def test_works_with_only_a_universe_get_it_as_fandom(adapters):
    for story_id in (COF, BACK, ONESHOT):
        story = adapters[story_id].story
        assert story.getMetadataRaw('category') == [HP_UNIVERSE]
        assert story.getMetadata('universe') == HP_UNIVERSE
        assert 'Кроссовер' not in story.getMetadataRaw('genre')


def test_fandom_wins_over_universe_when_both_listed(adapters):
    story = adapters[ROSES].story
    assert story.getMetadataRaw('category') == [ROULING]
    assert story.getMetadata('universe') == HP_UNIVERSE


def test_crossover_genre(adapters):
    assert 'Кроссовер' in adapters[JOURNEY].story.getMetadataRaw('genre')
    assert 'Кроссовер' not in adapters['9139455'].story.getMetadataRaw('genre')


def test_books_and_films_of_one_canon_are_not_a_crossover(adapters):
    story = adapters['3405280'].story
    assert story.getMetadataRaw('category') == [ROULING, 'Гарри Поттер']
    assert 'Кроссовер' not in story.getMetadataRaw('genre')


def test_two_canons_are_a_crossover_without_the_authors_tag():
    story = make_adapter(NARUTO).story
    assert story.getMetadataRaw('category') == ['Naruto', ROULING]
    assert story.getMetadataRaw('genre').count('Кроссовер') == 1


def test_the_authors_crossover_tag_is_kept():
    story = make_adapter(TAGGED).story
    assert story.getMetadataRaw('category') == ['Boku no Hero Academia']
    assert story.getMetadataRaw('genre').count('Кроссовер') == 1


@pytest.mark.parametrize('one,other', [
    (ROULING, 'Гарри Поттер'),
    ('Толкин Джон Р. Р. «Властелин колец»', 'Властелин Колец'),
    ('Сапковский Анджей «Ведьмак» (Сага о ведьмаке)', 'Ведьмак'),
    ('Чёрный клевер', 'Черный  клевер'),
])
def test_fandom_canon_same(one, other):
    assert fandom_canon(one) == fandom_canon(other)


@pytest.mark.parametrize('one,other', [
    ('Сапковский Анджей «Ведьмак» (Сага о ведьмаке)', 'The Witcher'),
    ('Лавкрафт Говард «Ужас Данвича»', 'Лавкрафт Говард Филлипс «Мифы Ктулху»'),
    (ROULING, 'Naruto'),
])
def test_fandom_canon_different(one, other):
    assert fandom_canon(one) != fandom_canon(other)


@pytest.mark.parametrize('story_id,status', [
    ('3405280', 'Completed'),
    (COF, 'In-Progress'),
    ('11757889', 'Frozen'),
    (ONESHOT, 'Frozen'),
])
def test_status(adapters, story_id, status):
    assert adapters[story_id].story.getMetadata('status') == status


def test_genres_ships_characters(adapters):
    story = adapters[COF].story
    assert len(story.getMetadataRaw('genre')) == 12
    assert story.getMetadataRaw('genre')[:3] == ['AU', 'Второй шанс', 'Насилие']
    assert 'Сильный Гарри' in story.getMetadataRaw('genre')
    assert story.getMetadataRaw('ships') == ['Гарри Поттер/ОЖП']
    assert story.getMetadataRaw('characters') == [
        'Гарри Поттер', 'ОЖП', 'Альбус Дамблдор', 'Амелия Боунс',
        'Сириус Блэк', 'Сириус Блэк III', 'Римус Люпин', 'Драко Малфой']

    story = adapters[ONESHOT].story
    assert story.getMetadataRaw('genre') == ['Songfic']
    assert story.getMetadataRaw('ships') == ['Том Марволо Реддл/Гарри Поттер']


def test_series(adapters):
    story = adapters[JOURNEY].story
    assert story.getMetadata('series') == 'Гарри Поттер и путешествие между мирами [1]'
    assert story.getMetadata('seriesUrl').startswith('https://ficbook.net/')
    assert not adapters[COF].story.getMetadata('series')


@pytest.mark.parametrize('story_id', ['3405280', COF, ONESHOT])
def test_chapters(adapters, story_id):
    chapters = adapters[story_id].get_chapters()
    assert len(chapters) == EXPECTED[story_id]['numChapters']
    base = 'https://ficbook.net/readfic/' + story_id
    if story_id == ONESHOT:
        assert chapters[0]['url'] == base
    else:
        assert all(c['url'].startswith(base + '/') and c['url'].endswith('#part_content')
                   for c in chapters)


def test_chapter_dates(adapters):
    chapters = adapters[COF].get_chapters()
    assert chapters[0]['title'] == 'Глава 1: Пролог'
    assert chapters[0]['url'] == 'https://ficbook.net/readfic/' + COF + '/42225253#part_content'
    assert chapters[0]['date'] == '2026-06-24 10:00'
    assert chapters[-1]['title'] == 'Глава 73: На благо магического мира'


@pytest.mark.parametrize('story_id', list(EXPECTED))
def test_cover(adapters, story_id):
    set_cover = adapters[story_id].set_cover
    cover = EXPECTED[story_id]['cover']
    if cover:
        set_cover.assert_called_once_with('https://ficbook.net/readfic/' + story_id, cover)
    else:
        set_cover.assert_not_called()


def test_direction_falls_back_to_the_title_without_label_text():
    html = read_fixture(COF).replace('<span class="hidden-xs">Гет</span>', '')
    assert 'hidden-xs">Гет' not in html
    adapter = make_adapter(COF, html)
    assert adapter.story.getMetadata('classification') == 'Гет'


@pytest.mark.parametrize('value,expected', [
    ('214', 214),
    (' 1 234 ', 1234),
    ('0', None),
    ('', None),
    (None, None),
])
def test_set_count(value, expected):
    adapter = new_adapter(COF)
    adapter.setCount('likes', value)
    assert adapter.story.getMetadataRaw('likes') == expected
