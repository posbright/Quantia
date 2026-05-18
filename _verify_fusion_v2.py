"""Quick black-box smoke for /quantia/api/verify/fusion v2.

Run after web_service restart to verify Stage 1-3 wiring:
- 5-dim payload accepted across 4 modes
- Stage 3 real Shapley / AB / Overlap fields populated
- Whitelist validation rejects bad fund/flow items

Use 2026-03-01 ~ 2026-05-14 (system clock is in 2026; 2025 ranges return empty).
"""
import json
import urllib.request
import urllib.error

URL = 'http://localhost:9988/quantia/api/verify/fusion'


def _post(body):
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode('utf-8'),
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.getcode(), json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _payload(mode, **overrides):
    base = {
        'version': 2,
        'mode': mode,
        'start_date': '2026-03-01',
        'end_date': '2026-05-14',
        'holding_days': 10,
        'min_score': 0.4,
        'vote_threshold': 2,
        'dimensions': {
            'tech': {'enabled': True, 'weight': 40,
                     'items': ['cn_stock_strategy_keep_increasing',
                               'cn_stock_strategy_breakthrough_platform']},
            'fund': {'enabled': True, 'weight': 30,
                     'items': ['pe9_lt_30', 'roe_weight_gte_10']},
            'flow': {'enabled': True, 'weight': 30,
                     'items': ['fund_amount_gt_0']},
            'sent': {'enabled': False, 'weight': 0, 'items': []},
            'custom': {'enabled': False, 'weight': 0, 'items': []},
        },
    }
    base.update(overrides)
    return base


def main():
    failures = []

    # Case 1: weighted_score 3-dim → must populate Shapley/AB/Overlap
    code, data = _post(_payload('weighted_score'))
    assert code == 200, f'weighted_score returned {code}: {data}'
    sh = data.get('shapley') or []
    ab = data.get('ab_steps') or []
    ov = data.get('overlap') or {}
    print(f'[1] weighted_score: sig={data["fusion_result"]["signal_count"]} '
          f'sharpe={data["fusion_result"]["sharpe"]}')
    print(f'    shapley={len(sh)} items, ab_steps={len(ab)} steps, '
          f'overlap.calendar={len(ov.get("calendar", []))} days, '
          f'overlap.co_occurrence={len(ov.get("co_occurrence", []))} pairs')
    if len(sh) != 3:
        failures.append(f'Expected 3 Shapley items, got {len(sh)}')
    if len(ab) != 3:
        failures.append(f'Expected 3 AB steps, got {len(ab)}')
    if len(ov.get('co_occurrence', [])) != 9:
        failures.append(f'Expected 9 co_occurrence pairs (3×3), got '
                        f'{len(ov.get("co_occurrence", []))}')
    # Shapley sum invariant (≈ v(N) = fusion sharpe within tolerance)
    fusion_sharpe = data['fusion_result']['sharpe']
    s_sum = sum((it.get('contrib') or 0.0) for it in sh)
    print(f'    Σ Shapley={s_sum:.4f}  v(N)={fusion_sharpe:.4f}  '
          f'diff={abs(s_sum - fusion_sharpe):.4f}')
    if abs(s_sum - fusion_sharpe) > 1e-3:
        failures.append(f'Shapley sum {s_sum} ≠ v(N) {fusion_sharpe}')

    # Case 2: vote mode threshold=2
    code, data = _post(_payload('vote', vote_threshold=2))
    assert code == 200, data
    print(f'[2] vote (threshold=2): sig={data["fusion_result"]["signal_count"]} '
          f'sharpe={data["fusion_result"]["sharpe"]}')

    # Case 3: condition_tree (intersection of all enabled dims)
    code, data = _post(_payload('condition_tree'))
    assert code == 200, data
    print(f'[3] condition_tree: sig={data["fusion_result"]["signal_count"]} '
          f'sharpe={data["fusion_result"]["sharpe"]}')

    # Case 4: rotation falls back to weighted_score with warning
    code, data = _post(_payload('rotation'))
    assert code == 200, data
    warns = data.get('warnings') or []
    print(f'[4] rotation: sig={data["fusion_result"]["signal_count"]} '
          f'warnings={len(warns)}')
    if not any('rotation' in w for w in warns):
        failures.append('rotation mode should emit fallback warning')

    # Case 5: whitelist tolerates bad fund expr (silently skip with warning;
    # if all dim items become invalid the dim is dropped from enabled_dims).
    bad = _payload('weighted_score')
    bad['dimensions']['fund']['items'] = ['no_such_col_lt_5']
    code, data = _post(bad)
    warns = data.get('warnings') or []
    enabled = (data.get('diagnostics') or {}).get('enabled_dims', [])
    print(f'[5] bad fund item → HTTP {code}, fund warned={any("基本面" in w for w in warns)}, '
          f'enabled_dims={enabled}')
    if code != 200:
        failures.append(f'Bad fund item should soft-degrade to 200, got {code}')
    if 'fund' in enabled:
        failures.append('fund should be dropped from enabled_dims when all items invalid')

    # Case 6: no enabled dim → 400
    empty = _payload('weighted_score')
    for k in empty['dimensions']:
        empty['dimensions'][k]['enabled'] = False
    code, data = _post(empty)
    print(f'[6] no enabled dim → HTTP {code}: {data.get("error", "")[:80]}')
    if code != 400:
        failures.append(f'No enabled dim should 400, got {code}')

    print()
    if failures:
        print(f'[FAIL] {len(failures)} issue(s):')
        for f in failures:
            print(f'  - {f}')
        raise SystemExit(1)
    print('[OK] All fusion v2 smoke checks passed.')


if __name__ == '__main__':
    main()
