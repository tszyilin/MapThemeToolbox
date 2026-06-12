"""
Standalone test of the QGIS plugin's core engine and storm parsers.
No QGIS required — tests pure-Python modules only.

Tests:
  1. storm.py  — parse ARR TXT, IFD CSV, temporal pattern CSV
  2. engine.py — run_from_files() matches RORB output
  3. Integration — storm setup -> engine matches known peaks
"""
import sys
import numpy as np
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT    = Path(__file__).parent
PLUGIN  = ROOT / 'QGIS_RORB' / 'rorb_qgis'
INPUTS  = ROOT / 'example_input'
HAIRSINE = INPUTS / '01_Hairsine'

sys.path.insert(0, str(PLUGIN.parent))   # so 'rorb_qgis.core.xxx' resolves
sys.path.insert(0, str(PLUGIN.parent.parent))

# Import core modules directly (no QGIS dependency)
from rorb_qgis.core.storm  import (parse_arr_txt, parse_ifd_csv,
                                     parse_temporal_patterns,
                                     get_ifd_depth, get_temporal_pattern,
                                     aep_to_band, build_rainfall_series)
from rorb_qgis.core.engine import (run_from_files, parse_rorb_csv,
                                     parse_catg, parse_out, parse_stm)

CATG = INPUTS / 'PSM6036_Goodwood.catg'
ARR  = INPUTS / 'Goodwood.txt'
IFD  = INPUTS / 'IFD_depths_Bundaberg_all_design.csv'
TP   = INPUTS / 'ECnorth_Increments.csv'

PASS = 0; FAIL = 0

def check(name, got, expected, tol=0.05):
    global PASS, FAIL
    ok = abs(got - expected) / max(abs(expected), 1e-9) <= tol
    symbol = 'PASS' if ok else 'FAIL'
    if ok: PASS += 1
    else:  FAIL += 1
    print(f"  [{symbol}]  {name}")
    if not ok:
        print(f"         got={got:.4f}  expected={expected:.4f}  "
              f"diff={abs(got-expected)/max(abs(expected),1e-9)*100:.1f}%")

def check_eq(name, got, expected):
    global PASS, FAIL
    ok = got == expected
    symbol = 'PASS' if ok else 'FAIL'
    if ok: PASS += 1
    else:  FAIL += 1
    print(f"  [{symbol}]  {name}")
    if not ok:
        print(f"         got={got!r}  expected={expected!r}")


# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("TEST 1: storm.py — ARR TXT parser")
print("="*70)

arr = parse_arr_txt(ARR)
check_eq("IL parsed",             arr['il'],  40.0)
check_eq("CL parsed",             arr['cl'],   3.2)
check_eq("LONGARF zone",          arr['longarf'].get('zone'), 'East Coast North')
check   ("LONGARF param a",       arr['longarf'].get('a', 0), 0.327, tol=0.001)


# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("TEST 2: storm.py — IFD CSV parser")
print("="*70)

aeps, rows, meta = parse_ifd_csv(IFD)
print(f"  Location: {meta.get('location')}  lat={meta.get('lat')}  lon={meta.get('lon')}")
print(f"  {len(rows)} durations  x  {len(aeps)} AEPs")

# 10 min, 63.2% AEP → burst depth from CSV (row shows 18.5 mm)
d_10m_63 = get_ifd_depth(rows, '63.2%', 10)
check("10 min / 63.2% burst depth", d_10m_63, 18.5, tol=0.02)

# 1 hour, 1% AEP
d_1h_1 = get_ifd_depth(rows, '1%', 60)
print(f"  1 hour / 1% burst depth = {d_1h_1:.1f} mm")


# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("TEST 3: storm.py — Temporal pattern parser")
print("="*70)

patterns = parse_temporal_patterns(TP)
print(f"  {len(patterns)} patterns loaded")

# 10 min, frequent, TP1 → should be [53.95, 46.05] (from .stm file)
incs_10m_tp1, dt_min = get_temporal_pattern(patterns, 10, 'frequent', 1)
if incs_10m_tp1:
    check("10 min TP1 step 1 %",  incs_10m_tp1[0], 53.95, tol=0.01)
    check("10 min TP1 step 2 %",  incs_10m_tp1[1], 46.05, tol=0.01)
    check("10 min TP1 sum = 100", sum(incs_10m_tp1), 100.0, tol=0.001)
    check_eq("10 min TP1 timestep = 5 min", dt_min, 5)
else:
    FAIL += 1
    print("  [FAIL]  10 min / frequent / TP1 not found")

# AEP band mapping
check_eq("63.2% -> frequent",    aep_to_band('63.2%'),    'frequent')
check_eq("20%   -> intermediate", aep_to_band('20%'),      'intermediate')
check_eq("1%    -> rare",         aep_to_band('1%'),        'rare')


# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("TEST 4: storm.py — Rainfall series matches .stm file")
print("="*70)
# For 10 min, 63.2% AEP, TP1 ARF=0.77 (from the .stm file header)
# .stm says: ARF*BurDepth = 14.19 mm, pattern = [53.95, 46.05]
# Our calc:  burst = 18.5 mm, ARF = 0.77, depth = 18.5*0.77 = 14.245 mm

ARF_10m = 0.77   # from .stm file
rain_ts = build_rainfall_series(d_10m_63, ARF_10m, incs_10m_tp1)
check("Catchment depth (burst x ARF)", sum(rain_ts), 14.19, tol=0.02)
check("Step 1 rainfall",  rain_ts[0], 14.19 * 0.5395, tol=0.02)
check("Step 2 rainfall",  rain_ts[1], 14.19 * 0.4605, tol=0.02)


# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("TEST 5: engine.py — run_from_files() vs RORB peaks")
print("="*70)
# Test a representative selection of events
test_events = [
    ('aep63p2', 'du10min', 'tp1'),
    ('aep63p2', 'du168hour', 'tp1'),
    ('aep1',    'du24hour',  'tp5'),
    ('aep20',   'du6hour',   'tp3'),
]

for aep_key, dur_key, tp_key in test_events:
    stem     = f'PSM6036_Goodwood_ {aep_key}_{dur_key}{tp_key}'
    out_path = HAIRSINE / f'{stem}.out'
    stm_path = HAIRSINE / f'{stem}.stm'
    csv_path = HAIRSINE / f'{stem}.csv'
    if not out_path.exists():
        print(f"  [SKIP]  {stem} (.out not found)")
        continue
    try:
        res    = run_from_files(str(CATG), str(out_path),
                                str(stm_path) if stm_path.exists() else None)
        hydros = res['hydros']
        peaks  = res['rorb_peaks']
        label  = f"{aep_key}/{dur_key}/{tp_key}"
        print(f"\n  Event: {label}")
        for node, rorb_q in sorted(peaks.items()):
            eng_q = float(np.max(hydros.get(node, [0])))
            diff  = abs(eng_q - rorb_q) / max(rorb_q, 0.01) * 100
            symbol = 'PASS' if diff <= 2.0 else ('WARN' if diff <= 5.0 else 'FAIL')
            if symbol == 'PASS': PASS += 1
            elif symbol == 'FAIL': FAIL += 1
            print(f"    [{symbol}]  {node:<22} "
                  f"Engine={eng_q:7.3f}  RORB={rorb_q:7.3f}  diff={diff:.1f}%")
    except Exception as e:
        FAIL += 1
        print(f"  [FAIL]  {stem}: {e}")


# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("TEST 6: Integration — storm parser -> engine -> compare to RORB")
print("="*70)
# Use storm.py to build the same rainfall that .stm has, then run engine,
# and check the peak matches the .out file.

stem     = 'PSM6036_Goodwood_ aep63p2_du10mintp1'
out_path = HAIRSINE / f'{stem}.out'
csv_path = HAIRSINE / f'{stem}.csv'

if out_path.exists():
    # Parse RORB params from .out
    kc, m, il, cl, dt, rain_ts_out, kr_list, rorb_peaks, _ = parse_out(str(out_path))

    # Build storm using storm.py instead of .stm file
    incs, dt_min = get_temporal_pattern(patterns, 10, 'frequent', 1)
    rain_storm = build_rainfall_series(d_10m_63, ARF_10m, incs)
    dt_hr = dt_min / 60.0

    # Run engine
    areas, vector = parse_catg(str(CATG))
    from rorb_qgis.core.engine import run_event
    n_steps  = max(len(rain_storm) * 4, 200)
    rain_pad = rain_storm + [0.0] * (n_steps - len(rain_storm))
    hydros, _ = run_event(vector, areas, kr_list, kc, m, dt_hr, rain_pad, il, cl)

    print(f"  Storm parser depth: {sum(rain_storm):.2f} mm  "
          f"(dt={dt_hr:.4f} hr, steps={len(rain_storm)})")
    for node, rorb_q in sorted(rorb_peaks.items()):
        eng_q = float(np.max(hydros.get(node, [0])))
        diff  = abs(eng_q - rorb_q) / max(rorb_q, 0.01) * 100
        symbol = 'PASS' if diff <= 5.0 else 'FAIL'
        if symbol == 'PASS': PASS += 1
        else: FAIL += 1
        print(f"  [{symbol}]  {node:<22} "
              f"Engine={eng_q:7.3f}  RORB={rorb_q:7.3f}  diff={diff:.1f}%")
else:
    print("  [SKIP]  .out file not found")


# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print(f"SUMMARY:  {PASS} passed,  {FAIL} failed")
print("="*70)
if FAIL == 0:
    print("All tests passed.")
else:
    print(f"{FAIL} test(s) failed — see details above.")
