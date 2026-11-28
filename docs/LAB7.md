# Лабораторная работа №7 Управление конфигурацией

Ansible управляет двумя Ubuntu VM: VM1 запускает приложение и Nginx, VM2 — PostgreSQL. Есть отдельные окружения `prod` и `staging` с разными каталогами, портами и томами; старые окружения лабораторных №4 и №6 не удаляются. `prod` в этой работе — учебное окружение, а не настоящий промышленный сервер.

| Окружение | Приложение на VM1 | PostgreSQL на VM2 |
|---|---:|---:|
| prod | 8082 | 5542 |
| staging | 8083 | 5543 |

Нужны две Ubuntu VM с интернетом, существующий пользователь с sudo, SSH по ключу и проверенные ключи обоих серверов в `known_hosts`. Команды ниже выполняются в Linux-терминале управляющей машины; им может быть VM1, если с неё работает SSH к обеим VM. Ansible при необходимости установит Python на целевой Ubuntu.

## 1. Подготовить Ansible

```sh
sudo apt-get update
sudo apt-get install -y git python3-venv openssl
git clone -b lab7-configuration https://github.com/Draponoid/library-app.git ~/library-lab7
cd ~/library-lab7
python3 -m venv .venv-infra
. .venv-infra/bin/activate
pip install -r infra/requirements.txt
ansible-galaxy collection install -r infra/requirements.yml
export ANSIBLE_CONFIG="$PWD/infra/ansible.cfg"
```

До слияния PR используется ветка `lab7-configuration`; после слияния можно использовать `master`.

## 2. Указать VM и сети

Создайте локальные копии inventory, чтобы случайно не публиковать адреса своих VM:

```sh
mkdir -p ~/lab7-config
cp -r infra/inventories/prod infra/inventories/staging ~/lab7-config/
```

В каждом окружении отредактируйте файлы `host_vars/lab_app.yml` и `host_vars/lab_db.yml`: замените `ansible_host` и `lab_bind_address` на частные IPv4-адреса VM1 и VM2 соответственно. При необходимости добавьте `ansible_user: имя_пользователя` в каждый файл; по умолчанию используется `ubuntu`.

В файл `group_vars/lab_environment.yml` каждого окружения добавьте свои сети, например:

```yaml
lab_admin_cidr: 192.168.1.0/24
lab_client_cidr: 192.168.1.0/24
```

Первая сеть должна включать адрес управляющей машины для SSH на обе VM, вторая — адреса, которым разрешён сайт. Ansible разрешает SSH из `lab_admin_cidr`, включает UFW и ограничивает опубликованные Docker-порты. **Проверьте CIDR до запуска**, иначе можно потерять SSH-доступ. Правила облака/гипервизора настраиваются отдельно: разрешите VM1 → VM2 порты 5542/5543 и доступ клиентов к VM1 на 8082/8083. Не применяйте примерные адреса 192.0.2.x.

Ansible создаст непривилегированного пользователя `librarydeploy` с указанным публичным SSH-ключом, без sudo и членства в группе Docker. Создайте файл с публичным ключом для playbook; замените путь, если используете другой ключ:

```sh
python3 - <<'PY'
import json
from pathlib import Path
key = (Path.home() / '.ssh/id_ed25519.pub').read_text().strip()
(Path.home() / 'lab7-config/operator.json').write_text(json.dumps({'lab_deploy_public_key': key}))
PY
```

## 3. Создать зашифрованные секреты

Для каждого окружения создайте отдельный Vault-файл. Пароль Vault храните отдельно от Git и не публикуйте:

```sh
mkdir -p infra/secrets
ansible-vault create infra/secrets/staging.vault.yml
ansible-vault create infra/secrets/prod.vault.yml
```

В редакторе каждого файла укажите **разные для каждого окружения** значения:

```yaml
vault_db_password: ЗДЕСЬ_СЛУЧАЙНЫЙ_HEX_ИЗ_24_БАЙТ
vault_secret_key: ЗДЕСЬ_СЛУЧАЙНЫЙ_HEX_ИЗ_32_БАЙТ
vault_demo_librarian_password: ЗДЕСЬ_СЛУЧАЙНЫЙ_HEX_ИЗ_12_БАЙТ
vault_demo_reader_password: ЗДЕСЬ_ДРУГОЙ_СЛУЧАЙНЫЙ_HEX_ИЗ_12_БАЙТ
```

Значения получают командами `openssl rand -hex 24`, `openssl rand -hex 32`, `openssl rand -hex 12` и ещё раз `openssl rand -hex 12`; замените ими текстовые заглушки. Это пароли, не показывайте их на экране преподавателю. `ansible-vault create` сохраняет зашифрованный файл; пароль Vault в репозиторий не добавляйте.

