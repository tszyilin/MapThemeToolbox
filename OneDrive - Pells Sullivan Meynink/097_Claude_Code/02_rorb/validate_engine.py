"""
RORB engine validation — compares Python routing engine vs RORB app outputs.
"""
import re, csv
import numpy as np
from pathlib import Path

BASE    = Path(r'C:\Users\safin.lin\OneDrive - Pells Sullivan Meynink\097_Claude_Code\02_rorb\example_input')
CATG    = BASE / 'PSM6036_Goodwood.catg'
IFD_CSV = BASE / 'IFD_depths_Bundaberg_all_design.csv'
RESULTS = BASE / '01_Hairsine'

# ── Non-linear storage routing ────────────────────────────────────────────────

def route(inflow, kc, kr, m, dt):
    """Non-linear storage routing.
    RORB convention: first step uses I1=inflow[0] (storm already at full intensity),
    Q1=0 (dry initial condition).
    """
    k = kc * kr
    n = len(inflow)
    Q = np.zeros(n)

    def bisect(rhs, hi_bound):
        lo, hi = 0.0, hi_bound
        for _ in range(64):
            mid = (lo + hi) / 2.0
            if k * mid**m + mid * dt / 2.0 < rhs:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0

    # First step: dry start (no rainfall before t=0), so I_prev=0, I_curr=inflow[0].
    # Using (0 + I[0])*dt/2 prevents amplification when inflow[0] is large.
    I2 = inflow[0]
    rhs = I2 * dt / 2.0
    Q[0] = bisect(rhs, max(I2, 0.0) * 4.0 + 1.0)

    for t in range(1, n):
        I1, I2, Q1 = inflow[t-1], inflow[t], Q[t-1]
        rhs = (I1 + I2) * dt / 2.0 - Q1 * dt / 2.0 + k * (max(Q1, 0.0) ** m)
        Q[t] = bisect(rhs, max(I1, I2, Q1) * 4.0 + 1.0)

    return Q

def apply_loss(rain_mm, il, cl, dt):
    """IL/CL loss model.
    On the step where IL is first satisfied, only the rain AFTER IL is used for excess.
    """
    excess = np.zeros(len(rain_mm))
    cum = 0.0
    il_satisfied = False
    for i, r in enumerate(rain_mm):
        if il_satisfied:
            excess[i] = max(0.0, r - cl * dt)
        else:
            cum += r
            if cum >= il:
                il_satisfied = True
                rain_after_il = cum - il   # only this portion is available
                excess[i] = max(0.0, rain_after_il - cl * dt)
    return excess

def to_m3s(excess_mm, area_km2, dt_hr):
    return excess_mm * area_km2 * 1e6 / 1e3 / (dt_hr * 3600.0)

# ── Parse .catg ───────────────────────────────────────────────────────────────

def parse_catg(path):
    lines = Path(path).read_text(errors='replace').splitlines()

    # Sub-area areas (after 'C Sub Area Data')
    areas = []
    in_area = False
    for line in lines:
        if 'C Sub Area Data' in line:
            in_area = True
            continue
        if in_area:
            if line.strip().startswith('C'):
                continue
            if '-99' in line:
                nums = re.findall(r'[\d.]+', line.split('-99')[0])
                areas += [float(x) for x in nums]
                break
            nums = re.findall(r'[\d.]+', line)
            areas += [float(x) for x in nums]

    # Vector block: skip graphical C-lines, then skip the type flag '1',
    # collect lines until standalone '0'
    vector = []
    past_graphical = False
    skip_next_flag = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('C END RORB_GE'):
            past_graphical = True
            skip_next_flag = True
            continue
        if not past_graphical:
            continue
        if skip_next_flag and stripped == '1':
            skip_next_flag = False
            continue
        vector.append(stripped)

    return areas, vector

# ── Parse .stm ────────────────────────────────────────────────────────────────

def parse_stm(stm_path):
    """Extract high-precision rainfall from .stm storm file.
    Returns (dt, rain_ts) where rain_ts is per-step mm values.
    """
    txt = Path(stm_path).read_text(errors='replace')

    # dt from first non-comment data line: "0.08333,200, 1, ..."
    dt_m = re.search(r'^\s*([\d.]+),\s*\d+', txt, re.MULTILINE)
    dt = float(dt_m.group(1)) if dt_m else None

    # Catchment depth (ARF*BurDepth)
    depth_m = re.search(r'ARF\*BurDepth\(mm\)\s*:\s*([\d.]+)', txt)
    depth = float(depth_m.group(1)) if depth_m else None

    # Temporal pattern percentages — use the data-section label, not the comment header
    pct_m = re.search(r'Temporal pattern \(% of depth\)\s*\n([\s\S]+?)(?:\nC |\n -99)', txt)
    pct = []
    if pct_m:
        for v in re.findall(r'-?[\d.]+', pct_m.group(1)):
            val = float(v)
            if val < 0:   # -99 sentinel
                break
            pct.append(val)

    if not depth or not pct or not dt:
        return None, None

    rain_ts = [depth * p / 100.0 for p in pct]
    return dt, rain_ts


