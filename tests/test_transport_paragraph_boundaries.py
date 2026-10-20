import json
import unittest
from pathlib import Path

from fallback_report import brief_transport
from report_preparation import prepare_evidence
from report_rules import transport_link_problems
from report_sections import recover_transport_section


POSTS=prepare_evidence(json.loads((Path(__file__).parent/'fixtures/transport_full_20261020.json').read_text())['posts'])


class TransportParagraphBoundaryTests(unittest.TestCase):
    def report(self,body):
        return '1.2. '+body+'\n1.3. Немає повідомлень.'

    def test_full_real_transport_buffer_passes_without_invented_causal_link(self):
        body=brief_transport(POSTS)
        self.assertIn('Сергія Єфремова.',body)
        self.assertIn('20 жовтня',body)
        self.assertEqual(transport_link_problems(self.report(body),POSTS),[])

    def test_recovery_from_real_draft_keeps_all_active_facts(self):
        raw=self.report('19 жовтня тимчасово змінювався рух тролейбуса №6, автобусів №18 та №134. '
            '20 жовтня призупинено рух трамваїв №6 та №9 через ремонт колії на Старому мосту.')
        out=recover_transport_section(raw,POSTS)
        self.assertEqual(transport_link_problems(out,POSTS),[])
        self.assertIn('Відновлюється рух',out)
        self.assertIn('№35',out)
        self.assertIn('вул. Харківської',out)
        self.assertNotIn('Інститут фізкультури',out)

    def test_real_unsupported_cause_still_rejected(self):
        raw=self.report('Через ремонт колії на Старому мосту припинено рух трамвая №1. '+brief_transport(POSTS))
        self.assertIn('unsupported causal link between separate transport notices',
                      transport_link_problems(raw,POSTS))


if __name__=='__main__':
    unittest.main()
