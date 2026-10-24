import unittest
from brief_budget import fit_layout


class BriefBudgetTests(unittest.TestCase):
    def test_fitting_report_is_not_rewritten(self):
        text='Дніпро: Евакуйовано 17 людей. Відключення з 08:00 до 18:00.'
        result,plan=fit_layout(text)
        self.assertEqual(result,text)
        self.assertEqual(plan['status'],'fits')

    def test_layout_compaction_preserves_dates_clocks_names_and_casualties(self):
        text=('Зведення '*477+'\nОфіційні джерела повідомили про атаки та їхні наслідки у Дніпрі. '
              'Евакуйовано 17 людей.\nПавлоград: з 08:00 24.10.2026 до 20:00 26.10.2026 '
              'для окремих будинків на вул. Центральна, вул. Шкільна, пров. Садовий.')
        result,plan=fit_layout(text)
        for fact in ['Евакуйовано 17 людей','08:00 24.10.2026','20:00 26.10.2026',
                     'Павлоград','окремих будинків','Центральна','Шкільна','Садовий']:
            self.assertIn(fact,result)
        self.assertLessEqual(plan['final_words'],plan['initial_words'])

    def test_irreducible_overflow_is_not_hidden_by_truncating_the_last_fact(self):
        text='Факт '*501+'Евакуйовано 19 людей.'
        result,plan=fit_layout(text)
        self.assertEqual(result,text)
        self.assertEqual(plan['status'],'overflow')
        self.assertIn('Евакуйовано 19 людей.',result)


if __name__=='__main__':unittest.main()
