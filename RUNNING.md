# HW5 — запуск і збір доказів

Статус: пілот і дві повні серії завершено. Новий live-запуск створить нові витрати й докази.
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
- console.stdout.txt — native console для кожного live unittest.

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

Forecast commit518f675 уже підтверджено, evidence/forecast-commit.json створено реальним тестом.
Live unittest до Docker перевіряє:
коміт існує, містить ідентичні байти JSONL і forecast із поточним set_hash,
час коміту раніший за запуск. Adapter повторно перевіряє hash змонтованого набору.
Це захист від випадкового запуску/підміни версії, не hard cap бюджету.

Для нового погодженого пілота:

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

## Повторення offline-верифікації

~~~powershell
python scripts/verify_offline_step7.py
~~~

Скрипт створює тимчасовий локальний клон кіту на зафіксованому commit, додає власний JSONL,
виконує Docker dry-run і offline-тести саме з loader/runner цього клону.
Live-режим примусово вимкнений; HTTP у інтеграційних тестах підмінено fixture Backend.
Тимчасовий Docker project і clone прибираються; код початкового кіту не змінюється.
Потрібні Docker, Git, Python і сусідні source-репозиторії для звірки hashes.

## Реальний preflight без моделі

~~~powershell
$env:HW5_RUN_PREFLIGHT='1'
python -m unittest discover -s tests -p test_preflight_hw5.py -v
Remove-Item Env:HW5_RUN_PREFLIGHT
~~~

Виконує GET, читання source hashes і конфігурації з контейнера, а також оборотний settings round-trip.
Не викликає chat, complete, reset або інструменти клієнтських дій.
Початкові settings повертаються в finally, action tables звіряються до/після.
На unlocked локальному сервері admin=true не є умовою дозволу server write; за locked без admin тест не змінює settings.

Звичайне offline discovery пропускає4 preflight-тести й1 paid live-тест.
Скрипт verify_offline_step7.py примусово вимикає обидва режими під час перевірки чистого клону.


## Результати повторних offline-перевірок

Кожен запуск verify_offline_step7.py створює унікальний каталог evidence/offline-runs/
із dry-run.txt, tests.txt і validation.json. Історичні докази кроку7 залишаються незмінними.
Типово потрібні лише HW5, L06-кіт і shared-стенд; попередні HW2–HW4 не читаються.

Окремий аудит попередніх датасетів:

~~~powershell
python scripts/verify_offline_step7.py --check-prior-datasets
~~~

Цей режим використовує історичні абсолютні шляхи з preparation-manifest.json
і потребує тих репозиторіїв за вказаними шляхами.

## Повторний аналіз збережених серій

~~~powershell
python scripts/analyze_full_runs.py --selection evidence/analysis-selection.json
~~~

Маніфест явно визначає full_runs для порівняння та ledger_runs для обліку вартості,
включно з пілотом і перерваною спробою. Нові каталоги прогонів автоматично не підбираються.
Для іншого порівняння створити окремий manifest; всі full_runs мають входити в ledger_runs.
Аналіз перевіряє завершеність full, hash набору й raw report, verdict replay та унікальність IDs.
Вихід: новий evidence/analysis-runs/<UTC-ID>/analysis.json; історичний full-run-analysis.json не змінюється.
Це offline replay збережених відповідей, без звернень до стенду.
