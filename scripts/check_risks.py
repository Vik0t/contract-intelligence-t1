"""Acceptance cases for the first catalog review; synthetic, not independent gold.

Explicit --backend api permits sending only these synthetic examples externally.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import time
from scripts.ml_check import TEXT


def cases():
    capped = TEXT.replace('без ограничения общей суммы', 'с учётом общих ограничений ответственности')
    capped = capped.replace('Поставщик вправе в одностороннем порядке увеличить цену без ограничения размера повышения и без согласия Покупателя.', 'Цена изменяется только по письменному соглашению обеих сторон.')
    capped = 'PAGE 1\n' + capped + '\nPAGE 2\n' + 'Доставка осуществляется по согласованному адресу. ' * 30 + '\nPAGE 9\nОбщая ответственность Покупателя по договору, включая все неустойки, ограничена 10% цены договора; исключений нет.'
    services = 'PAGE 1\nДоговор возмездного оказания услуг между ООО «Альфа» (Исполнитель) и ООО «Бета» (Заказчик). Консультационные услуги по праву РФ. Исполнитель вправе отказаться от оказания услуг в любое время без возмещения убытков Заказчика. Заказчик вправе отказаться от договора при оплате фактически оказанных услуг и подтверждённых фактических расходов Исполнителя.'
    provider = 'PAGE 1\nДоговор оказания консультационных услуг между ООО «Альфа» (Исполнитель) и ООО «Бета» (Заказчик). Оплата Исполнителю производится исключительно после получения Заказчиком финансирования от третьего лица. Предельный срок оплаты отсутствует. Исполнитель не вправе требовать оплаты до получения такого финансирования.'
    return [
        ('supply_customer', 'supply', 'customer', 'PAGE 1\n' + TEXT, {'price_change', 'uncapped_penalty'}, set()),
        ('supply_provider', 'supply', 'provider', 'PAGE 1\n' + TEXT, set(), {'price_change', 'uncapped_penalty'}),
        ('supply_global_cap', 'supply', 'customer', capped, set(), {'uncapped_penalty', 'price_change'}),
        ('services_customer', 'services', 'customer', services, {'services_provider_exit'}, {'services_customer_exit'}),
        ('services_provider', 'services', 'provider', provider, {'payment_dependency'}, set()),
        ('neutral', 'supply', 'customer', 'PAGE 1\nДоговор поставки между двумя организациями по праву РФ. Поставка по согласованной спецификации. Изменения только по письменному соглашению обеих сторон. Ответственность определяется законодательством Российской Федерации.', set(), None),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=['local', 'api'], default='local')
    parser.add_argument('--output', type=Path, default=Path('tmp/risk-check.json'))
    parser.add_argument('--case', action='append', help='Only the selected synthetic cases')
    args = parser.parse_args()
    os.environ.update(ML_ALLOW_EXTERNAL='true' if args.backend == 'api' else 'false', RISK_BACKEND=args.backend)
    from src.extraction.risk_review import review_contract_risks
    report = {'kind': 'synthetic_catalog_acceptance', 'backend': args.backend, 'records': [], 'passed': False, 'limitations': 'Synthetic development cases; legal expert gold and real GPU validation remain necessary.'}
    for name, kind, side, text, required, forbidden in cases():
        if args.case and name not in args.case:
            continue
        started = time.monotonic()
        record = {'case': name, 'passed': False}
        try:
            result = review_contract_risks(text, {}, {'contract_type': kind, 'user_side': side, 'scope_confirmed': True})
            found = {item['rule_id'] for item in result['findings']}
            assert required <= found, f'Missing checks: {required - found}'
            assert not (found & forbidden) if forbidden is not None else not found, f'Unexpected findings: {found}'
            if name == 'supply_global_cap':
                check = next(item for item in result['checks'] if item['rule_id'] == 'uncapped_penalty')
                assert check['status'] == 'mitigated', 'General liability cap must mitigate penalty'
                assert any(item['page'] == 9 for item in check['evidence'] + check['related_clauses'])
            record.update(passed=True, report=result)
        except Exception as exc:
            record.update(error_type=type(exc).__name__)
            if isinstance(exc, AssertionError):
                record['error'] = str(exc)
        record['elapsed_sec'] = round(time.monotonic() - started, 2)
        report['records'].append(record)
        report['passed'] = bool(report['records']) and all(item['passed'] for item in report['records'])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({key: value for key, value in record.items() if key != 'report'}, ensure_ascii=False), flush=True)
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