# ── Parse .out ────────────────────────────────────────────────────────────────

def parse_out(path):
    txt = Path(path).read_text(errors='replace')

    kc = float(re.search(r'kc\s*=\s*([\d.]+)', txt).group(1))
    m  = float(re.search(r'm\s*=\s*([\d.]+)', txt).group(1))
    # IL and CL are on the line BELOW the header, in column order
    loss_m = re.search(
        r'Initial loss \(mm\)\s+Cont\. loss \(mm/h\)\s+([\d.]+)\s+([\d.]+)', txt)
    il = float(loss_m.group(1))
    cl = float(loss_m.group(2))
    dt = float(re.search(r'Time increment.*?=\s*([\d.]+)\s+hours', txt).group(1))

    # Parse actual catchment rainfall series directly from the .out file
    # (includes pre-burst + burst, with ARF already applied)
    rain_section = re.search(r'Rainfall, mm.*?(?=Rainfall-excess)', txt, re.DOTALL)
    rain_ts = []
    if rain_section:
        for line in rain_section.group(0).splitlines():
            nums = re.findall(r'[\d.]+', line)
            if len(nums) >= 2 and nums[0].isdigit():
                rain_ts.append(float(nums[1]))  # catchment average column
    total_depth = sum(rain_ts) if rain_ts else None
    pct = None  # not used when rain_ts is available

    # kr values from storage table
    kr_list = [float(x) for x in re.findall(
        r'^\s*\d+\s+[\d.]+\s+([\d.]+)\s+Natural', txt, re.MULTILINE)]

    # Peak flows — handle m³/s encoding issues
    peaks = {}
    node = None
    for line in txt.splitlines():
        m_node = re.search(r'\*\*\* Calculated hydrograph,\s+(.+)', line)
        if m_node:
            node = m_node.group(1).strip()
        if node and 'Peak discharge' in line:
            nums = re.findall(r'[\d.]+', line)
            if nums:
                peaks[node] = float(nums[-1])
            node = None

    return kc, m, il, cl, dt, rain_ts, kr_list, peaks, total_depth

# ── Parse IFD CSV ─────────────────────────────────────────────────────────────

def parse_ifd(path):
    ifd = {}
    with open(path) as f:
        lines = f.readlines()
    hi = next(i for i, l in enumerate(lines) if 'Duration in min' in l)
    header = [h.strip() for h in lines[hi].split(',')]
    aep_cols = header[2:]
    for line in lines[hi+1:]:
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 3:
            continue
        dur = parts[0]
        for j, aep in enumerate(aep_cols):
            try:
                ifd[(dur, aep)] = float(parts[j+2])
            except (ValueError, IndexError):
                pass
    return ifd

DUR_MAP = {
    '10min': '10 min', '15min': '15 min', '20min': '20 min', '25min': '25 min',
    '30min': '30 min', '45min': '45 min',
    '1hour': '1 hour', '1_5hour': '1.5 hour', '2hour': '2 hour',
    '3hour': '3 hour', '4_5hour': '4.5 hour', '6hour': '6 hour',
    '9hour': '9 hour', '12hour': '12 hour', '18hour': '18 hour',
    '24hour': '24 hour', '30hour': '30 hour', '36hour': '36 hour',
    '48hour': '48 hour', '72hour': '72 hour', '96hour': '96 hour',
    '120hour': '120 hour', '144hour': '144 hour', '168hour': '168 hour',
}
AEP_MAP = {
    'aep63p2': '63.2%', 'aep50': '50%',   'aep20': '20%',  'aep10': '10%',
    'aep5': '5%',       'aep2': '2%',      'aep1': '1%',
    'aep0p5EY': '0.5EY', 'aep0p2EY': '0.2EY',
}

def parse_filename(stem):
    m = re.search(r' (aep[^_]+)_du([^t]+)(tp\d+)', stem)
    if not m:
        return None, None, None
    return AEP_MAP.get(m.group(1)), DUR_MAP.get(m.group(2)), int(m.group(3)[2:])

# ── Run routing sequence ──────────────────────────────────────────────────────

