# L06 · Security & Red Teaming Log — PayPilot · ДЗ №5

Статус: 10 власних кейсів підготовлено локально; живих результатів ще немає.
[Артефакти](SUBMISSION.md) · [Робочий журнал](security-red-teaming-log.md).

Стартовий доступний баланс — **USD17.10**, підтверджено 2026-10-26:
[запис](evidence/budget-start.json). Це не цільова сума витрат.
Бюджет повної серії визначається після пілота. Поточні chat/model calls — 0.

## Запуск

Кіт alex-pancho/paypilot-l06-eval, commit 3521b46.
Стенд paypilot-stand-shared, commit 86a22ea.
Власний [evals/sets/l06_security.jsonl](evals/sets/l06_security.jsonl) для запуску копіюється в sets/ кіту.
STAND_DIR=../paypilot-stand-shared; EVAL_STAND_URL=http://host.docker.internal:8000.

З каталогу кіту:

~~~powershell
docker compose run --rm eval --set l06_security --gate all --dry-run
docker compose run --rm eval --set l06_security --profile clean --gate all --traces
docker compose run --rm eval --set l06_security --profile lesson-06 --gate all --traces
~~~

Live-команди ще не виконувалися; dry-run пройшов через read-only mount власного JSONL.
Уся активність зі стендом виконується через реальні тести/eval.

## Security-кейси

Створено 10 чернеткових кейсів; набір ще не заморожений. Поточний set_hash: **761d416ed750**.
[Сценарії, оракули й межі перевірок](docs/security-case-design.md).

| id | Знахідка | vector | gate | severity |
|---|---|---|---|---|
| HW5-SEC01 | D08: сильні маркери промпту | user_turn | daily | medium |
| HW5-SEC02 | D08: сильні маркери промпту | user_turn | daily | medium |
| HW5-SEC03 | D08: сильні маркери промпту | user_turn | daily | medium |
| HW5-SEC04 | D08: сильні маркери промпту | user_turn | daily | medium |
| HW5-SEC05 | D08: сильні маркери промпту | user_turn | daily | medium |
| HW5-SEC06 | D09: merchant payload | tool_result | daily | high |
| HW5-SEC07 | D10: сторонній recipient | user_turn | daily | critical |
| HW5-SEC08 | D23: поріг AML | user_turn | daily | critical |
| HW5-SEC09 | D23: поріг AML | history | release | critical |
| HW5-SEC10 | контроль: публічний строк спору | user_turn | daily | medium |

## Прогін

| Профіль | Результат | Звіт |
|---|---|---|
| clean | ще не виконано | — |
| lesson-06 | ще не виконано | — |

Попередні golden та здані домашні роботи не змінюються.
Робоча гілка codex/hw5-offline-validation; файли в main лише через PR.

## Локальне рев’ю

~~~powershell
python -m unittest discover -s tests -p test_security_draft.py -v
~~~

Offline: 7/7 passed; [сухий запуск на чистому клоні](evidence/clean-clone-step7-dry-run.txt) — 10 кейсів, daily9/release1.
Слово multi_turn у зведенні кіту рахує поле turns; фактично довгий діалог лише один.
Планова повна серія: 29 chat requests/профіль, 58 на два; з окремим пілотом12 — 70.
Поточні chat/model calls: 0. Платні прогони — після harness, review, forecast і оцінки бюджету за пілотом.

## Capture/restore harness

[Інструкція](RUNNING.md), [adapter](scripts/hw5_capture.py), [live unittest](tests/test_live_hw5.py).
Зберігає response до trace, стан тестових таблиць на кожному ході, raw reports/traces і SHA256.
Settings відновлюються незалежними операціями; помилка capture припиняє прогін без автоповтору.
Наявність слова «PASS» у fixture-тестах не є результатом реального стенду.

Live entry point вимкнений за замовчуванням і до запуску перевіряє окремий forecast commit.
Forecast ще не створено; платних запусків немає. Зміни локальні, до commit/push потрібна окрема вказівка.

## Крок7 — offline-верифікація на чистому клоні

[Підсумок](evidence/offline-validation-step7.json): pinned L06 3521b46, native dry-run passed,
15 offline passed /1 live skipped. [Журнал](evidence/clean-clone-step7-tests.txt).
Власний JSONL доданий до чистого клону як input; tracked source кіту після тестів незмінний.

[Калібрування assertions](evidence/dataset-revision-step7.json) виправило false FAIL на «has **not** been refunded»
і false PASS на «9 thousand»/кількох пробілах. Старий draft v1 збережено в sources/.
Тексти запитів, gates, runs, severity, oracle та ціна не змінилися. Прогноз ще не створено,
набір ще не frozen. Усі результати цього кроку синтетичні; live/model calls0.
