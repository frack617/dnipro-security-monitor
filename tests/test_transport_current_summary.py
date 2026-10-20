import json
import unittest
from pathlib import Path

from fallback_report import brief_attacks, brief_transport
from report_rules import transport_link_problems
from report_sections import recover_transport_section
from transport_state import effective_transport_posts


F = json.loads((Path(__file__).parent/'fixtures/report_reserve_20261020.json').read_text())


class CurrentTransportSummaryTests(unittest.TestCase):
    def setUp(self):
        self.posts = [dict(p, category_hint='1.2') for p in F['posts']
                      if str(p['post_id']) in {'14997', '15002'}]
        self.current = dict(self.posts[-1], key='city/90000', reply_to=None,
                            published_at='2026-10-20T04:27:00Z', text=(
            'Через ремонт колії на Старому мосту призупинено рух трамваїв №6 та №9. '
            'Працюють автобуси №6К та №9К.'))

    def report(self, body):
        return '1.2. '+body+'\n1.3. Немає повідомлень.'

    def test_current_summary_does_not_require_ended_detour_streets(self):
        body = brief_transport(self.posts+[self.current])
        self.assertEqual(transport_link_problems(self.report(body),self.posts+[self.current]),[])
        self.assertNotIn('Інститут фізкультури',body)
        self.assertNotIn('Добровольців',body)

    def test_tram_six_is_not_restored_trolleybus_six(self):
        body = brief_transport(self.posts+[self.current])
        self.assertIn('призупинено рух трамваїв №6 та №9',body)
        self.assertNotIn('outdated transport restriction presented as current',
                         transport_link_problems(self.report(body),self.posts+[self.current]))

    def test_unrelated_active_restriction_is_still_required(self):
        problems=transport_link_problems(self.report(brief_transport(self.posts)),
                                         self.posts+[self.current])
        self.assertIn('missing source transport routes',problems)
        self.assertIn('missing source transport location or closure segment',problems)

    def test_missing_restoration_still_rejected(self):
        problems=transport_link_problems(self.report(self.current['text']),self.posts+[self.current])
        self.assertIn('missing source transport restoration',problems)

    def test_recovery_is_short_and_preserves_unrelated_boost(self):
        out=recover_transport_section(self.report('Рух змінено.'),self.posts+[self.current])
        self.assertEqual(transport_link_problems(out,self.posts+[self.current]),[])
        self.assertLess(len(out.split()),90)
        self.assertIn('№35',out)
        self.assertIn('№9К',out)
        self.assertNotIn('За попереднім повідомленням',out)

    def test_different_channel_reply_does_not_cancel_a_restriction(self):
        changed=dict(self.posts[-1],channel='another_channel')
        effective=effective_transport_posts([self.posts[0],changed])
        self.assertIn('Інститут фізкультури',effective[0]['text'])

    def test_input_sources_are_not_mutated(self):
        before=json.dumps(self.posts,sort_keys=True,ensure_ascii=False)
        effective_transport_posts(self.posts)
        self.assertEqual(json.dumps(self.posts,sort_keys=True,ensure_ascii=False),before)

    def test_different_districts_have_sentence_and_paragraph_boundary(self):
        posts=[dict(p,category_hint='2.1') for p in F['posts']
               if str(p['post_id'])=='32696']
        from report_preparation import prepare_evidence
        body=brief_attacks(prepare_evidence(posts))
        self.assertIn('інфраструктура.\n\nУ Синельниківському районі',body)


if __name__ == '__main__':
    unittest.main()