def run_event(vector, areas_km2, kr_list, kc, m_exp, dt, rain_mm, il, cl):
    n      = len(rain_mm)
    excess = apply_loss(rain_mm, il, cl, dt)
    sa_in  = [to_m3s(excess, a, dt) for a in areas_km2]

    hydro    = np.zeros(n)
    stack    = []
    results  = {}
    si, ki   = 0, 0      # sub-area index, storage index
    next_print_name = None

    for line in vector:
        if not line:
            continue

        # After a print code, next non-code line is the node name
        if next_print_name == 'PENDING':
            if not re.match(r'^\d', line):
                results[line.strip()] = hydro.copy()   # store full hydrograph
                next_print_name = None
                continue
            next_print_name = None

        code_m = re.match(r'^(\d+)', line)
        if not code_m:
            continue
        code = int(code_m.group(1))

        def get_sa():
            nonlocal si
            inflow = sa_in[si] if si < len(sa_in) else np.zeros(n)
            si += 1
            return inflow

        def get_kr():
            nonlocal ki
            kr = kr_list[ki] if ki < len(kr_list) else 0.1
            ki += 1
            return kr

        if code == 0:
            break
        elif code == 1:
            hydro = route(get_sa(), kc, get_kr(), m_exp, dt)
        elif code == 2:
            hydro = route(hydro + get_sa(), kc, get_kr(), m_exp, dt)
        elif code == 3:
            stack.append(hydro.copy())
            hydro = np.zeros(n)
        elif code == 4:
            hydro = hydro + (stack.pop() if stack else np.zeros(n))
        elif code == 5:
            hydro = route(hydro, kc, get_kr(), m_exp, dt)
        elif code == 7:
            next_print_name = 'PENDING'

    return results

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print('Parsing .catg ...')
    areas, vector = parse_catg(CATG)
    print(f'  Sub-areas: {len(areas)}  {[round(a,2) for a in areas]}')
    print(f'  Vector lines: {len(vector)}')

    print('Parsing IFD ...')
    ifd = parse_ifd(IFD_CSV)

    out_files = sorted(RESULTS.glob('*.out'))
    print(f'Found {len(out_files)} result files')

    table = []
    checked = 0

    for out_path in out_files:
        aep_key, dur_key, tp = parse_filename(out_path.stem)
        if not aep_key or not dur_key:
            continue
        pass  # run all temporal patterns

        try:
            kc, m_exp, il, cl, dt, rain_ts, kr_list, rorb_peaks, total_depth = parse_out(out_path)
        except Exception as e:
            continue

        if not rain_ts or not kr_list:
            continue

        # Use high-precision rainfall from .stm if available
        stm_path = out_path.with_suffix('.stm')
        if stm_path.exists():
            stm_dt, stm_rain = parse_stm(stm_path)
            if stm_rain and stm_dt:
                rain_ts = stm_rain
                dt = stm_dt

        rain_storm = rain_ts
        # Match RORB's 200-increment simulation length (like RORB's Duration of calculations)
        n_steps    = max(len(rain_storm) * 4, 200)   # RORB uses 200 time increments minimum
        rain_pad   = rain_storm + [0.0] * (n_steps - len(rain_storm))

        our = run_event(vector, areas, kr_list, kc, m_exp, dt, rain_pad, il, cl)

        for node, rorb_q in rorb_peaks.items():
            our_hydro = our.get(node, None)
            if our_hydro is None:
                continue
            our_q = float(np.max(our_hydro))
            diff = (our_q - rorb_q) / rorb_q * 100 if rorb_q > 0.01 else 0.0
            table.append({
                'AEP': aep_key, 'Duration': dur_key, 'TP': tp,
                'Node': node,
                'RORB': round(rorb_q, 3),
                'Ours': round(our_q, 3),
                'Diff%': round(diff, 1),
            })
        checked += 1

    # ── Print summary ─────────────────────────────────────────────────────────
    print(f'\n{"="*88}')
    print(f'VALIDATION  ({checked} events, all TPs)')
    print(f'{"="*88}')
    print(f'{"AEP":<10} {"Duration":<12} {"Node":<22} {"RORB (m³/s)":>12} {"Ours (m³/s)":>12} {"Diff%":>7}')
    print('-'*88)

    outlet = [r for r in table if 'Total Outlet' in r['Node'] or 'outlet' in r['Node'].lower()]
    for r in outlet:
        flag = '  ***' if abs(r['Diff%']) > 5 else ''
        print(f"{r['AEP']:<10} {r['Duration']:<12} {r['Node']:<22} "
              f"{r['RORB']:>12.3f} {r['Ours']:>12.3f} {r['Diff%']:>6.1f}%{flag}")

    nz = [r for r in outlet if r['RORB'] > 0.01]
    if nz:
        diffs = [abs(r['Diff%']) for r in nz]
        print(f'\nNon-zero events : {len(nz)}')
        print(f'Mean |diff|     : {np.mean(diffs):.1f}%')
        print(f'Max  |diff|     : {np.max(diffs):.1f}%')
        print(f'Within ±5%      : {sum(1 for d in diffs if d<=5)}/{len(nz)}')

    if table:
        out_csv = BASE / 'validation_results.csv'
        with open(out_csv, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=table[0].keys())
            w.writeheader(); w.writerows(table)
        print(f'\nSaved: {out_csv}')

if __name__ == '__main__':
    main()
