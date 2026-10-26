import unittest
from fact_registry import merge_mirrors

class MirrorRegionSpellingTests(unittest.TestCase):
    def record(self, key, text):
        return dict(id=key, source_key=key, source_text=text, source_refs=[key],
                    reporting_period='2026-10-26T07:30:00+02:00',
                    scope='Дніпропетровська область', state='included', reason=None)

    def test_known_spelling_correction_is_not_conflict(self):
        original='Понад 10 разів ворог атакував Нкопольщину безпілотниками'
        a=self.record('ova', original.replace('Нкопольщину','Нікопольщину'))
        b=self.record('mirror', original)
        diagnostics=[]
        result=merge_mirrors([a,b],diagnostics)
        self.assertEqual(diagnostics,[])
        self.assertEqual(len(result),1)
        self.assertEqual(b['state'],'mirror')
        self.assertEqual(b['source_text'],original)
        self.assertEqual(set(a['source_refs']),{'ova','mirror'})

    def test_factual_difference_still_conflicts(self):
        for replacement in ['Понад 20 разів ворог атакував Нкопольщину безпілотниками',
                            'Понад 10 разів ворог атакував Криворіжжя безпілотниками']:
            a=self.record('ova','Понад 10 разів ворог атакував Нікопольщину безпілотниками')
            b=self.record('mirror',replacement)
            diagnostics=[]
            merge_mirrors([a,b],diagnostics)
            self.assertEqual(b['state'],'conflict')
            self.assertTrue(diagnostics)
