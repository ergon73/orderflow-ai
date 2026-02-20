# RU LLM Benchmark Report

- cases: `50`

| target | provider | runtime model | strict success | adjusted success | missing rate | unexpected missing | p95 ms | avg ms | errors | in RUB/1k | out RUB/1k |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GigaChat Pro | gigachat | `GigaChat-2-Pro` | 100.00% | 100.00% | 0.00% | 0.00% | 4126.79 | 3499.78 | 0 | - | - |

## Notes
- `strict success` = доля кейсов без ошибок и без `missing_fields` вообще.
- `adjusted success` = доля кейсов без ошибок и без НЕОЖИДАННЫХ пропусков. Ожидаемые пропуски (когда поле отсутствует в исходном тексте) не считаются ошибкой модели.
- `missing rate` = доля кейсов, где разбор прошел, но есть любые `missing_fields`.
- `unexpected missing` = доля кейсов с пропусками, которых не должно было быть по исходному тексту.
- `p95` считается по latency полного parse+post-validation.
- цены указаны как справочные RUB/1000 токенов; для моделей с `-` нужно подставить текущий тариф.
