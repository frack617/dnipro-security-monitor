"""The acceptance oracle must itself reject false positives."""
import unittest
from acceptance import oracle

REPORT='''Станом на 19.09.2026 08.00
1.1.
Огляд.
1.2. Сповіщення
Немає повідомлень.
2.1. Обстріли
Дніпро:
Пошкоджено лікарню. Евакуйовано 17 пацієнтів.

Павлоград:
Поранено одну людину.
2.2. Незаконне
Немає повідомлень.
2.3. ВНП
Немає повідомлень.
'''
SPEC={'required':[{'section':'2.1','scope':'Дніпро','fragment':'Евакуйовано 17 пацієнтів'}]}


class OracleTests(unittest.TestCase):
    def test_correct_document(self):self.assertEqual(oracle(REPORT,SPEC),[])

    def test_number_elsewhere_is_not_coverage(self):
        text=REPORT.replace('Евакуйовано 17 пацієнтів.','').replace('Поранено одну людину.','Евакуйовано 17 пацієнтів.')
        self.assertTrue(oracle(text,SPEC))

    def test_fact_in_another_section_is_not_coverage(self):
        text=REPORT.replace('Евакуйовано 17 пацієнтів.','').replace('Огляд.','Евакуйовано 17 пацієнтів.')
        self.assertTrue(oracle(text,SPEC))

    def test_changed_number_fails(self):self.assertTrue(oracle(REPORT.replace('17','18'),SPEC))

    def test_known_equivalent_spelling_is_an_explicit_oracle_choice(self):
        spec={'required':[dict(SPEC['required'][0],alternatives=['Вивезено 17 пацієнтів'])]}
        self.assertEqual(oracle(REPORT.replace('Евакуйовано','Вивезено'),spec),[])

    def test_declared_duplicate_limit(self):
        spec=dict(SPEC,max_occurrences=[dict(SPEC['required'][0],count=1)])
        self.assertTrue(oracle(REPORT.replace('Евакуйовано 17 пацієнтів.',
                                            'Евакуйовано 17 пацієнтів. Евакуйовано 17 пацієнтів.'),spec))

    def test_forbidden_unsupported_assertion(self):
        spec=dict(SPEC,forbidden=[{'section':'2.1','fragment':'Гарантовано безпечно'}])
        self.assertTrue(oracle(REPORT.replace('Поранено одну людину.','Гарантовано безпечно.'),spec))


if __name__=='__main__':unittest.main()
