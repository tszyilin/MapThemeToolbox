"""
Validate the full hydrograph time series against RORB CSV outputs.
Checks: peak flow, time to peak, hydrograph shape (RMSE, Nash-Sutcliffe).
"""
import re, csv, numpy as np
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from validate_engine import (
    parse_catg, parse_out, parse_stm, run_event,
    CATG, RESULTS
)

# ── Parse RORB hydrograph CSV ─────────────────────────────────────────────────

def parse_csv(csv_path):
    """Returns dict: {node_name: np.array of flows}"""
    result = {}
    with open(csv_path, errors='replace') as f:
        lines = f.readlines()
    # Find header row
    hi = next((i for i, l in enumerate(lines) if 'Time (hrs)' in l), None)
    if hi is None:
        return result
    header = [h.strip() for h in lines[hi].split(',')]
    nodes = header[2:]  # skip Inc, Time(hrs)
    arrays = [[] for _ in nodes]
    for line in lines[hi+1:]:
        parts = line.split(',')
        if len(parts) < len(header):
            continue
        try:
            for j, a in enumerate(arrays):
                a.append(float(parts[j+2]))
        except (ValueError, IndexError):
            break
    for j, node in enumerate(nodes):
        name = node.replace('Calculated hydrograph:', '').strip()
        result[name] = np.array(arrays[j])
    return result

# ── Nash-Sutcliffe Efficiency ─────────────────────────────────────────────────

def nse(obs, sim):
    obs, sim = np.array(obs), np.array(sim)
    n = min(len(obs), len(sim))
    obs, sim = obs[:n], sim[:n]
    denom = np.sum((obs - obs.mean())**2)
    if denom < 1e-12:
        return 1.0 if np.sum((obs - sim)**2) < 1e-10 else np.nan
    return 1 - np.sum((obs - sim)**2) / denom

def rmse(obs, sim):
    n = min(len(obs), len(sim))
    return float(np.sqrt(np.mean((obs[:n] - sim[:n])**2)))

