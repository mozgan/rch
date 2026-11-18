#!/usr/bin/env python3
"""Replay native C3 and isolate saturation with a shared extended encoder."""
from __future__ import annotations
import argparse,csv,hashlib,json,subprocess,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from experiments.runners.run_matrix import kendall_tau_against_clean, read_order_csv
ARMS=('native','tie_projected','clamp_on','clamp_off')
def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write_csv(path,rows):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def analyze(root,output):
    state=json.loads((root/'run_manifest.json').read_text())
    for name,h in state['files_sha256'].items():
        if digest(root/name)!=h:raise ValueError('clamping inventory mismatch: '+name)
    metrics=list(csv.DictReader((root/'metrics.csv').open()))
    indexed={(r['geometry_id'],r['seed'],r['condition'],r['arm']):r for r in metrics}
    effects=[]
    for r in metrics:
        if r['condition']=='D0' or r['arm'] not in ('clamp_on','tie_projected'):continue
        comparison='saturation_on_minus_off' if r['arm']=='clamp_on' else 'projected_tie_minus_raw_tie'
        reference='clamp_off' if r['arm']=='clamp_on' else 'native'
        b=indexed[r['geometry_id'],r['seed'],r['condition'],reference]
        effects.append({k:r[k] for k in ['geometry_id','seed','condition']}|{'comparison':comparison,'delta_kendall':float(r['kendall_tau'])-float(b['kendall_tau']),'delta_normalized_miad_all':float(r['normalized_miad_all'])-float(b['normalized_miad_all']),'delta_normalized_miad_inlier':float(r['normalized_miad_inlier'])-float(b['normalized_miad_inlier']),'delta_shared_key_fraction':float(r['shared_key_fraction'])-float(b['shared_key_fraction'])})
    output.mkdir(parents=True,exist_ok=True);write_csv(output/'paired_effects.csv',effects)
    summaries=[]
    rng=np.random.default_rng(20261109)
    for comparison in sorted({r['comparison'] for r in effects}):
        chosen=[r for r in effects if r['comparison']==comparison]
        blocks=sorted({(r['geometry_id'],r['seed']) for r in chosen})
        for metric in ['delta_kendall','delta_normalized_miad_all','delta_normalized_miad_inlier','delta_shared_key_fraction']:
            per_cloud={(g,s):float(np.mean([r[metric] for r in chosen if (r['geometry_id'],r['seed'])==(g,s)])) for g,s in blocks}
            samples=[]
            for g in sorted({g for g,s in blocks}):
                values=np.array([v for (geom,s),v in per_cloud.items() if geom==g]);samples.append(rng.choice(values,size=(5000,len(values))))
            boot=np.median(np.concatenate(samples,axis=1),axis=1)
            summaries.append({'comparison':comparison,'metric':metric,'n_clouds':len(blocks),'median_cloud_mean_effect':float(np.median(list(per_cloud.values()))),'ci95_low':float(np.quantile(boot,.025)),'ci95_high':float(np.quantile(boot,.975)),'inference_scope':'cloud bootstrap within fixed geometries; conditions kept in cloud; descriptive pointwise interval'})
    write_csv(output/'summary.csv',summaries)
    (output/'scope.md').write_text('The saturation intervention shares an extended encoder and offset across D0-D4. Frame/domain/native depths are fitted per input and identical between ON/OFF within that input. Upper-bound coordinates retain the native closed-bin convention. Embedding changes the native encoder context; compare the native arm separately. This is a conditional saturation contrast, not exact native-C3 causal loss or a deployable quantizer. Projected tie changes only within original native key groups. Raw MIAD is normalized by each clean cloud bbox diagonal.\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    selected=[x for x in summaries if x['metric']=='delta_kendall'];fig,ax=plt.subplots(figsize=(8,4));x=np.arange(len(selected));y=[r['median_cloud_mean_effect'] for r in selected];ax.scatter(x,y)
    ax.vlines(x,[r['ci95_low'] for r in selected],[r['ci95_high'] for r in selected]);ax.axhline(0,color='black',linewidth=.6);ax.set_xticks(x,[r['comparison'].replace('_',' ') for r in selected],rotation=12);ax.set_ylabel('Cloud-mean inlier Kendall difference');fig.tight_layout();fig.savefig(output/'fig_clamping_intervention.pdf');plt.close(fig)
    (output/'analysis_manifest.json').write_text(json.dumps({'source_manifest_sha256':digest(root/'run_manifest.json'),'artifacts':{p.name:digest(p) for p in output.iterdir() if p.is_file() and p.name!='analysis_manifest.json'}},indent=2)+'\n')
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input-root',type=Path,default=ROOT/'experiments/outputs/independent_benchmarks');p.add_argument('--binary',type=Path,required=True);p.add_argument('--output-dir',type=Path,default=ROOT/'experiments/outputs/clamping_intervention');p.add_argument('--seed-limit',type=int,default=20);p.add_argument('--analyze-only',action='store_true');a=p.parse_args()
    # Normalize CLI paths before comparing them with the absolute repository root.
    a.input_root=a.input_root.resolve()
    a.output_dir=a.output_dir.resolve()
    a.binary=a.binary.resolve()
    if a.analyze_only:analyze(a.output_dir,a.output_dir/'analysis');return
    if a.output_dir.exists():raise ValueError('output root already exists')
    parent=a.input_root/'frame_ablation_bit_rules/off';rows=list(csv.DictReader((parent/'frame_ablation_bit_rules.csv').open()));source_inventory=json.loads((a.input_root/'benchmark_manifest.json').read_text())['files_sha256'];selected=[r for r in rows if r['algorithm_id']=='A6_rch' and r['bit_rule']=='C3_frame_core_occupancy' and int(r['seed'])<a.seed_limit];groups=sorted({(r['geometry_id'],r['seed']) for r in selected});a.output_dir.mkdir(parents=True)
    all_metrics=[];input_hashes={}
    for number,(geometry,seed) in enumerate(groups):
        inputs=[parent/'data'/f'A6_rch__C3_frame_core_occupancy__D{d}__{geometry}__n256__s{seed}.csv' for d in range(5)]
        for path in inputs:
            h=digest(path);relative=str(path.relative_to(a.input_root));assert source_inventory[relative]==h;input_hashes[str(path.relative_to(ROOT))]=h
        folder=a.output_dir/'clouds'/f'{geometry}_s{seed}';command=[str(a.binary.resolve()),'--output',str(folder)]
        for path in inputs:command+=['--input',str(path.resolve())]
        subprocess.run(command,check=True,capture_output=True,text=True)
        clean=np.loadtxt(inputs[0],delimiter=',',ndmin=2);n=len(clean);scale=float(np.linalg.norm(np.ptp(clean,axis=0)));assert scale>0
        diagnostic={(r['condition'],r['arm']):r for r in csv.DictReader((folder/'diagnostics.csv').open())}
        for d,path in enumerate(inputs):
            points=np.loadtxt(path,delimiter=',',ndmin=2)
            for arm in ARMS:
                order=read_order_csv(folder/f'D{d}.{arm}.order.csv');reference=read_order_csv(folder/f'D0.{arm}.order.csv');assert sorted(order)==list(range(len(points)));inliers=[i for i in order if i<n]
                def miad(ids):return float(np.linalg.norm(np.diff(points[ids],axis=0),axis=1).mean())
                diag=diagnostic[f'D{d}',arm]
                all_metrics.append({'geometry_id':geometry,'seed':seed,'condition':f'D{d}','arm':arm,'point_count':len(points),'clean_point_count':n,'miad_all':miad(order),'miad_inlier':miad(inliers),'normalized_miad_all':miad(order)/scale,'normalized_miad_inlier':miad(inliers)/scale,'kendall_tau':kendall_tau_against_clean(reference,order,n),'clipped_fraction':int(diag['clipped_point_count'])/len(points),'shared_key_fraction':int(diag['shared_key_point_count'])/len(points),'robust_fallback':diag['native_robust_fallback']})
        if (number+1)%20==0:print(f'clamping: {number+1}/{len(groups)} clouds',flush=True)
    write_csv(a.output_dir/'metrics.csv',all_metrics)
    state={'schema':'rch.clamping_intervention','n_clouds':len(groups),'binary_sha256':digest(a.binary),'source_sha256':{str(path.relative_to(ROOT)):digest(path) for path in [Path(__file__).resolve(),ROOT/'src/cli/rch_clamping_ablation.cpp',ROOT/'include/rch/orderings/orderer.hpp',ROOT/'include/rch/curves/quantization.hpp',ROOT/'include/rch/curves/hilbert3_compact.hpp']},'input_sha256':input_hashes,'protocol_sha256':digest(ROOT/'experiments/configs/extended_benchmarks.yml'),'files_sha256':{str(path.relative_to(a.output_dir)):digest(path) for path in a.output_dir.rglob('*') if path.is_file()}}
    (a.output_dir/'run_manifest.json').write_text(json.dumps(state,indent=2)+'\n');analyze(a.output_dir,a.output_dir/'analysis')
if __name__=='__main__':main()
