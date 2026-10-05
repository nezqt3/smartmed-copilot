# SmartMed — начни здесь

Рабочая папка: `/Users/pavel/Documents/github/smartmed-copilot`.
И документы, и первый эксперимент сейчас находятся здесь.

```text
smartmed-copilot/
├── README.md                 ← описание проекта; карта папок в docs/WORKSPACE_GUIDE.md
├── docs/                     ← актуальные предложения ZH / RU / EN
├── experiments/
│   └── 01_baseline/
│       ├── START_HERE.md     ← объяснение для первого запуска
│       ├── run.py            ← программа запуска модели и проверки ответа
│       ├── cases.json        ← учебные диалоги, переводы и эталоны
│       ├── results/          ← сохранённые результаты запусков
│       ├── NOTES.md          ← разбор первоначального эксперимента
│       ├── README.md         ← технические подробности
│       └── test_checks.py    ← проверки оценочного кода
├── tools/                    ← генератор актуальных документов
├── archive/                  ← исходные документы и старые материалы
└── .qa/                      ← скрытые служебные файлы проверки документов
```

Для работы с бэкендом прочитай [BACKEND_START_HERE.md](BACKEND_START_HERE.md).
Для конкурсных документов прочитай [SUBMISSION_READINESS.md](SUBMISSION_READINESS.md).
Учебное объяснение первого запуска осталось в [эксперименте 01](../experiments/01_baseline/START_HERE.md); сравнение моделей — в `experiments/02_model_comparison`, проверки бэкенда — в `experiments/03_backend_smoke`.
Генераторы документов для работы с бэкендом запускать не нужно.
В корне репозитория также есть src/, configs/ и tests/ — существующий код проекта.

Открыть эту папку в Finder из терминала:

```sh
open /Users/pavel/Documents/github/smartmed-copilot
```

Перейти к эксперименту:

```sh
cd /Users/pavel/Documents/github/smartmed-copilot/experiments/01_baseline
```

В Finder папку экспериментов видно внутри `smartmed-copilot` рядом с `docs`.
Если открыта другая папка проекта, эти файлы в ней не появятся автоматически.

Для будущей пересборки документов актуальный генератор — `tools/rewrite_competition.py`.
Документы обновлены 5 октября 2026 года: актуальный прототип, результаты проверок и фактический состав команды. Китайский PDF сохранён рядом с DOCX.
