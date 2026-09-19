# HTTP API версии 0.1.0

Базовый адрес: `http://127.0.0.1:5000`. JSON кодируется в UTF-8. Для тела запроса нужен `Content-Type: application/json`. Даты выдач: `YYYY-MM-DD` по локальному времени сервера; время аудита: ISO 8601, UTC.

## Сессии и ошибки

`POST /api/auth/login` устанавливает HttpOnly cookie `library_session` и возвращает `csrf_token`. Клиент должен сохранять cookie и передавать `X-CSRF-Token` во **всех изменяющих запросах авторизованной сессии**, включая выход и повторный вход. `GET /api/auth/me` возвращает текущий токен. До входа регистрация и вход не требуют токена. Браузерные запросы с чужим Origin отклоняются. CORS не включён.

Ошибка имеет форму:

```json
{"error":{"message":"Экземпляр уже выдан.","status":409}}
```

| Код | Значение |
|---|---|
| 200 | Чтение, изменение, удаление или возврат выполнены |
| 201 | Запись или выдача созданы |
| 400 | Неверный JSON или тело не является объектом |
| 401 | Нет действующей сессии либо неверные учётные данные |
| 403 | Недостаточно прав, неверный CSRF или чужой Origin |
| 404 | Ресурс или изменяемая запись не найдены |
| 405 | HTTP-метод не поддерживается |
| 409 | Дубликат, связанная запись, повторная выдача/возврат, лимит или просрочка |
| 413 | Тело запроса больше 64 КиБ |
| 422 | Неверные поля, диапазон, тип или ссылка на отсутствующую сущность |
| 500 | Внутренняя ошибка; подробности только в журнале сервера |

Проверки сессии и CSRF могут вернуть 401/403 до ошибки маршрута. Идентификаторы в JSON — целые положительные числа, не строки и не boolean. Неизвестные поля запрещены в регистрации, справочниках и выдаче.

## Общие маршруты

| Метод и путь | Доступ | Результат |
|---|---|---|
| GET / | Все | Веб-приложение |
| GET /health | Все | `{"status":"ok","version":"0.1.0","database":"ok"}` |
| GET /api/faculties/public | Все | Список факультетов для регистрации |
| POST /api/auth/register | Все | Создание только читателя; 201, `id`, `message` |
| POST /api/auth/login | Все | `user`, `csrf_token`, cookie |
| GET /api/auth/me | Вошедший пользователь | `user`, `csrf_token` |
| POST /api/auth/logout | Вошедший пользователь | Удаление серверной сессии и cookie, `message` |

Регистрация: `{"username":"student","password":"StudentPassword2026!","full_name":"Иван Петров","faculty_id":1}`. Логин: 3–50 латинских букв, цифр, точек, дефисов и подчёркиваний; приводится к нижнему регистру. Имя: 2–120 символов. Пароль: 10–128 символов. Крайние пробелы у строк удаляются, в том числе у пароля. Вход: `{"username":"student","password":"StudentPassword2026!"}`. Поля `user`: `id`, `username`, `full_name`, `role`, `faculty_id`.

## Справочники и фонд

Для `authors`, `branches`, `faculties`, `books`, `copies` действует единая схема:

| Метод | Путь | Доступ | Ответ |
|---|---|---|---|
| GET | /api/{entity} | Любая роль | `{"items":[...]}` |
| POST | /api/{entity} | Библиотекарь | 201, `{"id":N}` |
| PUT | /api/{entity}/{id} | Библиотекарь | 200, `{"id":N}` |
| DELETE | /api/{entity}/{id} | Библиотекарь | 200, `{"id":N}` |

PUT полностью заменяет редактируемые поля: передайте все перечисленные поля, без `id`. GET отдельного объекта не предусмотрен; объект доступен в коллекции. Пагинации нет, версия предназначена для небольшого учебного фонда.

| Сущность | Все обязательные поля POST/PUT | Дополнения ответа GET |
|---|---|---|
| authors | `name` (1–120) | `id` |
| faculties | `name` (1–120) | `id` |
| branches | `name` (1–120), `address` (1–200) | `id` |
| books | `title` (1–200), `author_id`, `year` (1450–2100), `isbn` (1–120) | `id`, `author`, `total_copies`, `available_copies` |
| copies | `book_id`, `branch_id`, `inventory_number` (1–120) | `id`, `title`, `branch`, `status` |

