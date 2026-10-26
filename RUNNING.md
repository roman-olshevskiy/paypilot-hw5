# HW5 — запуск і збір доказів

Статус: крок6, harness підготовлено локально. Реальних security-прогонів ще не було.
Стенд localhost:8000 і кіт paypilot-l06-eval мають лежати поруч із paypilot-hw5.
Код tracked runner/loader/assertions не змінюється; adapter обгортає native stand.chat та runner._one_run.

## Що зберігається

Кожен новий запуск створює evidence/hw5-runs/<UTC-microseconds>-<profile>/:

- before.json — health, profile/extra defects, clock, summarize, retrieval, prompt.
- attempts.json — кожна спроба chat; неповний/невідомий результат теж залишається.
- captures.json — case/run/turn, повне питання й response із session_id/request_id/usage;
  потім trace і state_after для statements_sent, disputes, escalations.
- restored.json — стан налаштувань після всіх спроб restore.
- manifest.json — повнота capture, код native runner, помилки, hashes raw reports, forecast reference.
- console.stdout.txt — native console для майбутнього live unittest.

Response записується атомарно до читання trace. Якщо trace/state/capture падає — запуск припиняється
без автоматичного повтору платного запиту. Transport timeout може означати невідомий оплачений результат;
attempt не прирівнюється до успішного response або до нульової вартості.

Стан тестових таблиць зберігається після кожного ходу, до наступного reset.
Так send_statement/sent_to не губиться при запуску наступного кейса.
Native reports і traces копіюються в reports/ без редагування байтів; колізія з іншими байтами є помилкою.
Назви trace folders перевіряються на вихід за межі reports.

## Відновлення

Спочатку повертаються original Python hooks. Далі незалежно робляться спроби відновити:
profile, extra defects, runtime clock, summarize_after, requested retrieval index/top_k.
Помилка однієї операції не пропускає решту. Фінальний запис/copy звітів виконується після restore.

За snapshot перевіряються defects/clock/summarize/retrieval; prompt записаний для provenance.
Відновлюється requested_index, а не ефективний index конкретного профілю.
Restore failure або неповний capture — помилка harness навіть за native code0/1.
Quality FAIL з повними доказами та успішним restore — нормальний результат eval, не transport failure.

Reset native runner скидає БД/сесії до seed. Довільний початковий стан БД не відновлюється.
Повних provider message bodies немає; trace/summary/tool поля не видаються за такі snapshots.
Chat/root usage може не містити summarizer/cache billing, непоказаний usage не вважається нулем.

## Безпечна offline-перевірка

~~~powershell
python -m unittest discover -s tests -p test_capture_harness.py -v
python -m unittest discover -s tests -p test_security_draft.py -v
~~~

Harness-тести запускають справжні cli/runner, але HTTP-межею є локальний fixture Backend:
вони не звертаються до сервера й не витрачають API-токени.
Згенеровані ними reports/traces існують лише в тимчасових каталогах.
Звичайне discovery пропускає test_live_hw5.py, поки явно не ввімкнено live-режим.

## Перед майбутніми live-тестами

Потрібні локальне review, frozen JSONL, окремий forecast commit і файл evidence/forecast-commit.json:

~~~json
{
  "commit": "<повний SHA коміту з прогнозом і тим самим JSONL>",
  "forecast_path": "docs/forecast-before-runs.md"
}
~~~

Цього файла й forecast commit зараз ще немає. Live unittest до Docker перевіряє:
коміт існує, містить ідентичні байти JSONL і forecast із поточним set_hash,
час коміту раніший за запуск. Adapter повторно перевіряє hash змонтованого набору.
Це захист від випадкового запуску/підміни версії, не hard cap бюджету.

Після кроків7–9, у межах погодженого кроку10:

~~~powershell
$env:HW5_ENABLE_PAID_RUNS='1'
$env:HW5_PROFILE='clean'
$env:HW5_PHASE='pilot'
python -m unittest discover -s tests -p test_live_hw5.py -v
$env:HW5_PROFILE='lesson-06'
python -m unittest discover -s tests -p test_live_hw5.py -v
~~~

Пілот: SEC07/08/09 по одному повтору,6 chat requests і3 незалежні сесії на профіль.
Після оцінки бюджету — HW5_PHASE=full:29 requests і14 незалежних сесій на профіль.
Профілі виконуються послідовно; інші лабораторні на тому самому стенді не запускати паралельно.

Live entry point застосовує read-only mount власного JSONL у sets/ кіту і mount HW5 для вихідних доказів.
Не потрібно копіювати adapter у tracked файли кіту.
Він явно очищає CASE/REPEAT/SUMMARIZE_AFTER та задає all gate, native --traces і judge not-used.
Модель і ключі налаштовані на локальному сервері; .env/API-ключі до HW5 не копіюються.
Native code0/1 допускається лише з повним capture й restore; кількість ходів/сесій/IDs і hashes звіряються.

Після завершення:

~~~powershell
Remove-Item Env:HW5_ENABLE_PAID_RUNS
Remove-Item Env:HW5_PROFILE
Remove-Item Env:HW5_PHASE
~~~
