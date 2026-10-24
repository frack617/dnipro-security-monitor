"""Explicit human-authored acceptance expectations, not production extraction.

Synthetic cases are fictional. They are deliberately separated from archived
real reports and must never be used as evidence about actual attacks.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def post(text, index, hour=12, channel='adm_dp'):
    return dict(key=f'{channel}/synthetic-{index}', channel=channel,
                published_at=f'2026-09-18T{hour:02}:00:00+00:00',
                url=f'https://example.invalid/{index}', text=text)


def case(name, texts, required=(), forbidden=(), max_occurrences=()):
    return dict(id=name, provenance='synthetic_not_a_real_event',
                checked_at='2026-09-19T05:20:00+00:00',
                posts=[post(t, f'{name}-{i}', 10+i) for i,t in enumerate(texts)],
                required=[dict(section='2.1', scope=p, fragment=f) for p,f in required],
                forbidden=[dict(section='2.1', fragment=f) for f in forbidden],
                max_occurrences=[dict(section='2.1', fragment=f, count=n) for f,n in max_occurrences],
                expect_publishable=True)


def main():
    # Discovery set: these four were run during audit before any production
    # edit. They are not described as unseen/held-out after that point.
    discovery = [
        case('evacuated_and_rescued', [
            '18 вересня ворог атакував Дніпро. Пошкоджено лікарню. Евакуйовано 17 пацієнтів. Врятовано двох дітей.'
        ], [('Дніпро','Евакуйовано 17 пацієнтів'), ('Дніпро','Врятовано двох дітей')]),
        case('bridge_closure', [
            '18 вересня ворог атакував Нікополь. Пошкоджено міст. Рух мостом закрито до 20 вересня.'
        ], [('Нікополь','Рух мостом закрито до 20 вересня')]),
        case('injury_count_and_child', [
            '18 вересня ворог атакував Павлоград. Постраждали троє людей, серед них дитина. Усі троє у важкому стані.'
        ], [('Павлоград','Постраждали троє людей, серед них дитина'), ('Павлоград','Усі троє у важкому стані')]),
        case('displaced_people', [
            '18 вересня у Дніпрі внаслідок атаки зруйновано будинок. Без житла залишилися 19 людей.'
        ], [('Дніпро','Без житла залишилися 19 людей')]),
    ]
    # Frozen before the first evaluation run. No production edits are made
    # after seeing this set in this audit. Future fixes turn it into regression
    # data and require a newly frozen validation set.
    validation = [
        case('damage_plus_destroyed_equipment', [
            '18 вересня ворог атакував Дніпро. Пошкоджено підприємство. Знищено 3 трансформатори.'
        ], [('Дніпро','Знищено 3 трансформатори')]),
        case('chemical_consequence', [
            '18 вересня ворог атакував Нікополь. Пошкоджено підприємство. Стався витік аміаку. Мешканців двох вулиць евакуювали.'
        ], [('Нікополь','Стався витік аміаку'), ('Нікополь','Мешканців двох вулиць евакуювали')]),
        case('hospital_child_status', [
            '18 вересня ворог атакував Павлоград. Пошкоджено будинок. Трьох постраждалих госпіталізовано. Стан однієї дитини тяжкий.'
        ], [('Павлоград','Трьох постраждалих госпіталізовано'), ('Павлоград','Стан однієї дитини тяжкий')]),
        case('independent_second_attack', [
            '18 вересня о 12:10 ворог атакував Дніпро. Пошкоджено школу.',
            '18 вересня о 14:20 ворог знову атакував Дніпро. Пошкоджено лікарню.'
        ], [('Дніпро','12:10'), ('Дніпро','14:20'), ('Дніпро','школу'), ('Дніпро','лікарню')]),
        case('different_places_keep_own_clinical_status', [
            '18 вересня ворог атакував Нікополь. Поранено двох людей. Один чоловік у тяжкому стані.',
            '18 вересня ворог атакував Павлоград. Поранено одну людину. Вона лікуватиметься амбулаторно.'
        ], [('Нікополь','Один чоловік у тяжкому стані'), ('Павлоград','Вона лікуватиметься амбулаторно')]),
        case('past_incident_not_relabelled_today', [
            '17 вересня ворог атакував Дніпро. Пошкоджено склад. Поранено 9 людей.'
        ], [], ['Поранено 9 людей','Пошкоджено склад']),
        case('prior_night_recap_not_new_attack', [
            'Протягом ночі ворог атакував Дніпро. Пошкоджено лікарню. Постраждали 4 людей.'
        ], [], ['Постраждали 4 людей','Пошкоджено лікарню']),
        case('an_actual_attack_inside_a_meeting_report', [
            'Під час наради 18 вересня ворог атакував Дніпро. Пошкоджено підприємство. Евакуйовано 8 працівників.'
        ], [('Дніпро','Пошкоджено підприємство'), ('Дніпро','Евакуйовано 8 працівників')]),
        case('same_fact_on_separate_day_not_summed', [
            '18 вересня ворог атакував Нікополь. Поранено 2 людей.',
            '18 вересня ворог знову атакував Павлоград. Поранено 2 людей.'
        ], [('Нікополь','Поранено 2 людей'),('Павлоград','Поранено 2 людей')], ['Поранено 4 людей']),
        case('unknown_consequence_survives_recap', [
            '18 вересня ворог атакував Дніпро. Пошкоджено будинок. Тимчасово відселено 12 мешканців.'
        ], [('Дніпро','Тимчасово відселено 12 мешканців')]),
        case('rescue_operation_outcome', [
            '18 вересня ворог атакував Дніпро. Сталася пожежа. З небезпечної зони вивели 6 людей. Одну людину шукають під завалами.'
        ], [('Дніпро','З небезпечної зони вивели 6 людей'), ('Дніпро','Одну людину шукають під завалами')]),
        case('electricity_scope_not_all_region', [
            '18 вересня ворог атакував Павлоград. Пошкоджено підстанцію. Без світла залишилися 120 будинків.'
        ], [('Павлоград','Без світла залишилися 120 будинків')], ['Вся область без світла']),
    ]
    for name, data in [('discovery',discovery),('validation',validation)]:
        content=json.dumps(data,ensure_ascii=False,indent=2)+'\n'
        (ROOT/'cases'/f'{name}.json').write_text(content,encoding='utf-8')
    inputs=[p for p in sorted((ROOT/'cases').glob('*.json')) if p.name!='SHA256SUMS.json']
    inputs+=sorted((ROOT/'archives').glob('*.json'))
    manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    (ROOT/'cases'/'SHA256SUMS.json').write_text(json.dumps(manifest,indent=2)+'\n')


if __name__=='__main__':main()