Имена авторов, филиалов и факультетов уникальны при точном сравнении SQLite; ISBN/шифр и инвентарный номер тоже уникальны. Проверки контрольной цифры ISBN нет: допускается внутренний шифр. Статус экземпляра вычисляется: `available` или `on_loan`. DELETE связанных данных возвращает 409, каскадного удаления нет. Выданный экземпляр нельзя менять или удалять.

`GET /api/books` поддерживает `q`, `author_id`, `branch_id`, `available=true|false`. `q` — подстрока названия, автора либо ISBN/шифра без учёта регистра. Фильтры соединяются условием И. `available=false` или отсутствие параметра не ограничивает наличие. В сочетании `branch_id` и `available=true` проверяется свободный экземпляр именно в этом филиале. Счётчики `total_copies` и `available_copies` всегда относятся ко всему фонду.

Пример: `/api/books?q=мастер&branch_id=1&available=true`.

## Читатели, выдачи, отчёты

| Метод и путь | Доступ | Назначение |
|---|---|---|
| GET /api/readers | Библиотекарь | `items`: id, username, full_name, faculty_id, faculty |
| GET /api/loans | Любая роль | Библиотекарь видит все выдачи, читатель — только свои |
| POST /api/loans | Библиотекарь | `{"copy_id":1,"reader_id":2}`; 201, `{"id":N}` |
| POST /api/loans/{id}/return | Библиотекарь | Возврат; можно передать `{}`; 200, `{"id":N}` |
| GET /api/reports | Библиотекарь | Состояние фонда и агрегаты за всё время |
| GET /api/audit | Библиотекарь | Последние 100 событий, новые первыми |

Выдача проверяет роль читателя, наличие экземпляра, отсутствие его активной выдачи, лимит и отсутствие просрочки. Срок вычисляет сервер, клиент не может подменить дату. Возвращённые выдачи остаются в истории; повторный возврат — 409.

Элемент `loans.items`: `id`, `copy_id`, `reader_id`, `issued_at`, `due_at`, `returned_at` (дата или null), `title`, `inventory_number`, `reader`, `overdue` (0/1). В день срока выдача ещё не просрочена, просрочка начинается на следующий день.

Ответ `reports`: `books`, `copies`, `active_loans`, `overdue`; массив `popular` содержит до 10 записей `{id,title,loan_count}`, включая книги с нулевым числом выдач; `faculties` — `{id,name,loan_count}`. Считаются все исторические выдачи, включая возвращённые.

Элемент `audit.items`: `id`, `actor_id`, `actor`, `action` (`post`, `put`, `delete`, `issue`, `return`), `entity`, `entity_id`, `created_at`. Журнал описывает успешные изменения фонда и выдач, не является журналом всех HTTP-запросов или входов.

## Воспроизводимый пример в PowerShell

Сначала запустите сервер. Введите пароль библиотекаря из `.env` вместо заполнителя:

```powershell
$base = 'http://127.0.0.1:5000'
$login = Invoke-RestMethod "$base/api/auth/login" -Method Post -ContentType 'application/json' -Body (@{username='librarian';password='ПАРОЛЬ_ИЗ_ENV'} | ConvertTo-Json) -SessionVariable webSession
$headers = @{'X-CSRF-Token'=$login.csrf_token}
Invoke-RestMethod "$base/api/books" -WebSession $webSession
$loan = Invoke-RestMethod "$base/api/loans" -Method Post -WebSession $webSession -Headers $headers -ContentType 'application/json' -Body '{"copy_id":1,"reader_id":2}'
Invoke-RestMethod "$base/api/loans/$($loan.id)/return" -Method Post -WebSession $webSession -Headers $headers -ContentType 'application/json' -Body '{}'
Invoke-RestMethod "$base/api/auth/logout" -Method Post -WebSession $webSession -Headers $headers -ContentType 'application/json' -Body '{}'
```

Идентификаторы примера соответствуют первоначальным демонстрационным данным; перед повторным использованием проверьте свободный экземпляр через `/api/copies`.
