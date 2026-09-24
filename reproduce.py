"""Fresh one-worker reproduction with bounded children and deterministic reconciliation.
The destination must not exist. No retained measurement is overwritten.
Timing and process measurements are compared descriptively, not for bit equality.
"""
from __future__ import annotations
import argparse, json, os, resource, subprocess, sys, time
from pathlib import Path

MEASUREMENTS={'seconds','cpu_seconds','wall_seconds','peak_rss_kib',
              'setup_seconds','update_seconds','total_seconds'}

def stable(value):
    if isinstance(value,dict):
        return {k:stable(v) for k,v in value.items() if k not in MEASUREMENTS}
    if isinstance(value,list):return [stable(v) for v in value]
    return value

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',required=True,help='new output directory, outside retained results')
    args=parser.parse_args()
    if not __debug__:
        raise SystemExit('Run without -O: the scientific checks require assertions')
    root=Path(__file__).resolve().parent
    out=Path(args.out).resolve()
    if out.exists():raise SystemExit('output exists; select a fresh directory')
    out.mkdir(parents=True)
    start=time.perf_counter();cpu0=time.process_time();commands=[]
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
    def run(parts):
        command=[sys.executable,*[str(p) for p in parts]]
        tick=time.perf_counter(); before=resource.getrusage(resource.RUSAGE_CHILDREN)
        record={'command':[str(p) for p in parts]}
        try:
            child=subprocess.run(command,cwd=root,env=env,text=True,stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,timeout=40)
            record.update(exit_code=child.returncode,stdout=child.stdout,stderr=child.stderr)
        except subprocess.TimeoutExpired as e:
            record.update(exit_code=None,status='timeout',stdout=str(e.stdout or ''),stderr=str(e.stderr or ''))
            commands.append(record)
            (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
            raise SystemExit('child timeout; partial outputs are retained, no completion claim')
        after=resource.getrusage(resource.RUSAGE_CHILDREN)
        record.update(wall_seconds=time.perf_counter()-tick,
                      child_cpu_seconds=(after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime))
        commands.append(record)
        (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        if child.returncode:raise SystemExit('child failed; inspect commands.json')
        print(parts[0], 'exit=0',flush=True)
    run(['tests/check_bibliography.py','--out',out/'bibliography_validation.json'])
    run(['pilot.py','--out',out/'pilot.json'])
    run(['tests/check_all.py','--out',out/'checks.json'])
    run(['tests/check_amplification.py','--out',out/'amplification.json'])
    run(['tests/check_support_envelope.py','--out',out/'support_envelope.json'])
    run(['tests/check_rational_model.py','--out',out/'rational_checks.json'])
    for first,last in ((0,20),(20,40),(40,60)):
        run(['benchmark.py','--start',first,'--stop',last,'--out',out/'campaign'])
    run(['summarize.py','--root',out/'campaign','--out',out])
    compared=0
    for name in ('bibliography_validation.json','pilot.json','checks.json','amplification.json','support_envelope.json','rational_checks.json'):
        old=json.loads((root/'results'/name).read_text())
        new=json.loads((out/name).read_text())
        if stable(old)!=stable(new):raise SystemExit('deterministic check mismatch: '+name)
    config=json.loads((root/'inputs/campaign.json').read_text())
    for spec in config['cases']:
        name=spec['id']+'.json'
        old=json.loads((root/'results/campaign'/name).read_text())
        new=json.loads((out/'campaign'/name).read_text())
        if stable(old)!=stable(new):raise SystemExit('deterministic campaign mismatch: '+name)
        compared+=len(new['runs'])
    old=json.loads((root/'results/summary.json').read_text())
    new=json.loads((out/'summary.json').read_text())
    lookup=lambda s:{(a['family'],a['method']):a for a in s['aggregates']}
    a,b=lookup(old),lookup(new)
    ratios=[{'family':f,'primary_exact_over_full':a[f,'exact']['total_ratio'],
             'reproduction_exact_over_full':b[f,'exact']['total_ratio']} for f in ('independent','coupled','relay','all')]
    child=resource.getrusage(resource.RUSAGE_CHILDREN)
    result={'status':'passed','deterministic_timed_searches_compared':compared,
            'deterministic_fields':'input bytes decoded as JSON; graphs/dimensions; costs; all work counters; search status/cost/expansions/generated; scalar factors',
            'excluded_from_equality':sorted(MEASUREMENTS),'timing_comparison':ratios,
            'child_cpu_seconds':child.ru_utime+child.ru_stime,
            'parent_cpu_seconds':time.process_time()-cpu0,'wall_seconds':time.perf_counter()-start,
            'child_peak_rss_kib':child.ru_maxrss,'workers':1}
    (out/'reproduction.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
