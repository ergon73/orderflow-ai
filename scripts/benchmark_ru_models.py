from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    text: str
    expected_missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelTarget:
    key: str
    label: str
    provider: str
    env_overrides: dict[str, str]
    price_in_rub_per_1k: float | None
    price_out_rub_per_1k: float | None
    price_note: str


DEFAULT_CASES: list[BenchmarkCase] = [
    BenchmarkCase(
        case_id="c01_basic_full",
        text=(
            "Хочу 2 кружки и 1 футболку, доставка Москва, ул. Тверская 7, "
            "телефон +79161234567, email georgy.belyanin@gmail.com"
        ),
    ),
    BenchmarkCase(
        case_id="c02_missing_phone",
        text="Хочу 1 кружку, доставка Казань, ул. Баумана 12, email test@example.com",
        expected_missing=("customer.phone",),
    ),
    BenchmarkCase(
        case_id="c03_short_order",
        text="Нужна футболка 2 шт, Питер, Невский 10, телефон 89161234567",
    ),
    BenchmarkCase(
        case_id="c04_two_items_named",
        text=(
            "Добрый день. Заказ: кружка x3, худи x1. "
            "Адрес: Москва, Ленинский проспект 45. "
            "Контакт: +7 (916) 123-45-67."
        ),
    ),
    BenchmarkCase(
        case_id="c05_slot_fill_like",
        text=(
            "Исправляю заказ: вместо 1 кружки нужно 2 кружки и 1 свитшот, "
            "адрес прежний - ул. Арбат 5, телефон тот же +79161234567."
        ),
    ),
    BenchmarkCase(
        case_id="c06_noise_text",
        text=(
            "Здравствуйте! Сначала думал не заказывать, но все же хочу 2 кружки. "
            "Доставка в Москву, ул. Профсоюзная 20, подъезд 3. "
            "Связь: 8 916 123 45 67."
        ),
    ),
    BenchmarkCase(
        case_id="c07_email_plus_name",
        text=(
            "Нужны 2 футболки и 1 кепка, доставить в СПб, ул. Марата 11. "
            "Меня зовут Георгий, телефон +79161234567, почта georgy.belyanin@gmail.com."
        ),
    ),
    BenchmarkCase(
        case_id="c08_minimal",
        text="2 кружки, ул. Ленина 10, +79161234567",
    ),
    BenchmarkCase(
        case_id="c09_complex_sentence",
        text=(
            "Закажу, пожалуй, три кружки и футболку, но если нельзя футболку, то только кружки. "
            "Доставка нужна по адресу Москва, ул. Большая Никитская 14, "
            "номер для связи +79161234567."
        ),
    ),
    BenchmarkCase(
        case_id="c10_typo_phone_format",
        text=(
            "хачу 1 худи и 2 кружки, доствка москва ул тверская 8, тел 8-916-123-45-67, "
            "email test.order@example.com"
        ),
    ),
]


DEFAULT_MODEL_TARGETS: list[ModelTarget] = [
    ModelTarget(
        key="yandex-lite",
        label="YandexGPT Lite",
        provider="yandexgpt",
        env_overrides={
            "YANDEXGPT_MODEL_NAME": "yandexgpt-lite",
            "YANDEXGPT_MODEL_URI": "",
            "YANDEXGPT_ESCALATION_ENABLED": "false",
        },
        price_in_rub_per_1k=0.2033,
        price_out_rub_per_1k=0.2033,
        price_note="Yandex public price table (sync, RUB/1k, Feb 2026 snapshot)",
    ),
    ModelTarget(
        key="yandex-full",
        label="YandexGPT",
        provider="yandexgpt",
        env_overrides={
            "YANDEXGPT_MODEL_NAME": "yandexgpt",
            "YANDEXGPT_MODEL_URI": "",
            "YANDEXGPT_ESCALATION_ENABLED": "false",
        },
        price_in_rub_per_1k=0.82,
        price_out_rub_per_1k=0.82,
        price_note="Yandex public price table (sync, RUB/1k, Feb 2026 snapshot)",
    ),
    ModelTarget(
        key="gigachat-pro",
        label="GigaChat Pro",
        provider="gigachat",
        env_overrides={
            "GIGACHAT_MODEL": "GigaChat-2-Pro",
            "GIGACHAT_ESCALATION_ENABLED": "false",
        },
        price_in_rub_per_1k=None,
        price_out_rub_per_1k=None,
        price_note="set manually from current tariff plan",
    ),
    ModelTarget(
        key="gigachat-max",
        label="GigaChat Max",
        provider="gigachat",
        env_overrides={
            "GIGACHAT_MODEL": "GigaChat-2-Max",
            "GIGACHAT_ESCALATION_ENABLED": "false",
        },
        price_in_rub_per_1k=None,
        price_out_rub_per_1k=None,
        price_note="set manually from current tariff plan",
    ),
]


