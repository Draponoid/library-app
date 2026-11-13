# Лабораторная работа №4: две Ubuntu VM

VM1: Nginx и два экземпляра приложения. VM2: PostgreSQL. Замените VM1_IP и VM2_IP на частные IP-адреса. Нужны связь между VM, интернет, sudo и не менее 2 ГБ RAM на каждой VM. HTTP подходит только для учебной сети.

## 1. Обе VM: подготовка

На каждой VM установите Docker Engine и Compose plugin по [инструкции Docker](https://docs.docker.com/engine/install/ubuntu/). Затем:

```sh
sudo apt-get update
sudo apt-get install -y git make python3 openssl
sudo usermod -aG docker "$USER"
```

Завершите SSH-сеанс и подключитесь заново. Проверьте `docker version` и `docker compose version`. На каждой VM:

```sh
git clone https://github.com/Draponoid/library-app.git
cd library-app
git switch lab4-containerization
```

После слияния PR используйте master вместо этой ветки.

## 2. Сессия VM2: база

В команде замените VM2_IP на адрес VM2. Сохраните выведенный пароль: он потребуется на VM1.

```sh
umask 077
DB_PASS=$(openssl rand -hex 24)
printf 'DB_BIND_IP=VM2_IP\nPOSTGRES_PASSWORD=%s\n' "$DB_PASS" > .env
cat .env
unset DB_PASS
make db-up
docker compose -f compose.db.yml ps
```

Дождитесь healthy. Откройте TCP 5432 только для VM1_IP в firewall облака/гипервизора. Docker может обходить правила UFW при публикации портов, поэтому дополнительно проверьте ограничение с другой машины. Не открывайте 5432 всему интернету.

## 3. Сессия VM1: приложение

Подставьте частный IP VM2 и тот же пароль. Пароли демонстрационных пользователей создаются случайно.

```sh
umask 077
read -rs -p 'Пароль PostgreSQL: ' DB_PASS; echo
printf 'DATABASE_URL=postgresql://library:%s@VM2_IP:5432/library\nSECRET_KEY=%s\nDEMO_LIBRARIAN_PASSWORD=%s\nDEMO_READER_PASSWORD=%s\nHTTP_PORT=8080\n' "$DB_PASS" "$(openssl rand -hex 32)" "$(openssl rand -hex 12)" "$(openssl rand -hex 12)" > .env
unset DB_PASS
make migrate
make seed
make up
docker compose ps
curl -fsS http://localhost:8080/health
```

На новой базе `migrate` применяет начальную схему, `seed` создаёт демоданные один раз. Пароли пользователей librarian и reader находятся в `.env`. Откройте `http://VM1_IP:8080`; разрешите TCP 8080 в firewall VM1 и сетевом firewall. Файл `.env` не отправляйте в Git.

Обновление: сделайте резервную копию, получите новую ревизию, выполните `make migrate`, затем `make up`. Эти команды сначала выполняют `make container-check`.

## 4. Проверки на защите

На VM1:

```sh
make container-check
for i in $(seq 1 8); do curl -sI http://localhost:8080/health | grep -i x-instance-id; done
docker compose exec app1 id
docker compose exec app2 id
docker compose stop app1
curl -fsS http://localhost:8080/health
docker inspect "$(docker compose ps -aq app1)" --format '{{.State.ExitCode}}'
docker compose start app1
```

Должны появиться два идентификатора. После остановки одного экземпляра запросы обслуживает второй; ожидаемый код завершения — 0. Gunicorn получает SIGTERM и завершает запросы в пределах 30 секунд. Приложение и база напрямую не опубликованы на VM1.

Создайте автора в интерфейсе под librarian. Для пересоздания контейнеров без удаления данных выполните на VM1 `make container-check && docker compose up -d --force-recreate`, на VM2 — `make container-check MODE=db && docker compose -f compose.db.yml up -d --force-recreate`. Проверьте автора. Для проверки обновления образа измените версию или код, выполните `make up` и убедитесь, что автор сохранился. Не используйте `down -v` с нужными данными.

## 5. Резервная копия и восстановление в новый volume

На VM2:

```sh
umask 077
mkdir -p backups
docker compose -f compose.db.yml exec -T db pg_dump -U library -d library -Fc > backups/library.dump
make container-check MODE=db
DB_BIND_IP=127.0.0.1 DB_PORT=15432 docker compose -p library-restore -f compose.db.yml up -d
# Дождитесь healthy в выводе следующей команды:
DB_BIND_IP=127.0.0.1 DB_PORT=15432 docker compose -p library-restore -f compose.db.yml ps
DB_BIND_IP=127.0.0.1 DB_PORT=15432 docker compose -p library-restore -f compose.db.yml exec -T db pg_restore -U library -d library --clean --if-exists < backups/library.dump
DB_BIND_IP=127.0.0.1 DB_PORT=15432 docker compose -p library-restore -f compose.db.yml exec -T db psql -U library -d library -c 'SELECT * FROM authors;'
```

Проверьте созданного автора. Используется отдельный проект Compose и новый volume; исходная база не затрагивается. Backup содержит данные пользователей, храните его с ограниченным доступом.

## Ограничения и правила

Запрещены latest, root-процессы сервисов, секреты в образе, отключение healthcheck и лишние опубликованные порты. `make container-check` проверяет конфигурацию, образы, healthcheck, ресурсы, порты, внутреннюю сеть, пользователя и доступ к БД; firewall и отсутствие секретов в исходном коде проверяются отдельно. На VM2 перед изменениями выполняйте `make container-check MODE=db`.

Лимиты: 0,5 CPU и 256 МБ на экземпляр приложения, 0,25 CPU и 128 МБ на Nginx, 1 CPU и 512 МБ на БД — старт для небольшой учебной нагрузки. Данные и сессии хранятся в общей базе. PostgreSQL, VM2 и Nginx остаются едиными точками отказа; сериализация операций выдачи и общая база ограничивают масштабирование записи.
