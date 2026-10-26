# L06 · Security & Red Teaming Log — PayPilot · ДЗ №5

Статус: підготовка репозиторію; кейси та живі результати ще не створено.
[Артефакти](SUBMISSION.md) · [Робочий журнал](security-red-teaming-log.md).

Стартовий доступний баланс — **USD17.10**, підтверджено 2026-10-26:
[запис](evidence/budget-start.json). Це не цільова сума витрат.
Бюджет повної серії визначається після пілота. Поточні chat/model calls — 0.

## Запуск

Кіт alex-pancho/paypilot-l06-eval, commit 3521b46.
Стенд paypilot-stand-shared, commit 86a22ea.
Після створення власного evals/sets/l06_security.jsonl скопіювати його в sets/ кіту.
STAND_DIR=../paypilot-stand-shared; EVAL_STAND_URL=http://host.docker.internal:8000.

З каталогу кіту:

~~~powershell
docker compose run --rm eval --set l06_security --gate all --dry-run
docker compose run --rm eval --set l06_security --profile clean --gate all --traces
docker compose run --rm eval --set l06_security --profile lesson-06 --gate all --traces
~~~

Це команди майбутніх запусків. Набір ще відсутній, тому вони поки не є готовою інструкцією здачі.
Уся активність зі стендом виконується через реальні тести/eval.

## Security-кейси

Заплановано 10 власних кейсів; обов’язковий мінімум — 6.
Матриця ще не заморожена; set_hash з’явиться після створення JSONL.

| id | Знахідка | vector | gate | severity |
|---|---|---|---|---|
| — | кейси ще не створено | — | — | — |

## Прогін

| Профіль | Результат | Звіт |
|---|---|---|
| clean | ще не виконано | — |
| lesson-06 | ще не виконано | — |

Попередні golden та здані домашні роботи не змінюються.
Робоча гілка codex/hw5-security; файли в main лише через PR.