def setup_django() -> None:
    project_root = Path(__file__).resolve().parents[1]
    backend_dir = project_root / "backend"
    sys.path.insert(0, str(backend_dir))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    rank = int(round((len(sorted_values) - 1) * p))
    rank = max(0, min(rank, len(sorted_values) - 1))
    return sorted_values[rank]


@contextmanager
def temporary_env(overrides: dict[str, str]):
    original: dict[str, str | None] = {}
    for key, value in overrides.items():
        original[key] = os.environ.get(key)
        os.environ[key] = value
    try:
        yield
    finally:
        for key, old_value in original.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def load_cases(dataset_path: str | None) -> list[BenchmarkCase]:
    if not dataset_path:
        return DEFAULT_CASES

    path = Path(dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset file not found: {path}")

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Dataset file is empty: {path}")

    cases: list[BenchmarkCase] = []
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        for idx, line in enumerate(text.splitlines(), start=1):
            raw = json.loads(line)
            cases.append(
                BenchmarkCase(
                    case_id=str(raw.get("id") or f"case_{idx:03d}"),
                    text=str(raw["text"]),
                    expected_missing=tuple(raw.get("expected_missing") or []),
                )
            )
        return cases

    raw_list = json.loads(text)
    for idx, raw in enumerate(raw_list, start=1):
        cases.append(
            BenchmarkCase(
                case_id=str(raw.get("id") or f"case_{idx:03d}"),
                text=str(raw["text"]),
                expected_missing=tuple(raw.get("expected_missing") or []),
            )
        )
    return cases


def evaluate_target(
    target: ModelTarget,
    cases: list[BenchmarkCase],
) -> dict[str, Any]:
    from ai_parser.services import _build_llm_client_for_provider, _parse_and_validate

    with temporary_env(target.env_overrides):
        llm = _build_llm_client_for_provider(target.provider)

        case_results: list[dict[str, Any]] = []
        latencies_ms: list[float] = []

        for case in cases:
            started = time.perf_counter()
            try:
                extract = _parse_and_validate(
                    llm=llm,
                    intake_text=case.text,
                    previous_extraction=None,
                )
                latency_ms = (time.perf_counter() - started) * 1000.0
                latencies_ms.append(latency_ms)
                case_results.append(
                    {
                        "case_id": case.case_id,
                        "latency_ms": round(latency_ms, 2),
                        "error": "",
                        "missing_fields": list(extract.missing_fields),
                        "missing_count": len(extract.missing_fields),
                        "expected_missing": list(case.expected_missing),
                        "unexpected_missing_fields": sorted(
                            set(extract.missing_fields) - set(case.expected_missing)
                        ),
                        "expected_missing_not_reported": sorted(
                            set(case.expected_missing) - set(extract.missing_fields)
                        ),
                        "adjusted_success": (
                            set(extract.missing_fields) == set(case.expected_missing)
                        ),
                        "has_items": bool(extract.items),
                        "has_phone": bool(extract.customer.phone),
                        "has_address": bool(extract.delivery.address),
                    }
                )
            except Exception as exc:
                latency_ms = (time.perf_counter() - started) * 1000.0
                latencies_ms.append(latency_ms)
                case_results.append(
                    {
                        "case_id": case.case_id,
                        "latency_ms": round(latency_ms, 2),
                        "error": f"{type(exc).__name__}: {exc}",
                        "missing_fields": [],
                        "missing_count": 0,
                        "expected_missing": list(case.expected_missing),
                        "unexpected_missing_fields": [],
                        "expected_missing_not_reported": list(case.expected_missing),
                        "adjusted_success": False,
                        "has_items": False,
                        "has_phone": False,
                        "has_address": False,
                    }
                )

    total = len(case_results)
    errors = sum(1 for x in case_results if x["error"])
    success = sum(1 for x in case_results if (not x["error"] and x["missing_count"] == 0))
    adjusted_success = sum(1 for x in case_results if (not x["error"] and x["adjusted_success"]))
    with_missing = sum(
        1 for x in case_results if (not x["error"] and x["missing_count"] > 0)
    )
    with_unexpected_missing = sum(
        1
        for x in case_results
        if (not x["error"] and bool(x["unexpected_missing_fields"]))
    )
    missing_total = sum(x["missing_count"] for x in case_results if not x["error"])
    has_items = sum(1 for x in case_results if x["has_items"])
    has_phone = sum(1 for x in case_results if x["has_phone"])
    has_address = sum(1 for x in case_results if x["has_address"])

    return {
        "target_key": target.key,
        "target_label": target.label,
        "provider": target.provider,
        "runtime_model_name": getattr(llm, "model_name", "unknown"),
        "total_cases": total,
        "errors": errors,
        "parse_success_rate": round(success / total, 4) if total else 0.0,
        "adjusted_success_rate": round(adjusted_success / total, 4) if total else 0.0,
        "missing_fields_rate": round(with_missing / total, 4) if total else 0.0,
        "unexpected_missing_rate": round(with_unexpected_missing / total, 4)
        if total
        else 0.0,
        "avg_missing_fields": round(missing_total / max(1, (total - errors)), 4),
        "items_presence_rate": round(has_items / total, 4) if total else 0.0,
        "phone_presence_rate": round(has_phone / total, 4) if total else 0.0,
        "address_presence_rate": round(has_address / total, 4) if total else 0.0,
        "latency_ms_p95": round(percentile(latencies_ms, 0.95), 2),
        "latency_ms_avg": round(sum(latencies_ms) / total, 2) if total else 0.0,
        "price_in_rub_per_1k": target.price_in_rub_per_1k,
        "price_out_rub_per_1k": target.price_out_rub_per_1k,
        "price_note": target.price_note,
        "cases": case_results,
    }


def to_markdown(results: list[dict[str, Any]], cases_count: int) -> str:
    lines = [
        "# RU LLM Benchmark Report",
        "",
        f"- cases: `{cases_count}`",
        "",
        "| target | provider | runtime model | strict success | adjusted success | missing rate | unexpected missing | p95 ms | avg ms | errors | in RUB/1k | out RUB/1k |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for row in results:
        in_price = "-" if row["price_in_rub_per_1k"] is None else f'{row["price_in_rub_per_1k"]:.4f}'
        out_price = "-" if row["price_out_rub_per_1k"] is None else f'{row["price_out_rub_per_1k"]:.4f}'
        lines.append(
            "| {target} | {provider} | `{model}` | {success:.2%} | {adjusted_success:.2%} | {missing:.2%} | {unexpected_missing:.2%} | {p95:.2f} | {avg:.2f} | {errors} | {in_price} | {out_price} |".format(
                target=row["target_label"],
                provider=row["provider"],
                model=row["runtime_model_name"],
                success=row["parse_success_rate"],
                adjusted_success=row["adjusted_success_rate"],
                missing=row["missing_fields_rate"],
                unexpected_missing=row["unexpected_missing_rate"],
                p95=row["latency_ms_p95"],
                avg=row["latency_ms_avg"],
                errors=row["errors"],
                in_price=in_price,
                out_price=out_price,
            )
        )

    lines.extend(
        [
            "",
            "## Notes",
            "- `strict success` = доля кейсов без ошибок и без `missing_fields` вообще.",
            "- `adjusted success` = доля кейсов без ошибок и без НЕОЖИДАННЫХ пропусков. Ожидаемые пропуски (когда поле отсутствует в исходном тексте) не считаются ошибкой модели.",
            "- `missing rate` = доля кейсов, где разбор прошел, но есть любые `missing_fields`.",
            "- `unexpected missing` = доля кейсов с пропусками, которых не должно было быть по исходному тексту.",
            "- `p95` считается по latency полного parse+post-validation.",
            "- цены указаны как справочные RUB/1000 токенов; для моделей с `-` нужно подставить текущий тариф.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark RU models for order intake extraction.")
    parser.add_argument("--dataset", default="", help="Path to JSON/JSONL dataset with {'id','text'}.")
    parser.add_argument(
        "--output-json",
        default="docs/benchmark_ru_models_report.json",
        help="Output JSON path.",
    )
    parser.add_argument(
        "--output-md",
        default="docs/benchmark_ru_models_report.md",
        help="Output Markdown path.",
    )
    parser.add_argument(
        "--include-vllm",
        action="store_true",
        help="Include local vLLM model target from current env settings.",
    )
    parser.add_argument(
        "--targets",
        default="",
        help=(
            "Comma-separated target keys to run (e.g. 'gigachat-pro,vllm-local'). "
            "If empty, all configured targets are used."
        ),
    )
    args = parser.parse_args()

    setup_django()
    cases = load_cases(args.dataset or None)
    targets = list(DEFAULT_MODEL_TARGETS)

    if args.include_vllm:
        targets.append(
            ModelTarget(
                key="vllm-local",
                label="vLLM Local",
                provider="vllm",
                env_overrides={},
                price_in_rub_per_1k=None,
                price_out_rub_per_1k=None,
                price_note="local GPU cost model; calculate separately",
            )
        )

    selected_targets = [x.strip() for x in (args.targets or "").split(",") if x.strip()]
    if selected_targets:
        targets_by_key = {target.key: target for target in targets}
        unknown = sorted(set(selected_targets) - set(targets_by_key))
        if unknown:
            raise ValueError(
                "Unknown target keys: {unknown}. Available: {available}".format(
                    unknown=", ".join(unknown),
                    available=", ".join(sorted(targets_by_key)),
                )
            )
        targets = [targets_by_key[key] for key in selected_targets]

    all_results: list[dict[str, Any]] = []
    for target in targets:
        print(f"[benchmark] target={target.key} provider={target.provider}")
        try:
            result = evaluate_target(target, cases)
            all_results.append(result)
            print(
                "[done] model={model} success={success:.2%} missing={missing:.2%} p95_ms={p95:.2f} errors={errors}".format(
                    model=result["runtime_model_name"],
                    success=result["parse_success_rate"],
                    missing=result["missing_fields_rate"],
                    p95=result["latency_ms_p95"],
                    errors=result["errors"],
                )
            )
            print(
                "[done+] adjusted_success={adjusted:.2%} unexpected_missing={unexpected:.2%}".format(
                    adjusted=result["adjusted_success_rate"],
                    unexpected=result["unexpected_missing_rate"],
                )
            )
        except Exception as exc:
            all_results.append(
                {
                    "target_key": target.key,
                    "target_label": target.label,
                    "provider": target.provider,
                    "runtime_model_name": "",
                    "total_cases": len(cases),
                    "errors": len(cases),
                    "parse_success_rate": 0.0,
                    "adjusted_success_rate": 0.0,
                    "missing_fields_rate": 0.0,
                    "unexpected_missing_rate": 0.0,
                    "avg_missing_fields": 0.0,
                    "items_presence_rate": 0.0,
                    "phone_presence_rate": 0.0,
                    "address_presence_rate": 0.0,
                    "latency_ms_p95": 0.0,
                    "latency_ms_avg": 0.0,
                    "price_in_rub_per_1k": target.price_in_rub_per_1k,
                    "price_out_rub_per_1k": target.price_out_rub_per_1k,
                    "price_note": target.price_note,
                    "cases": [],
                    "fatal_error": f"{type(exc).__name__}: {exc}",
                }
            )
            print(f"[error] target={target.key} fatal={type(exc).__name__}: {exc}")

    payload = {
        "generated_at_epoch": int(time.time()),
        "cases_count": len(cases),
        "targets_count": len(targets),
        "results": all_results,
    }

    out_json = Path(args.output_json)
    out_md = Path(args.output_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    out_md.write_text(to_markdown(all_results, len(cases)), encoding="utf-8")

    print(f"[saved] {out_json}")
    print(f"[saved] {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
