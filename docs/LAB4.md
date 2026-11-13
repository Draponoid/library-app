# Лабораторная работа №4: две Ubuntu VM

VM1: Nginx и два экземпляра приложения. VM2: PostgreSQL. Замените VM1_IP и VM2_IP на частные IP-адреса. Нужны связь между VM, интернет, sudo и не менее 2 ГБ RAM на каждой VM. HTTP подходит только для учебной сети.

## 1. Автоматическая установка на две VM

На обеих VM нужны Ubuntu с интернетом и sudo без пароля. С VM1 должен работать SSH по ключу на VM2, причём ключ сервера VM2 должен уже быть проверен в `~/.ssh/known_hosts`. Проверьте IP и SSH-имя; в сетевом firewall гипервизора/облака разрешите VM1 → VM2 TCP 5432 и доступ к VM1 TCP 8080.

На VM1 вставьте одну команду, заменив `VM1_IP`, `VM2_IP` и `USER@VM2`:

```sh
sudo -n apt-get update && sudo -n apt-get install -y git && git clone -b lab4-containerization https://github.com/Draponoid/library-app.git && cd library-app && bash scripts/deploy-two-vms.sh VM1_IP VM2_IP USER@VM2
```

Скрипт установит Docker и Compose на обе VM, скачает тот же коммит на VM2, создаст случайные пароли, настроит правило Docker для PostgreSQL с доступом только от VM1, запустит базу, применит схему, создаст демоданные и запустит два приложения с Nginx. На VM1 с активным UFW откроется TCP 8080. Правило на VM2 сохраняется при перезапуске Docker. Облачный или сетевой firewall скрипт не меняет: его правила задаются в интерфейсе платформы.

Откройте `http://VM1_IP:8080`. Логины `librarian` и `reader`; пароли находятся на VM1 в `library-app/.env` (права 600). Пароль базы также записан на VM2 в `~/library-lab4-db/.env`. Не публикуйте эти файлы. Окружение рассчитано на учебную сеть; для доступа из интернета нужен HTTPS.

Скрипт предназначен для первой установки и не перезаписывает существующие `.env`, каталог `~/library-lab4-db` и созданные им правила firewall. При ошибке просмотрите её и состояние обеих VM, прежде чем удалять или менять какие-либо файлы и повторять запуск. После слияния PR замените имя ветки `lab4-containerization` на `master`.

Для обновления сохраните резервную копию, получите новую ревизию на VM1, затем выполните `sudo make migrate` и `sudo make up`. Эти команды сначала выполняют `make container-check`. На VM2 команды базы выполняются из `~/library-lab4-db`; если текущий пользователь не входит в группу docker, добавьте к ним `sudo`.

## 2. Проверки на защите

На VM1:

```sh
sudo make container-check
for i in $(seq 1 8); do curl -sI http://localhost:8080/health | grep -i x-instance-id; done
sudo docker compose exec app1 id
sudo docker compose exec app2 id
sudo docker compose stop app1
curl -fsS http://localhost:8080/health
sudo docker inspect "$(sudo docker compose ps -aq app1)" --format '{{.State.ExitCode}}'
sudo docker compose start app1
```

Должны появиться два идентификатора. После остановки одного экземпляра запросы обслуживает второй; ожидаемый код завершения — 0. Gunicorn получает SIGTERM и завершает запросы в пределах 30 секунд. Приложение и база напрямую не опубликованы на VM1.

Создайте автора в интерфейсе под librarian. Для пересоздания контейнеров без удаления данных выполните на VM1 `sudo make container-check && sudo docker compose up -d --force-recreate`, на VM2 — `sudo make container-check MODE=db && sudo docker compose -f compose.db.yml up -d --force-recreate`. Проверьте автора. Для проверки обновления образа измените версию или код, выполните `sudo make up` и убедитесь, что автор сохранился. Не используйте `down -v` с нужными данными.

## 3. Резервная копия и восстановление в новый volume

На VM2:

```sh
umask 077
mkdir -p backups
sudo docker compose -f compose.db.yml exec -T db pg_dump -U library -d library -Fc > backups/library.dump
sudo make container-check MODE=db
sudo env DB_BIND_IP=127.0.0.1 DB_PORT=15432 docker compose -p library-restore -f compose.db.yml up -d
# Дождитесь healthy в выводе следующей команды:
sudo env DB_BIND_IP=127.0.0.1 DB_PORT=15432 docker compose -p library-restore -f compose.db.yml ps
sudo env DB_BIND_IP=127.0.0.1 DB_PORT=15432 docker compose -p library-restore -f compose.db.yml exec -T db pg_restore -U library -d library --clean --if-exists < backups/library.dump
sudo env DB_BIND_IP=127.0.0.1 DB_PORT=15432 docker compose -p library-restore -f compose.db.yml exec -T db psql -U library -d library -c 'SELECT * FROM authors;'
```

Проверьте созданного автора. Используется отдельный проект Compose и новый volume; исходная база не затрагивается. Backup содержит данные пользователей, храните его с ограниченным доступом.

## Ограничения и правила

Запрещены latest, root-процессы сервисов, секреты в образе, отключение healthcheck и лишние опубликованные порты. `sudo make container-check` проверяет конфигурацию, образы, healthcheck, ресурсы, порты, внутреннюю сеть, пользователя и доступ к БД; firewall и отсутствие секретов в исходном коде проверяются отдельно. На VM2 перед изменениями выполняйте `sudo make container-check MODE=db`.

Лимиты: 0,5 CPU и 256 МБ на экземпляр приложения, 0,25 CPU и 128 МБ на Nginx, 1 CPU и 512 МБ на БД — старт для небольшой учебной нагрузки. Данные и сессии хранятся в общей базе. PostgreSQL, VM2 и Nginx остаются едиными точками отказа; сериализация операций выдачи и общая база ограничивают масштабирование записи.