Нужен конкретный существующий образ приложения из GHCR, например `ghcr.io/draponoid/library-app:sha-<полный SHA>`; `latest` запрещён. Если пакет закрыт, добавьте в Vault `vault_registry_username` и `vault_registry_token` с правом чтения пакета, а в group_vars окружения — `lab_registry_auth: true`. Ansible выполнит вход на VM1 без вывода токена; Docker хранит его в доступном только root `/root/.docker/config.json`.

## 4. Применить настройки

Замените тег на реально опубликованный. Сначала staging:

```sh
ansible-playbook -i ~/lab7-config/staging/hosts.yml infra/site.yml \
  -e "@$HOME/lab7-config/operator.json" \
  -e @infra/secrets/staging.vault.yml \
  -e lab_app_image=ghcr.io/draponoid/library-app:sha-ПОЛНЫЙ_SHA \
  --ask-vault-pass
```

Затем так же запустите `prod`: замените оба вхождения `staging` на `prod`. Если sudo требует пароль, добавьте `--ask-become-pass`. Скрипт подготовит пакеты, Docker, SSH и firewall, создаст конфигурацию и запустит БД и приложение. Для новой пустой БД демоданные создаются один раз. Итоговая проверка `/health` должна пройти.

Откройте `http://VM1_IP:8083/health` для staging и `http://VM1_IP:8082/health` для prod. Сами сайты доступны по этим адресам без `/health`. Пароли демопользователей находятся в Vault-файлах.

Схема применяется только при создании нового тома PostgreSQL. Повторный запуск не выполняет миграции существующих таблиц и не меняет пароль PostgreSQL внутри уже созданной базы. Для изменения схемы или ротации пароля требуется отдельная миграция и резервная копия.

## 5. Проверка на защите

1. На чистых учебных VM покажите первый запуск команды из раздела 4: Ansible установит ПО, настроит машины и проверит `/health`.
2. Запустите ту же команду ещё раз с теми же параметрами. В конце, в `PLAY RECAP`, ожидается `changed=0` и `failed=0` на обоих узлах.
3. На VM1 измените управляемый файл staging:

   ```sh
   sudo sed -i 's/worker_connections 1024/worker_connections 256/' /opt/library-lab7/staging/application/nginx.conf
   ```

   Снова выполните команду staging из раздела 4. Ansible восстановит `1024` и пересоздаст Nginx для применения файла. Проверьте:

   ```sh
   grep worker_connections /opt/library-lab7/staging/application/nginx.conf
   curl -fsS http://VM1_IP:8083/health
   ```

4. Покажите `prod` и `staging` на двух портах. На VM2 тома БД различаются; данные одного окружения не должны появляться в другом.
5. Покажите только заголовок Vault и права файлов, не содержимое паролей:

   ```sh
   head -n 1 infra/secrets/staging.vault.yml
   sudo stat -c '%a %U %G' /opt/library-lab7/staging/application/.env
   python infra/check_policy.py
   ```

   Первая строка начинается с `$ANSIBLE_VAULT;`, у `.env` ожидается `600 root root`. Файл `.env` на VM2 также имеет права 600. Сканер проверяет несколько типичных нарушений и не гарантирует нахождение всех возможных секретов.

## 6. Согласование и CI

`.github/CODEOWNERS` назначает владельца `@Draponoid` для инфраструктуры, зашифрованных файлов Vault, workflow и правил защиты. **Один CODEOWNERS не включает обязательное согласование.** Администратор репозитория должен в Settings → Branches или Rulesets для `master` включить обязательный PR, `Require review from Code Owners` и успешную проверку `Infrastructure verification / infra`; настройте запрет обхода этих правил. У пользователя с правом Write может не быть доступа к этим настройкам.

Зашифрованные файлы `infra/secrets/*.vault.yml` можно добавлять в отдельный PR после создания; владелец кода должен согласовать изменение. Например: `git add infra/secrets/staging.vault.yml infra/secrets/prod.vault.yml`, затем `python infra/check_policy.py` и PR. Перед публикацией убедитесь, что файлы зашифрованы. Локальные inventory и файл `operator.json` храните вне Git. Пароли Vault и приватные SSH-ключи никогда не коммитьте.

Отдельный workflow `.github/workflows/infra.yml` запускает проверки инфраструктуры на PR и push в master: политика, Ansible lint/syntax, установка контейнерного окружения в CI, повторный запуск, исправление изменений и запуск второго окружения. CI выполняется на одном временном Linux runner и не подключается к вашим VM; настройка чистых VM, SSH и реального firewall должна быть проверена у вас перед защитой. Файл Docker firewall использует `iptables` с `--ctorigdstport`, поскольку опубликованные Docker-порты могут обходить UFW; скрипт восстанавливает отдельную цепочку при изменении или перезапуске Docker.
