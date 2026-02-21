# Security and Quality Stack

Этот документ фиксирует единый контур проверки проекта:
- `pytest + coverage` (через `python manage.py test` + `coverage`)
- `bandit` (SAST для Python-кода)
- `pip-audit` (уязвимости зависимостей)
- `semgrep` (правила security/secrets)
- `CodeQL` (GitHub code scanning)

## Где запускать

- Локально: перед push/PR (быстрая проверка на своей машине).
- В GitHub Actions: автоматически на `push`/`pull_request` в `main` и вручную через `workflow_dispatch`.

## 1) Локальный запуск (PowerShell)

Из корня репозитория:

```powershell
cd backend
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install bandit pip-audit

python -m coverage run manage.py test --noinput
python -m coverage report --fail-under=75
python -m coverage xml

python -m bandit -q -r . -x tests -ll -ii
python -m pip_audit -r requirements.txt --progress-spinner off

cd ..
python -m semgrep scan --config p/security-audit --config p/secrets --severity ERROR --error --metrics=off backend
```

Примечание для Windows:
- `semgrep` может не устанавливаться в локальный Python.
- В этом случае запускайте через Docker:

```powershell
docker run --rm -v "${PWD}:/src" returntocorp/semgrep semgrep scan --config p/security-audit --config p/secrets --severity ERROR --error --metrics=off backend
```

## 2) Локальный запуск одной командой

Из корня репозитория:

```powershell
./scripts/run_quality_stack.ps1 -InstallTools
```

Повторный запуск (без переустановки инструментов):

```powershell
./scripts/run_quality_stack.ps1
```

## 3) GitHub Actions

В репозитории настроены workflow:
- `.github/workflows/quality_security.yml`
- `.github/workflows/codeql.yml`

Они запускаются автоматически:
- при `push` в `main`
- при `pull_request` в `main`
- вручную из вкладки `Actions` (`Run workflow`)

## Интерпретация результатов

- `tests + coverage`: регрессии функционала и порог покрытия.
- `bandit`: потенциально опасные конструкции в коде.
- `pip-audit`: известные CVE в зависимостях.
- `semgrep`: дополнительные security/secrets-паттерны.
- `CodeQL`: глубокий анализ потока данных и security-антипаттернов.
