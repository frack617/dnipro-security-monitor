import json
import unittest
from pathlib import Path

import collector as c


F=json.loads((Path(__file__).parent/'fixtures/morning_20261019.json').read_text())


class AdjacentReportWindowTests(unittest.TestCase):
    def setUp(self):
        self.post=next(p for p in F['posts'] if p['key']=='dnipropetrovskaODA/32672')
        self.today=c.parse_datetime('2026-10-19T08:20:00+03:00')
        self.tomorrow=c.parse_datetime('2026-10-20T08:20:00+03:00')

    def test_real_late_cutoff_bulletin_belongs_to_only_one_window(self):
        self.assertEqual(c.report_window_posts([self.post],self.today),[self.post])
        self.assertEqual(c.report_window_posts([self.post],self.tomorrow),[])

    def test_mirror_and_exact_boundary_are_also_not_reused(self):
        for channel in ('adm_dp','dnipropetrovskaODA'):
            for timestamp in ('2026-10-19T05:00:00Z','2026-10-19T05:00:32Z','2026-10-19T05:15:00Z'):
                with self.subTest(channel=channel,timestamp=timestamp):
                    p=dict(self.post,channel=channel,published_at=timestamp)
                    self.assertTrue(c.report_window_posts([p],self.today))
                    self.assertFalse(c.report_window_posts([p],self.tomorrow))

    def test_explicit_new_attack_after_eight_stays_in_next_window(self):
        p=dict(self.post,published_at='2026-10-19T05:01:00Z',
               text=self.post['text']+' Після 08:00 щойно росіяни атакували Дніпро.')
        self.assertFalse(c.report_window_posts([p],self.today))
        self.assertTrue(c.report_window_posts([p],self.tomorrow))

    def test_ordinary_post_at_exact_start_is_not_removed(self):
        p=dict(self.post,published_at='2026-10-19T05:00:00Z',
               text='Росіяни завдали нового удару по Дніпру. Інформацію уточнюємо.')
        self.assertFalse(c.report_window_posts([p],self.today))
        self.assertTrue(c.report_window_posts([p],self.tomorrow))

    def test_next_days_cutoff_bulletin_is_still_accepted(self):
        p=dict(self.post,published_at='2026-10-20T05:00:17Z',
               text=self.post['text'].replace('19 жовтня','20 жовтня'))
        self.assertTrue(c.report_window_posts([p],self.tomorrow))

    def test_window_uses_kyiv_offset_across_dst_change(self):
        p=dict(self.post,published_at='2026-10-25T06:00:17Z',
               text=self.post['text'].replace('19 жовтня','25 жовтня'))
        at=c.parse_datetime('2026-10-25T08:20:00+02:00')
        next_at=c.parse_datetime('2026-10-26T08:20:00+02:00')
        self.assertTrue(c.report_window_posts([p],at))
        self.assertFalse(c.report_window_posts([p],next_at))


if __name__=='__main__':
    unittest.main()
