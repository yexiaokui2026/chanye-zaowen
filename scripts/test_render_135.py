import copy
import unittest
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import render_135 as r


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.items = {}
        for index, (category, minimum) in enumerate(r.MINIMUM_COUNTS.items()):
            self.items[category] = [dict(
                title=f'Story {index}-{n}', summary='Verified test fact.',
                source='Test source', published_at='2026-09-08',
                url=f'https://test.gov.cn/{index}/{n}', note='Test fixture')
                for n in range(minimum)]
        self.template = (Path(__file__).parent.parent / 'assets' / '135-wechat-template.html').read_text(encoding='utf-8')
        self.date = r.parse_publish_date('2026-09-09')

    def render(self, items):
        return r.render_html(self.template, {'items': items}, self.date)[0]

    def test_minimums_pass(self):
        self.assertEqual(len(r.CARD_RE.findall(self.render(self.items))), 19)

    def test_each_short_category_fails_even_if_total_is_high(self):
        for category in r.CATEGORY_ORDER:
            with self.subTest(category=category):
                items = copy.deepcopy(self.items)
                items[category].pop()
                other = next(c for c in r.CATEGORY_ORDER if c != category)
                for n in range(5):
                    extra = dict(items[other][0], title=f'Extra {n}', url=f'https://test.gov.cn/extra/{n}')
                    items[other].append(extra)
                with self.assertRaisesRegex(ValueError, 'minimum'):
                    self.render(items)

    def test_extra_items_are_not_truncated(self):
        for category in r.CATEGORY_ORDER:
            extra = dict(self.items[category][0], title=f'Extra {category}', url=f'https://test.gov.cn/extra/{category}')
            self.items[category].append(extra)
        output = self.render(self.items)
        self.assertEqual(len(r.CARD_RE.findall(output)), 24)
        for category in r.CATEGORY_ORDER:
            self.assertIn(f'Extra {category}', output)

    def test_macro_media_link_fails(self):
        self.items[r.CATEGORY_ORDER[-1]][0]['url'] = 'https://www.cls.cn/detail/test'
        with self.assertRaisesRegex(ValueError, 'official'):
            self.render(self.items)

    def test_deceptive_government_hostname_fails(self):
        self.items[r.CATEGORY_ORDER[-1]][0]['url'] = 'https://agency.gov.cn.example.com/test'
        with self.assertRaisesRegex(ValueError, 'official'):
            self.render(self.items)

    def test_reviewed_non_gov_official_requires_note(self):
        item = self.items[r.CATEGORY_ORDER[-1]][0]
        item.update(url='https://official.example.org/policy', official_source=True, note='')
        with self.assertRaisesRegex(ValueError, 'official'):
            self.render(self.items)
        item['note'] = 'Ownership verified by editor; synthetic test.'
        self.render(self.items)

    def test_duplicate_story_fails(self):
        self.items[r.CATEGORY_ORDER[0]][1] = dict(self.items[r.CATEGORY_ORDER[0]][0])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.render(self.items)

    def test_date_precision_is_preserved(self):
        table = r.render_links_table(self.items, self.date)
        self.assertIn('|2026-09-08|', table)
        self.assertNotIn('00:00', table)
        self.assertEqual(r.computed_time_check('2026-09-08', self.date), '目标新闻日')
        self.assertEqual(r.computed_time_check('2026-09-07', self.date), '超出默认窗口，需复核')

    def test_cli_emits_three_consistent_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = root / 'selected.json'
            selected.write_text(json.dumps({'publish_date': '2026-09-09', 'items': self.items}), encoding='utf-8')
            result = subprocess.run([sys.executable, '-X', 'utf8', str(Path(r.__file__)),
                                     '--input', str(selected), '--out-dir', str(root / 'out')],
                                    check=True, capture_output=True, encoding='utf-8')
            paths = json.loads(result.stdout)
            self.assertEqual(set(paths), {'html', 'code', 'links'})
            self.assertEqual(len(list((root / 'out').iterdir())), 3)
            self.assertEqual(Path(paths['html']).read_bytes(), Path(paths['code']).read_bytes())
            table = Path(paths['links']).read_text(encoding='utf-8')
            self.assertIn('来源分布自检', table)
            self.assertIn('共 19 条', table)

    def test_source_concentration_warning(self):
        for category in r.CATEGORY_ORDER[:-1]:
            for n, item in enumerate(self.items[category]):
                item['url'] = f'https://www.cls.cn/{category}/{n}'
        self.assertIn('来源集中预警', r.render_source_audit(self.items))


if __name__ == '__main__':
    unittest.main()
