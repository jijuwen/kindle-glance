"""Search behavior without network; real upstream samples live in smoke checks."""
import unittest
from unittest.mock import patch
from app import locations


def place(identifier, name, feature='PPLA2', population=100, **extra):
    return dict(id=identifier, name=name, feature_code=feature, population=population,
                latitude=24.48, longitude=118.08, timezone='Asia/Shanghai',
                admin1='福建省', country='中国', **extra)


class LocationSearchTest(unittest.TestCase):
    def test_short_simplified_traditional_and_full_city_names(self):
        city = place(1, '厦门市')
        for query in ('厦门', '廈門', '厦门市', '  廈門市  '):
            with self.subTest(query=query), patch.object(locations, 'fetch', side_effect=lambda q: [city] if q in ('厦门市', 'xiamen') else []):
                result = locations.search(query)
                self.assertEqual([p['id'] for p in result['results']], ['1'])
                self.assertFalse(result['partial'])

    def test_pinyin_city_rank_and_secondary_localities(self):
        rows = [place(3, 'Xiamen', 'PPL'), place(1, '厦门市', population=4000000), place(1, '厦门市')]
        with patch.object(locations, 'fetch', return_value=rows):
            result = locations.search('xiamen')
        self.assertEqual([p['id'] for p in result['results']], ['1'])
        self.assertEqual([p['id'] for p in result['more_results']], ['3'])

    def test_native_traditional_alias_finds_international_city(self):
        tokyo = place(1, '東京', 'PPLC')
        tokyo.update(admin1='東京都', country='日本', timezone='Asia/Tokyo')
        with patch.object(locations, 'fetch', side_effect=lambda q: [tokyo] if q == '東京' else [place(2, '东京城')]):
            result = locations.search('东京')
        self.assertEqual(result['results'][0]['name'], '东京')
        self.assertEqual(result['results'][0]['timezone'], 'Asia/Tokyo')
        self.assertEqual([c['name'] for c in result['more_results']], ['东京城'])

    def test_same_named_places_are_not_merged(self):
        rows = [place(1, '朝阳市'), place(2, '朝阳区', 'PPLA3'), place(3, '朝阳区', 'PPLA3')]
        with patch.object(locations, 'fetch', return_value=rows):
            result = locations.search('朝阳')
        self.assertEqual(len(result['results']), 3)

    def test_exact_city_before_more_populous_prefix_and_bad_alias_cleaned(self):
        rows = [place(1, '泉州市', population=10), place(2, '泉州新区', population=100000)]
        rows[0]['admin1'] = '福建省 or 福建省'
        with patch.object(locations, 'fetch', return_value=rows):
            result = locations.search('泉州')
        self.assertEqual(result['results'][0]['id'], '1')
        self.assertEqual(result['results'][0]['label'], '泉州市 · 福建省 · 中国')

    def test_international_qualifiers_and_no_implicit_country_filter(self):
        city = place(1, 'Berlin', 'PPLC')
        city.update(admin1='Berlin', country='Deutschland', timezone='Europe/Berlin')
        with patch.object(locations, 'fetch', return_value=[city]) as request:
            result = locations.search('Berlin, Germany')
        request.assert_called_once_with('Berlin, Germany')
        self.assertEqual(result['results'][0]['timezone'], 'Europe/Berlin')
        self.assertEqual(result['results'][0]['label'], 'Berlin · Deutschland')
        self.assertTrue(all(q.endswith(', 福建') for q in locations.variants('厦门, 福建')))

    def test_empty_and_failure_are_distinct_and_partial_is_marked(self):
        with patch.object(locations, 'fetch', return_value=[]):
            self.assertEqual(locations.search('abcdefgh'), {'results': [], 'more_results': [], 'partial': False})
        with patch.object(locations, 'fetch', side_effect=TimeoutError):
            with self.assertRaises(OSError):
                locations.search('厦门')
        def fetch(q):
            if q == '厦门市':
                return [place(1, '厦门市')]
            raise TimeoutError()
        with patch.object(locations, 'fetch', side_effect=fetch):
            self.assertTrue(locations.search('厦门')['partial'])

    def test_invalid_coordinates_and_timezone_are_not_selectable(self):
        rows = [place(1, 'Valid')]
        for i, update in enumerate(({'latitude':float('nan')}, {'longitude':200}, {'timezone':'invalid'}, {'latitude':True}), 2):
            row=place(i, 'Invalid');row.update(update);rows.append(row)
        with patch.object(locations, 'fetch', return_value=rows):
            self.assertEqual(len(locations.search('valid')['results']), 1)

    def test_fallback_requests_are_bounded_and_include_pronunciation(self):
        for query in ('厦门', '重庆', '泉州市'):
            alternatives = locations.variants(query)
            self.assertLessEqual(len(alternatives), 5)
            self.assertEqual(len(set(alternatives)), len(alternatives))
        self.assertIn('xiamen', locations.variants('厦门'))
        self.assertEqual(locations.variants('Tokyo'), [])


if __name__ == '__main__':
    unittest.main()
