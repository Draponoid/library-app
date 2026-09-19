# Git-процесс ЛР1

Задача: https://github.com/Draponoid/library-app/issues/1

Порядок проверки: локальные тесты, проверка API-фильтров и проверка Docker-контейнера.

Ветка features сохраняется без изменений. Рабочая ветка: lab/loan-status.

## Демонстрация конфликта

19.09.2026 изменена одна строка порядка приёмки: в ветке lab/loan-status добавлена проверка API, в master — проверка Docker. После `git merge master` Git выдал `CONFLICT (content): Merge conflict in docs/GIT_PROCESS.md`, статус `UU docs/GIT_PROCESS.md`. Решение сохраняет оба требования: API и Docker.

Исходные коммиты: `9884bc1` (функция и требование API) и `88d07d5` (требование Docker). Общая база: `f2f218f`.

```text
git switch lab/loan-status
git merge master
# CONFLICT (content): Merge conflict in docs/GIT_PROCESS.md
# Вручную объединены оба требования, удалены маркеры конфликта.
git add docs/GIT_PROCESS.md
git commit -m "merge: resolve acceptance checklist conflict preserving both checks"
```

После разрешения выполняются тесты и CI. Исходные варианты доступны через `git show 9884bc1:docs/GIT_PROCESS.md` и `git show 88d07d5:docs/GIT_PROCESS.md`; merge-коммит сохраняет оба родителя. Это реальный конфликт Git, а не иллюстрация команд без выполнения.
