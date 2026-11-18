#!/usr/bin/env python3
"""Measure same-cloud policy costs and evaluate predeclared stability/budget scenarios."""
from __future__ import annotations
import argparse,csv,hashlib,json,random,subprocess,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from experiments.runners.run_matrix import read_order_csv,kendall_tau_against_clean
RULES={'C2_occupancy_floor1':'occupancy_floor1','C3_frame_core_occupancy':'frame_core_occupancy','C4_hybrid':'hybrid_occupancy'}
def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(path,rows):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def analyze(root,output):
    rows=list(csv.DictReader((root/'measurements.csv').open()));cells={(r['geometry_id'],r['seed'],r['policy'],r['condition']):r for r in rows};blocks=sorted({(r['geometry_id'],r['seed']) for r in rows});policies=sorted({r['policy'] for r in rows});cloud=[]
    for g,s in blocks:
        for policy in policies:
            selected=[cells[g,s,policy,'D'+str(d)] for d in range(1,5)];clean=cells[g,s,policy,'D0'];cloud.append({'geometry_id':g,'seed':s,'policy':policy,'worst_kendall':min(float(r['kendall_tau']) for r in selected),'mean_contaminated_kendall':float(np.mean([float(r['kendall_tau']) for r in selected])),'clean_sort_seconds':float(clean['sort_seconds']),'worst_condition_sort_seconds':max(float(r['sort_seconds']) for r in [clean,*selected])})
    scenarios=[]
    for g,s in blocks:
        selected=[r for r in cloud if (r['geometry_id'],r['seed'])==(g,s)]
        # Budget uses the cheapest measured PCA policy under the same worst-condition timing boundary.
        baseline=min(r['worst_condition_sort_seconds'] for r in selected if r['policy'].startswith('PCA:'))
        for tau_min in [.5,.75,.9,.95]:
            for budget in [2,5,10,20]:
                eligible=[r for r in selected if r['worst_kendall']>=tau_min and r['worst_condition_sort_seconds']<=baseline*budget]
                best=min(eligible,key=lambda r:(r['worst_condition_sort_seconds'],r['policy'])) if eligible else None
                scenarios.append({'geometry_id':g,'seed':s,'tau_min_scenario':tau_min,'budget_multiplier':budget,'pca_baseline_worst_seconds':baseline,'selected_policy':best['policy'] if best else 'none','selected_worst_kendall':best['worst_kendall'] if best else '', 'selected_worst_seconds':best['worst_condition_sort_seconds'] if best else '', 'rch_eligible':any(r['policy'].startswith('RCH:') for r in eligible),'pca_eligible':any(r['policy'].startswith('PCA:') for r in eligible),'eligible_policy_count':len(eligible)})
    summary=[]
    for tau_min in [.5,.75,.9,.95]:
        for budget in [2,5,10,20]:
            current=[r for r in scenarios if r['tau_min_scenario']==tau_min and r['budget_multiplier']==budget];n=len(current)
            summary.append({'tau_min_scenario':tau_min,'budget_multiplier':budget,'n_clouds':n,'rch_selected':sum(r['selected_policy'].startswith('RCH:') for r in current),'pca_selected':sum(r['selected_policy'].startswith('PCA:') for r in current),'none_selected':sum(r['selected_policy']=='none' for r in current),'rch_only_eligible':sum(r['rch_eligible'] and not r['pca_eligible'] for r in current),'rch_eligible':sum(r['rch_eligible'] for r in current),'pca_eligible':sum(r['pca_eligible'] for r in current)})
    output.mkdir(parents=True,exist_ok=True);write(output/'cloud_policy_costs.csv',cloud);write(output/'scenario_decisions.csv',scenarios);write(output/'scenario_summary.csv',summary)
    (output/'scope.md').write_text('Hypothetical requirements, not observed user/application thresholds. Worst-case Kendall over four declared contaminations is paired with the same cloud and policy worst-condition ordering median over five in-process calls. The budget reference is the fastest PCA policy using the same timing boundary. Policies are selected retrospectively from measured outcomes, not a deployable predictor; no held-out selection guarantee. Separate 256-point evidence must not be used to justify full-scene processing time. Native C2/C3/C4 policies may have different effective resolutions. No frame-only causality is claimed.\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    data=np.array([[next(r['rch_only_eligible'] for r in summary if r['tau_min_scenario']==tau and r['budget_multiplier']==b) for b in [2,5,10,20]] for tau in [.5,.75,.9,.95]])
    fig,ax=plt.subplots(figsize=(6,4));im=ax.imshow(data,vmin=0,vmax=len(blocks));ax.set_xticks(range(4),[2,5,10,20]);ax.set_yticks(range(4),[.5,.75,.9,.95]);ax.set_xlabel('Hypothetical preparation budget / fastest PCA');ax.set_ylabel('Hypothetical minimum worst-condition Kendall')
    for i in range(4):
        for j in range(4):ax.text(j,i,str(data[i,j]),ha='center',va='center',color='white' if data[i,j]<len(blocks)/2 else 'black')
    fig.colorbar(im,ax=ax,label='Clouds where only an RCH policy is eligible');fig.tight_layout();fig.savefig(output/'fig_cost_stability_scenarios.pdf');plt.close(fig)
    (output/'analysis_manifest.json').write_text(json.dumps({'source_manifest_sha256':digest(root/'run_manifest.json'),'artifacts':{p.name:digest(p) for p in output.iterdir() if p.is_file() and p.name!='analysis_manifest.json'}},indent=2)+'\n')
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input-root',type=Path,default=ROOT/'experiments/outputs/independent_benchmarks');p.add_argument('--binary',type=Path,required=True);p.add_argument('--output-dir',type=Path,default=ROOT/'experiments/outputs/cost_stability_scenarios');p.add_argument('--seed-limit',type=int,default=20);p.add_argument('--analyze-only',action='store_true');a=p.parse_args()
    # Normalize CLI paths before comparing them with the absolute repository root.
    a.input_root=a.input_root.resolve()
    a.output_dir=a.output_dir.resolve()
    a.binary=a.binary.resolve()
    if a.analyze_only:analyze(a.output_dir,a.output_dir/'analysis');return
    if a.output_dir.exists():raise ValueError('output root already exists')
    parent=a.input_root/'frame_ablation_bit_rules/off';rows=[r for r in csv.DictReader((parent/'frame_ablation_bit_rules.csv').open()) if int(r['seed'])<a.seed_limit];inventory=json.loads((a.input_root/'benchmark_manifest.json').read_text())['files_sha256'];indexed={(r['geometry_id'],r['seed'],r['algorithm_id'],r['bit_rule'],r['contamination_id']):r for r in rows};blocks=sorted({(r['geometry_id'],r['seed']) for r in rows});a.output_dir.mkdir(parents=True);(a.output_dir/'orders').mkdir();records=[];inputs={};schedule=[]
    for index,(g,s) in enumerate(blocks):
        tasks=[(d,alg,rule) for d in range(5) for alg in ['A5_pca_compact_hilbert','A6_rch'] for rule in RULES];random.Random(20261109+index).shuffle(tasks);schedule.append({'geometry':g,'seed':s,'tasks':tasks})
        results={}
        for d,alg,rule in tasks:
            source=parent/'data'/f'{alg}__{rule}__D{d}__{g}__n256__s{s}.csv';h=digest(source);assert inventory[str(source.relative_to(a.input_root))]==h;inputs[str(source.relative_to(ROOT))]=h
            prefix=a.output_dir/'orders'/f'{g}_s{s}_D{d}_{alg}_{rule}';order=prefix.with_suffix('.csv');meta=prefix.with_suffix('.json')
            command=[str(a.binary.resolve()),'--input',str(source.resolve()),'--method','rch' if alg=='A6_rch' else 'pca_compact_hilbert','--frame-estimator','det_mcd' if alg=='A6_rch' else 'sample','--bit-allocator',RULES[rule],'--refinement','off','--timing-repeats','5','--output',str(order.resolve()),'--manifest',str(meta.resolve())]
            subprocess.run(command,check=True,capture_output=True,text=True);state=json.loads(meta.read_text());old=indexed[g,s,alg,rule,'D'+str(d)]
            if state['hash']!=old['output_hash']:raise ValueError('current ordering differs from frozen source')
            results[d,alg,rule]=(state,order)
        for d,alg,rule in tasks:
            state,order=results[d,alg,rule];reference=results[0,alg,rule][1];tau=kendall_tau_against_clean(read_order_csv(reference),read_order_csv(order),256)
            record={'geometry_id':g,'seed':s,'policy':('RCH:' if alg=='A6_rch' else 'PCA:')+rule[:2],'condition':'D'+str(d),'timing_repeats':5,'sort_seconds':state['sort_seconds'],'kendall_tau':tau,'output_hash':state['hash']}
            record.update({'phase_'+k:v for k,v in state['timing_breakdown_seconds'].items()});records.append(record)
        if (index+1)%20==0:print(f'cost/stability: {index+1}/{len(blocks)} clouds',flush=True)
    write(a.output_dir/'measurements.csv',records);state={'schema':'rch.cost_stability_scenarios','n_clouds':len(blocks),'timing_repeats':5,'binary_sha256':digest(a.binary),'input_sha256':inputs,'schedule':schedule,'source_sha256':{str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__).resolve(),ROOT/'src/cli/rch_order.cpp',ROOT/'include/rch/orderings/orderer.hpp']},'protocol_sha256':digest(ROOT/'experiments/configs/extended_benchmarks.yml'),'files_sha256':{str(p.relative_to(a.output_dir)):digest(p) for p in a.output_dir.rglob('*') if p.is_file()}}
    (a.output_dir/'run_manifest.json').write_text(json.dumps(state,indent=2)+'\n');analyze(a.output_dir,a.output_dir/'analysis')
if __name__=='__main__':main()
