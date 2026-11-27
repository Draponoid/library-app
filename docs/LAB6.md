# Лабораторная работа №6 Continuous Delivery

Цель: доставить в отдельное тестовое окружение на двух Ubuntu VM ровно тот образ, который прошёл CI. VM1 запускает Nginx и два приложения на порту 8081, VM2 — отдельную PostgreSQL на порту 5433. Данные лабораторной №4 не используются. Нужны установленные Docker и Compose, интернет у VM1 и VM2, SSH между VM, sudo и доступ к настройкам GitHub-репозитория. Подставьте частные IP вместо VM1_IP и VM2_IP.

## 1. Отдельная тестовая база на VM2

```sh
git clone -b lab6-continuous-delivery https://github.com/Draponoid/library-app.git ~/library-lab6-db
cd ~/library-lab6-db
umask 077
DB_PASSWORD=$(openssl rand -hex 24)
printf 'DB_BIND_IP=VM2_IP\nDB_PORT=5433\nPOSTGRES_PASSWORD=%s\n' "$DB_PASSWORD" > .env
unset DB_PASSWORD
sudo make container-check MODE=db
sudo bash scripts/install-stage-firewall.sh VM1_IP VM2_IP
sudo make db-up
sudo docker compose -f compose.db.yml ps
```

Дождитесь `healthy`. Разрешите VM1 → VM2 TCP 5433 в firewall сети или гипервизора. Скрипт добавляет правило в DOCKER-USER на VM2, но не управляет внешним firewall. Пароль базы находится в `~/library-lab6-db/.env`; не публикуйте его.

## 2. Отдельная учётная запись и настройки на VM1

```sh
sudo useradd -m -s /bin/bash librarycd
sudo usermod -aG docker librarycd
sudo -iu librarycd
mkdir -p ~/library-stage
chmod 700 ~/library-stage
```

Если `librarycd` уже существует, не используйте её автоматически: сначала убедитесь, что она выделена для этой лабораторной. Группа `docker` фактически даёт права администратора на VM: запускайте runner только для доверенного кода и не направляйте на него задания из чужих PR.

Под пользователем `librarycd` создайте конфигурацию. Введите пароль из `.env` на VM2, когда команда попросит его:

```sh
umask 077
read -rs -p 'Пароль тестовой PostgreSQL: ' DB_PASSWORD; echo
LIBRARIAN_PASSWORD=$(openssl rand -hex 12)
printf 'DATABASE_URL=postgresql://library:%s@VM2_IP:5433/library\nSECRET_KEY=%s\nDEMO_LIBRARIAN_PASSWORD=%s\nDEMO_READER_PASSWORD=%s\nCD_SMOKE_USERNAME=librarian\nCD_SMOKE_PASSWORD=%s\nHTTP_PORT=8081\n' "$DB_PASSWORD" "$(openssl rand -hex 32)" "$LIBRARIAN_PASSWORD" "$(openssl rand -hex 12)" "$LIBRARIAN_PASSWORD" > ~/library-stage/.env
unset DB_PASSWORD LIBRARIAN_PASSWORD
```

Файл содержит секреты и остаётся на VM1, вне образа и Git. Откройте доступ к TCP 8081 на VM1 только в учебной сети. Для доступа из интернета нужен HTTPS.

## 3. Runner и GitHub

На GitHub откройте **Settings → Environments → New environment**, создайте `staging` и добавьте environment variable `STAGING_DIR` со значением `/home/librarycd/library-stage`. Ограничьте разрешённую ветку `master`. На **Settings → Actions → Runners → New self-hosted runner** выберите Linux x64 и выполните показанные GitHub команды от пользователя `librarycd` в каталоге `~/actions-runner`. При выполнении `config.sh` добавьте `--labels library-stage`. Регистрационный токен короткоживущий; используйте тот, который выдаст GitHub, и не отправляйте его в чат.

Затем выйдите из `librarycd` и от администратора VM1 запустите runner как службу:

```sh
cd /home/librarycd/actions-runner
sudo ./svc.sh install librarycd
sudo ./svc.sh start
sudo ./svc.sh status
```

Убедитесь в GitHub, что runner `library-stage` находится в состоянии Idle. На runner запускается только задача развёртывания из `master`; тесты PR выполняются на GitHub-hosted runner. Пользователь `librarycd` должен иметь доступ к Docker без sudo. Инструкция GitHub: https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners .

