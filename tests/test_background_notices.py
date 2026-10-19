import json
import unittest
from pathlib import Path

import collector as c


class BackgroundNoticeTests(unittest.TestCase):
    def setUp(self):
        self.posts = {p['key']: p for p in json.loads((Path(__file__).parent /
            'fixtures/background_notice_20261019.json').read_text())}

    def test_real_exhibition_is_neither_attack_evidence_nor_alert(self):
        p = self.posts['DniproCityOfficial/14983']
        self.assertIsNone(c.classify_post(p))
        self.assertFalse(c.is_resonant(p))

    def test_real_attack_and_assistance_notice_remains_selected(self):
        for key in ('DniproCityOfficial/14967', 'dnipropetrovskaODA/32691'):
            with self.subTest(key=key):
                self.assertEqual(c.classify_post(self.posts[key]), '2.1')
                self.assertTrue(c.is_resonant(self.posts[key]))

    def test_generic_opening_forms_not_tied_to_title_or_date(self):
        for opening in ('відкрили фотовиставку', 'відкрито виставку',
                        'відкрилася експозиція', 'відкриється фотовиставка'):
            with self.subTest(opening=opening):
                p = {'channel': 'adm_dp', 'text': 'У Нікополі ' + opening +
                     ' про допомогу громадам. Світлини показують евакуацію та підтримку після обстрілів.'}
                self.assertIsNone(c.classify_post(p))
                self.assertFalse(c.is_resonant(p))

    def test_attack_at_exhibition_is_not_suppressed(self):
        for text in (
            'У Дніпрі росіяни атакували будинок, де відкрили фотовиставку.',
            'У Дніпрі відкрили фотовиставку. Росіяни завдали удару по будівлі.',
            'У Дніпрі відкрили фотовиставку. Унаслідок обстрілу пошкоджено будівлю.',
            'У Дніпрі відкрито виставку. Є поранені через обстріл.',
        ):
            with self.subTest(text=text):
                p = {'channel': 'adm_dp', 'text': text}
                self.assertEqual(c.classify_post(p), '2.1')
                self.assertTrue(c.is_resonant(p))

    def test_exhibition_word_alone_never_suppresses_attack(self):
        p = {'channel': 'adm_dp', 'text': 'Ворог атакував Дніпро. Пошкоджено виставкову залу.'}
        self.assertEqual(c.classify_post(p), '2.1')
        self.assertTrue(c.is_resonant(p))


if __name__ == '__main__':
    unittest.main()
