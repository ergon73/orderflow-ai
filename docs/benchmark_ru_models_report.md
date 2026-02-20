# RU LLM Benchmark Report

- cases: `10`

| target | provider | runtime model | strict success | adjusted success | missing rate | unexpected missing | p95 ms | avg ms | errors | in RUB/1k | out RUB/1k |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| YandexGPT Lite | yandexgpt | `yandexgpt-lite` | 80.00% | 90.00% | 20.00% | 10.00% | 2006.74 | 1669.30 | 0 | 0.2033 | 0.2033 |
| YandexGPT | yandexgpt | `yandexgpt` | 80.00% | 90.00% | 20.00% | 10.00% | 2273.47 | 1950.70 | 0 | 0.8200 | 0.8200 |
| GigaChat Pro | gigachat | `GigaChat-2-Pro` | 90.00% | 100.00% | 10.00% | 0.00% | 4594.15 | 3668.91 | 0 | - | - |
| GigaChat Max | gigachat | `GigaChat-2-Max` | 90.00% | 100.00% | 10.00% | 0.00% | 3620.48 | 3061.77 | 0 | - | - |
| vLLM Local | vllm | `Qwen/Qwen2.5-VL-7B-Instruct-AWQ` | 90.00% | 100.00% | 10.00% | 0.00% | 3552.24 | 1777.58 | 0 | - | - |

## Notes
- `strict success` = доля кейсов без ошибок и без `missing_fields` вообще.
- `adjusted success` = доля кейсов без ошибок и без НЕОЖИДАННЫХ пропусков. Ожидаемые пропуски (когда поле отсутствует в исходном тексте) не считаются ошибкой модели.
- `missing rate` = доля кейсов, где разбор прошел, но есть любые `missing_fields`.
- `unexpected missing` = доля кейсов с пропусками, которых не должно было быть по исходному тексту.
- `p95` считается по latency полного parse+post-validation.
- цены указаны как справочные RUB/1000 токенов; для моделей с `-` нужно подставить текущий тариф.