Если пакет GHCR приватный, свяжите пакет с репозиторием и дайте ему Actions-доступ на чтение: задача получает `GITHUB_TOKEN` с `packages: read`. При ручной подготовке ниже выполните `docker login ghcr.io` под `librarycd` с отдельным токеном чтения пакетов либо сделайте пакет доступным для чтения. Не записывайте токен в `.env`.

## 4. Первый запуск и автоматический выпуск

Сначала объедините PR в `master`. После успешных тестов задача публикует `ghcr.io/draponoid/library-app:sha-<полный SHA коммита>`. Пока база не инициализирована, первый автоматический деплой может завершиться ошибкой; это нормально, образ уже опубликован. Скопируйте тег из шага Publish tested image в GitHub Actions.

На VM1 от пользователя `librarycd` один раз для **новой пустой тестовой базы**:

```sh
git clone -b master https://github.com/Draponoid/library-app.git ~/library-lab6
cd ~/library-lab6
export RELEASE_IMAGE=ghcr.io/draponoid/library-app:sha-ПОЛНЫЙ_SHA
docker compose --project-name library-stage --env-file ~/library-stage/.env -f compose.release.yml pull app1
docker compose --project-name library-stage --env-file ~/library-stage/.env -f compose.release.yml run --rm --no-deps app1 python app.py migrate
docker compose --project-name library-stage --env-file ~/library-stage/.env -f compose.release.yml run --rm --no-deps app1 python app.py init-demo
```

Вместо `sha-ПОЛНЫЙ_SHA` укажите существующий тег, состоящий из `sha-` и 40 строчных шестнадцатеричных символов. Не выполняйте `init-demo` на заполненной базе. В GitHub откройте **Actions → CI and container checks → Run workflow**, выберите `master` и укажите тот же `image_tag`. Успех — зелёная задача `deploy-staging` и запись тега в `/home/librarycd/library-stage/active-tag`.

После настройки каждый успешный push в `master` проходит тесты, публикует образ и запускает развёртывание. VM1 выполняет `make container-check MODE=release`, скачивает образ, не собирая его, запускает контейнеры и проверяет healthcheck, `/health`, `/version`, вход и каталог. Проверка обоих экземпляров обязательна. Два выпуска не выполняются одновременно. Тег обновляется только после успешной проверки.

## 5. Проверка и защита

На VM1:

```sh
curl -fsS http://localhost:8081/health
curl -fsS http://localhost:8081/version
sudo -u librarycd cat /home/librarycd/library-stage/active-tag
```

В Actions покажите порядок: тесты → публикация SHA-образа → `deploy-staging`. Откройте сайт `http://VM1_IP:8081`, войдите как `librarian`, пароль в `/home/librarycd/library-stage/.env`, проверьте каталог. Не показывайте файл с секретами на экране.

Ручной возврат: возьмите предыдущий успешный SHA-тег из Actions и через **Run workflow** на `master` запустите его в поле `image_tag`. После успешной проверки `/version` и `active-tag` покажут этот тег. Откат образа не откатывает схему и данные БД; перед несовместимыми миграциями нужна отдельная стратегия и backup. Старые образы без `/version` не подходят для этого механизма.

Продемонстрируйте неуспешные случаи в тестовой среде:

- Неверный формат тега или отсутствующий тег: Run workflow завершается ошибкой до замены контейнеров.
- Нет переменной: временно переименуйте `CD_SMOKE_PASSWORD` в `.env`; проверка останавливается до замены контейнеров. Верните её.
- Недоступен registry: укажите несуществующий SHA-тег либо временно ограничьте доступ VM1 к GHCR; получение образа завершится ошибкой. Восстановите доступ.
- Не проходит healthcheck: в копии `.env` временно укажите недоступную тестовую БД, выполните выпуск и верните настройки. Контейнеры не станут здоровыми, выпуск будет красным.
- Сайт отвечает, но пользовательский сценарий не работает: временно укажите неверный `CD_SMOKE_PASSWORD`; health может пройти, но вход не пройдёт, выпуск будет красным.
- После сбоя верните настройки и вручную разверните предыдущий успешный тег через Run workflow; проверьте `/version`.

При сбое после обновления контейнеры могут остаться в неисправном состоянии: `active-tag` сохраняет последний проверенный тег, но **автоматического отката нет**. Верните предыдущий тег вручную. Перед экспериментами сохраните копию `.env` с правами 600 и backup тестовой БД; не проводите их на рабочей среде.