def pbias(obs, sim):
    n = min(len(obs), len(sim))
    obs, sim = obs[:n], sim[:n]
    return float((sim.sum() - obs.sum()) / obs.sum() * 100) if obs.sum() > 0 else 0.0

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print('Parsing .catg ...')
    areas, vector = parse_catg(CATG)

    AEP_MAP = {'aep63p2':'63.2%','aep50':'50%','aep20':'20%','aep10':'10%',
               'aep5':'5%','aep2':'2%','aep1':'1%','aep0p5EY':'0.5EY','aep0p2EY':'0.2EY'}
    DUR_MAP  = {'10min':'10 min','15min':'15 min','20min':'20 min','25min':'25 min',
                '30min':'30 min','45min':'45 min','1hour':'1 hour','1_5hour':'1.5 hour',
                '2hour':'2 hour','3hour':'3 hour','4_5hour':'4.5 hour','6hour':'6 hour',
                '9hour':'9 hour','12hour':'12 hour','18hour':'18 hour','24hour':'24 hour',
                '30hour':'30 hour','36hour':'36 hour','48hour':'48 hour','72hour':'72 hour',
                '96hour':'96 hour','120hour':'120 hour','144hour':'144 hour','168hour':'168 hour'}

    out_files = sorted(RESULTS.glob('*.out'))
    # Sample: first TP for each AEP/duration (one per event type)
    seen = set()
    sample = []
    for f in out_files:
        m = re.search(r' (aep[^_]+)_du([^t]+)(tp\d+)', f.stem)
        if not m:
            continue
        aep_r, dur_r = m.group(1), m.group(2)
        key = (aep_r, dur_r)
        if key in seen:
            continue
        seen.add(key)
        aep = AEP_MAP.get(aep_r)
        dur = DUR_MAP.get(dur_r)
        if aep and dur:
            sample.append(f)

    print(f'Checking {len(sample)} representative events (one TP per AEP/duration)...\n')

    stats = []
    for out_path in sample:
        csv_path = out_path.with_suffix('.csv')
        stm_path = out_path.with_suffix('.stm')
        if not csv_path.exists():
            continue

        try:
            kc, m_exp, il, cl, dt, rain_ts, kr_list, _, _ = parse_out(out_path)
            if stm_path.exists():
                stm_dt, stm_rain = parse_stm(stm_path)
                if stm_rain and stm_dt:
                    rain_ts, dt = stm_rain, stm_dt
            if not rain_ts or not kr_list:
                continue
        except Exception:
            continue

        n_steps = max(len(rain_ts) * 4, 200)
        rain_pad = rain_ts + [0.0] * (n_steps - len(rain_ts))
        our = run_event(vector, areas, kr_list, kc, m_exp, dt, rain_pad, il, cl)

        rorb_hydros = parse_csv(csv_path)

        m_name = re.search(r' (aep[^_]+)_du([^t]+)(tp\d+)', out_path.stem)
        label = f'{AEP_MAP.get(m_name.group(1),"?")} {DUR_MAP.get(m_name.group(2),"?")} {m_name.group(3)}'

        # Match each print node
        for node_name, rorb_q in rorb_hydros.items():
            if 'Total Outlet' not in node_name:
                continue
            # our hydrograph — find matching node result
            our_q = our.get(node_name)
            if our_q is None:
                # try partial match
                for k in our:
                    if node_name in k or k in node_name:
                        our_q = our[k]
                        break
            if our_q is None:
                continue

            # Engine leads RORB by 1 index: our_q[k] ≈ rorb_q[k+1].
            # Align by skipping RORB's first step and comparing rorb_q[1:] vs our_q[:-1].
            if len(rorb_q) < 2:
                continue
            n = min(len(rorb_q) - 1, len(our_q))
            if n < 2:
                continue
            obs = rorb_q[1:n + 1]   # rorb_q[k+1] at time (k+2)*dt
            sim = our_q[:n]         # our_q[k]    at time (k+2)*dt (same physical time)

            if obs.max() < 0.01:
                continue

            nse_val  = nse(obs, sim)
            rmse_val = rmse(obs, sim)
            pb       = pbias(obs, sim)
            peak_diff = (sim.max() - obs.max()) / obs.max() * 100
            # Both obs[j] and sim[j] represent the same time (j+2)*dt
            ttp_obs  = (np.argmax(obs) + 2) * dt
            ttp_sim  = (np.argmax(sim) + 2) * dt
            ttp_diff = ttp_sim - ttp_obs

            stats.append({
                'event': label, 'node': node_name,
                'NSE': nse_val, 'RMSE': rmse_val,
                'PBias%': pb, 'PeakDiff%': peak_diff,
                'TTP_obs': ttp_obs, 'TTP_sim': ttp_sim, 'TTP_diff_hr': ttp_diff,
            })

    # Summary
    nse_vals  = [s['NSE']       for s in stats if not np.isnan(s['NSE'])]
    pb_vals   = [abs(s['PBias%']) for s in stats]
    peak_vals = [abs(s['PeakDiff%']) for s in stats]
    ttp_vals  = [abs(s['TTP_diff_hr']) for s in stats]

    print(f'{"Metric":<25} {"Mean":>8} {"Median":>8} {"p95":>8} {"Max":>8}')
    print('-'*60)
    print(f'{"NSE":<25} {np.mean(nse_vals):8.4f} {np.median(nse_vals):8.4f} {np.percentile(nse_vals,5):8.4f} {np.min(nse_vals):8.4f}')
    print(f'{"RMSE (m3/s)":<25} {np.mean([s["RMSE"] for s in stats]):8.4f} {np.median([s["RMSE"] for s in stats]):8.4f}')
    print(f'{"Peak diff (%)":<25} {np.mean(peak_vals):8.3f} {np.median(peak_vals):8.3f} {np.percentile(peak_vals,95):8.3f} {np.max(peak_vals):8.3f}')
    print(f'{"Vol bias (%)":<25} {np.mean(pb_vals):8.3f} {np.median(pb_vals):8.3f} {np.percentile(pb_vals,95):8.3f} {np.max(pb_vals):8.3f}')
    print(f'{"Time to peak diff (hr)":<25} {np.mean(ttp_vals):8.4f} {np.median(ttp_vals):8.4f} {np.percentile(ttp_vals,95):8.4f} {np.max(ttp_vals):8.4f}')
    print(f'\nNSE >= 0.99: {sum(1 for n in nse_vals if n>=0.99)}/{len(nse_vals)}')
    print(f'NSE >= 0.999: {sum(1 for n in nse_vals if n>=0.999)}/{len(nse_vals)}')

    # Worst cases
    worst = sorted(stats, key=lambda s: s['NSE'])[:5]
    print('\nWorst NSE events:')
    for s in worst:
        print(f'  {s["event"]:<35} NSE={s["NSE"]:.4f}  PeakDiff={s["PeakDiff%"]:+.2f}%  TTP_diff={s["TTP_diff_hr"]:+.3f}hr  PBias={s["PBias%"]:+.1f}%')

if __name__ == '__main__':
    main()
