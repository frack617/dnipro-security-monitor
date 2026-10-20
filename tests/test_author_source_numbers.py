import json
import re
import unittest
from pathlib import Path

from ai_report import (_source_text, build_prompt, build_review_prompt,
                       enforce_report_frame, linked_casualty_locations, validate_report)
from report_rules import casualty_counts, source_problems, report_section
from report_sections import recover_transport_section


FIXTURE=json.loads((Path(__file__).parent/'fixtures/author_replay_20261020.json').read_text())


class AuthorSourceNumberTests(unittest.TestCase):
    def test_each_supported_apostrophe_represents_the_same_number(self):
        for word in ("П'ятеро",'П’ятеро','Пʼятеро'):
            with self.subTest(word=word):
                self.assertEqual(casualty_counts(word+' постраждалих зараз у лікарні.'),{5})

    def test_explicit_increase_to_count_is_supported(self):
        for value,count in [('семи',7),('восьми',8),('п’яти',5),('10',10)]:
            self.assertEqual(casualty_counts('Кількість поранених зросла до '+value+'.'),{count})

    def test_age_attack_count_and_hypothetical_growth_are_not_casualty_totals(self):
        for text in ('Семирічний хлопець поранений.', '55-річний чоловік поранений.',
                     'Понад 20 атак.', 'Кількість поранених може зрости до семи.'):
            with self.subTest(text=text):self.assertEqual(casualty_counts(text),set())

    def test_unsourced_eight_is_still_rejected(self):
        post={'category_hint':'2.1','text':'У Кривому Розі кількість поранених зросла до семи.',
              'published_local':'19.10.2026 12:31 за Києвом'}
        text='1.1. В області є повідомлення про атаки.\n2.1. У Кривому Розі восьмеро людей поранені.\n2.2. Немає.'
        self.assertIn('unsupported casualty count: 8',source_problems(text,[post]))

    def test_real_source_count_is_not_rejected_as_missing(self):
        post={'category_hint':'2.1','text':'У Кривому Розі кількість поранених зросла до семи. Пʼятеро постраждалих зараз у лікарні.',
              'published_local':'19.10.2026 12:31 за Києвом'}
        text='1.1. В області є повідомлення про атаки.\n2.1. У Кривому Розі семеро людей поранені. П’ятеро постраждалих у лікарні.\n2.2. Немає.'
        self.assertFalse(any('unsupported casualty count' in p for p in source_problems(text,[post])))

    def test_all_four_real_drafts_stay_rejected_without_false_number_or_transport_errors(self):
        for raw in FIXTURE['drafts']:
            with self.subTest(draft=raw[:100]):
                report=recover_transport_section(enforce_report_frame(raw,
                    '08:00 19.10.2026','08:00 20.10.2026','09:03 20.10.2026'),FIXTURE['posts'])
                with self.assertRaises(ValueError) as caught:
                    validate_report(report,'20.10.2026',linked_casualty_locations(FIXTURE['posts']),FIXTURE['posts'])
                self.assertNotIn('unsupported casualty count: 5',str(caught.exception))
                self.assertNotIn('unsupported casualty count: 7',str(caught.exception))
                self.assertNotIn('transport',str(caught.exception))
                self.assertIn('word count',str(caught.exception))

    def test_author_and_editor_share_generic_composition_rules(self):
        for prompt in (build_prompt([],'start','end','checked',[]),
                       build_review_prompt('draft',[],'start','end')):
            self.assertIn('300–360 слів',prompt)
            self.assertIn('без нового датованого заголовка',prompt)
            self.assertIn('не обчислюй його з переліку людей',prompt)
            self.assertNotRegex(prompt,r'19 жовтня|20 жовтня')

    def test_source_block_boundaries_and_opening_total_are_explicit(self):
        post=dict(FIXTURE['posts'][0],category_hint='2.1',text='Двоє людей загинули.\n▪️\nУ Кривому Розі пошкоджено будинок.\n▪️\nНа Нікопольщині пошкоджено авто.')
        original=json.dumps(post,sort_keys=True,ensure_ascii=False)
        text=_source_text([post])
        self.assertIn('першій громаді без прямої вказівки',text)
        self.assertEqual(text.count('Окремий блок джерела:'),2)
        for part in re.split('[▪●]\\ufe0f?',post['text']):self.assertIn(part,text)
        self.assertEqual(json.dumps(post,sort_keys=True,ensure_ascii=False),original)


if __name__=='__main__':
    unittest.main()
