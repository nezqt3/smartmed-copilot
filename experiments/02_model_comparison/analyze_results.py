"""Detailed per-field and per-category analysis of saved runs; never calls a model."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LABELS = {"发热": "Температура", "咳嗽": "Кашель", "症状持续时间": "Длительность",
          "青霉素过敏": "Аллергия на пенициллин", "已用药物": "Принятый препарат",
          "已用药物剂量": "Принятая дозировка"}

def main():
    folder = Path((ROOT / "LATEST_RESULT.txt").read_text().strip())
    summary = json.loads((folder / "summary.json").read_text())
    gold = {c['id']: c for c in json.loads((folder / 'cases_test.json').read_text())}
    status_counts = Counter(item['status'] for c in gold.values() for item in c['gold'].values())
    lines = ["# Подробный разбор локальных Qwen", "",
             "Завершение всех прогонов: " + ("да" if summary['complete'] else "НЕТ — промежуточные результаты"), "",
             "40 синтетических диалогов, составленных ассистентом; эталоны не проверены врачом или носителем китайского. Это выбор модели для прототипа, не клинический бенчмарк.",
             "Результаты относятся к указанным квантованным версиям, одной фиксированной инструкции и шести полям. Оптимальная модель здесь означает лучшую среди проверенных кандидатов при этих условиях.", ""]
    lines += [f"Распределение эталонных статусов: {dict(status_counts)}.",
              f"Простой ответ unknown во всех полях дал бы {status_counts['unknown']/sum(status_counts.values()):.1%} точности статусов. Поэтому общую accuracy нужно читать вместе с Macro F1 и ошибками по каждому полю.", ""]
    analysis = {}
    for model, data in summary['models'].items():
        run = json.loads((folder / f"{model.replace(':','_')}_quality.json").read_text())
        fields = {f: Counter() for f in LABELS}
        categories = {}
        failure_cases = []
        for record in run['cases']:
            case = gold[record['id']]
            cat = categories.setdefault(case['category'], Counter())
            cat['cases'] += 1
            cat['valid_cases'] += int('error' not in record and not record.get('validation_errors'))
            answer = record.get('answer', {})
            answer = answer if isinstance(answer, dict) else {}
            for field in LABELS:
                ref = case['gold'][field]
                item = answer.get(field, {})
                item = item if isinstance(item, dict) else {}
                right = ref['status'] == item.get('status')
                fields[field]['total'] += 1
                fields[field]['correct_status'] += int(right)
                fields[field]['correct_exact_value'] += int(right and ref['value'] == item.get('value'))
                fields[field]['unsupported_positive'] += int(ref['status'] != 'present' and item.get('status') == 'present')
                fields[field]['unknown_as_negated'] += int(ref['status'] == 'unknown' and item.get('status') == 'negated')
                cat['field_count'] += 1
                cat['correct_status'] += int(right)
            if record.get('differences') or record.get('validation_errors') or record.get('error'):
                failure_cases.append({'id': record['id'], 'note_ru': case['note_ru'],
                                      'error': record.get('error'),
                                      'differences': record.get('differences', []),
                                      'validation_errors': record.get('validation_errors', [])})
        analysis[model] = {'fields': fields, 'categories': categories, 'failure_cases': failure_cases}
        lines += [f"## {model}", "", "| Поле | Верный статус | Статус + точный текст | Необоснованное наличие | Неизвестно → отрицание |",
                  "|---|---:|---:|---:|---:|"]
        for f, counts in fields.items():
            lines.append(f"| {LABELS[f]} | {counts['correct_status']}/{counts['total']} | {counts['correct_exact_value']}/{counts['total']} | {counts['unsupported_positive']} | {counts['unknown_as_negated']} |")
        lines += ["", "| Категория | Диалогов | Статусы верны | Ответы прошли проверки |", "|---|---:|---:|---:|"]
        for category, counts in categories.items():
            lines.append(f"| {category} | {counts['cases']} | {counts['correct_status']}/{counts['field_count']} | {counts['valid_cases']}/{counts['cases']} |")
        lines += ["", "### Случаи, требующие разбора", ""]
        for record in failure_cases:
            lines.append(f"- **{record['id']}** — {record['note_ru']}")
            for diff in record['differences']:
                lines.append(f"  - {LABELS[diff['field']]} / {diff['key']}: эталон `{diff['expected']}`, ответ `{diff['actual']}`.")
            for error in record['validation_errors']:
                lines.append(f"  - Проверка: `{error}`.")
            if record['error']:
                lines.append(f"  - Ошибка запуска: `{record['error']}`.")
        if 'timing' in data:
            timing = data['timing']
            timing_run = json.loads((folder / f"{model.replace(':','_')}_timing.json").read_text())
            repeated = {}
            for record in timing_run['cases']:
                case_id = record['id'].rsplit('_repeat', 1)[0]
                repeated.setdefault(case_id, []).append(record)
            stability = {'groups': len(repeated), 'status_stable_groups': 0, 'exact_answer_stable_groups': 0}
            for records in repeated.values():
                if any('error' in r for r in records):
                    continue
                vectors = [tuple((r.get('answer') or {}).get(f, {}).get('status') for f in LABELS) for r in records]
                stability['status_stable_groups'] += int(len(set(vectors)) == 1)
                answers = [json.dumps(r.get('answer'), sort_keys=True, ensure_ascii=False) for r in records]
                stability['exact_answer_stable_groups'] += int(len(set(answers)) == 1)
            analysis[model]['repeat_stability'] = stability
            lines += ["", "### Скорость", "", f"```json\n{json.dumps(timing, ensure_ascii=False, indent=2)}\n```", "",
                      "Это время локального извлечения, без ASR. Первый запрос отделён от работы загруженной модели; 14 замеров недостаточно для устойчивой оценки P95. Размер выделения Ollama не является измеренным пиком RAM.", "",
                      f"Повторы: одинаковые статусы в {stability['status_stable_groups']}/{stability['groups']} групп; полностью одинаковые ответы с цитатами — в {stability['exact_answer_stable_groups']}/{stability['groups']}. Стабильность не означает правильность."]
    (folder / 'DETAILS_RU.md').write_text('\n'.join(lines) + '\n')
    (folder / 'detailed_analysis.json').write_text(json.dumps(analysis,ensure_ascii=False,indent=2))
    print(folder / 'DETAILS_RU.md')

if __name__ == '__main__':
    main()
