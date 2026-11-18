#!/usr/bin/env python3
"""Independent checks of source chains, clipping interventions and budget decisions."""
from __future__ import annotations
import argparse,csv,hashlib,json,math,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from experiments.runners.run_matrix import read_order_csv,kendall_tau_against_clean

def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):result.update(chunk)
    return result.hexdigest()
def rows(path):
    with path.open() as f:return list(csv.DictReader(f))
def inventory(root):
    state=json.loads((root/'run_manifest.json').read_text())
    for name,h in state['files_sha256'].items():
        path=(root/name).resolve();path.relative_to(root.resolve())
        if digest(path)!=h:raise ValueError('inventory mismatch: '+name)
    for key in ['source_sha256','input_sha256']:
        for name,h in state.get(key,{}).items():
            path=(ROOT/name).resolve();path.relative_to(ROOT)
            if digest(path)!=h:raise ValueError('source/input changed: '+name)
    if state.get('protocol_sha256') and digest(ROOT/'experiments/configs/extended_benchmarks.yml')!=state['protocol_sha256']:raise ValueError('study protocol changed')
    analysis=root/'analysis/analysis_manifest.json'
    if analysis.is_file():
        derived=json.loads(analysis.read_text())
        if derived['source_manifest_sha256']!=digest(root/'run_manifest.json'):raise ValueError('analysis source changed')
        for name,h in derived['artifacts'].items():
            path=(analysis.parent/name).resolve();path.relative_to(analysis.parent.resolve())
            if digest(path)!=h:raise ValueError('analysis artifact changed: '+name)
    return state

def cloud(folder,metrics):
    spec=json.loads((folder/'embedding.json').read_text());n=spec['clean_point_count'];clean=None;checked=0
    expected={int(r['condition'][1:]):r for r in metrics if r['arm']=='native'}
    for d in range(5):
        grid=rows(folder/f'D{d}.grid.csv');frames=rows(folder/f'D{d}.frame.csv')
        points=np.array([[float(r[k]) for k in ['x','y','z']] for r in grid]);projected=np.array([[float(r['projected_'+a]) for a in 'xyz'] for r in grid]);half=np.array([float(r['half_extent']) for r in frames]);center=np.array([float(r['center']) for r in frames]);axes=np.array([[float(r['axis'+str(j)]) for j in range(3)] for r in frames]).T
        delta=points-center
        reconstructed=np.column_stack([(axes[0,j]*delta[:,0]+axes[1,j]*delta[:,1])+axes[2,j]*delta[:,2] for j in range(3)])
        if not np.allclose(projected,reconstructed,rtol=1e-12,atol=1e-10):raise ValueError('projection snapshot mismatch')
        if d==0:clean=points;assert len(clean)==n
        elif not np.array_equal(points[:n],clean):raise ValueError('inlier prefix drift')
        bits=np.array([int(r['native_bits']) for r in frames]);limit=np.array([2**int(b)-1 for b in bits],dtype=np.int64)
        expected_q=np.floor((projected.astype(np.longdouble)+half.astype(np.longdouble))/(2*half.astype(np.longdouble))*np.exp2(bits.astype(np.longdouble))).astype(np.int64)
        expected_q=np.maximum(0,np.minimum(limit,expected_q));outside=(projected < -half)|(projected > half)
        unclipped=np.where(outside,np.floor((projected.astype(np.longdouble)+half.astype(np.longdouble))/(2*half.astype(np.longdouble))*np.exp2(bits.astype(np.longdouble))),expected_q).astype(np.int64)
        q=np.array([[int(r['q'+str(j)]) for j in range(3)] for r in grid]);u=np.array([[int(r['unclipped'+str(j)]) for j in range(3)] for r in grid])
        if not np.array_equal(q,expected_q) or not np.array_equal(u,unclipped):raise ValueError('quantization intervention drift')
        count=int(np.any(outside,axis=1).sum())
        if count!=round(float(expected[d]['clipped_fraction'])*len(points)):raise ValueError('clipped fraction mismatch')
        keys={};orders={}
        for arm in ['native','tie_projected','clamp_on','clamp_off']:
            order_rows=rows(folder/f'D{d}.{arm}.order.csv');order=[int(r['raw_index']) for r in order_rows]
            if sorted(order)!=list(range(len(points))):raise ValueError('invalid permutation')
            by_id={int(r['raw_index']):int(r['key']) for r in order_rows};keys[arm]=by_id;orders[arm]=order
            def key(i):return (by_id[i],*(projected[i] if arm=='tie_projected' else []),*points[i],i)
            if order!=sorted(range(len(points)),key=key):raise ValueError('wrong deterministic tie ordering')
            r=next(r for r in metrics if r['arm']==arm and r['condition']==f'D{d}');reference=read_order_csv(folder/f'D0.{arm}.order.csv');tau=kendall_tau_against_clean(reference,order,n)
            if not math.isclose(tau,float(r['kendall_tau']),abs_tol=1e-14):raise ValueError('Kendall mismatch')
            scale=float(np.linalg.norm(np.ptp(clean,axis=0)))
            inliers=[i for i in order if i<n]
            for field,ids in [('normalized_miad_all',order),('normalized_miad_inlier',inliers)]:
                value=float(np.linalg.norm(np.diff(points[ids],axis=0),axis=1).mean())/scale
                if not math.isclose(value,float(r[field]),rel_tol=1e-10,abs_tol=1e-13):raise ValueError('MIAD mismatch')
            checked+=1
        if keys['native']!=keys['tie_projected']:raise ValueError('tie intervention changed native keys')
        for i in range(len(points)):
            if (keys['clamp_on'][i]!=keys['clamp_off'][i])!=bool(np.any(q[i]!=u[i])):raise ValueError('clamp changed an unaffected tuple or failed to change a distinct tuple')
    return checked

def validate_clamping(root):
    state=inventory(root);data=rows(root/'metrics.csv');blocks=sorted({(r['geometry_id'],r['seed']) for r in data});checked=0
    if len(blocks)!=state['n_clouds'] or len(data)!=len(blocks)*20:raise ValueError('incomplete clamping matrix')
    for g,s in blocks:checked+=cloud(root/'clouds'/f'{g}_s{s}',[r for r in data if (r['geometry_id'],r['seed'])==(g,s)])
    return {'clouds':len(blocks),'verified_order_metric_records':checked,'status':'passed'}
def validate_real_clamping(root):
    state=inventory(root);data=rows(root/'metrics.csv');checked=0
    for site in state['sites']:
        for seed in range(state['subclouds_per_site']):
            selected=[{**r,'clipped_fraction':next(x['clipped_point_count'] for x in rows(root/site/f'seed_{seed}/intervention/diagnostics.csv') if x['condition']==r['condition'] and x['arm']==r['arm'])} for r in data if r['dataset_id']==site and int(r['subsample_seed'])==seed]
            # The common checker expects a point fraction, not a count.
            diag={(x['condition'],x['arm']):x for x in rows(root/site/f'seed_{seed}/intervention/diagnostics.csv')}
            for r in selected:r['clipped_fraction']=int(diag[r['condition'],r['arm']]['clipped_point_count'])/int(diag[r['condition'],r['arm']]['point_count'])
            checked+=cloud(root/site/f'seed_{seed}/intervention',selected)
    return {'sites':len(state['sites']),'verified_order_metric_records':checked,'status':'passed'}
def validate_cost(root):
    state=inventory(root);data=rows(root/'measurements.csv');blocks=sorted({(r['geometry_id'],r['seed']) for r in data})
    if len(blocks)!=state['n_clouds'] or len(data)!=len(blocks)*30:raise ValueError('incomplete cost matrix')
    for r in data:
        if int(r['timing_repeats'])!=5 or float(r['sort_seconds'])<=0 or not -1<=float(r['kendall_tau'])<=1:raise ValueError('invalid cost/stability metric')
        if r['condition']=='D0' and float(r['kendall_tau'])!=1:raise ValueError('invalid clean reference')
    policies=rows(root/'analysis/cloud_policy_costs.csv');decisions=rows(root/'analysis/scenario_decisions.csv')
    if len(decisions)!=len(blocks)*16:raise ValueError('incomplete requirement grid')
    measurements_by_policy={}
    for x in data:measurements_by_policy.setdefault((x['geometry_id'],x['seed'],x['policy']),[]).append(x)
    for r in decisions:
        candidates=[x for x in policies if x['geometry_id']==r['geometry_id'] and x['seed']==r['seed']];base=min(float(x['worst_condition_sort_seconds']) for x in candidates if x['policy'].startswith('PCA:'));tau=float(r['tau_min_scenario']);budget=float(r['budget_multiplier']);eligible=[]
        for candidate in candidates:
            measured=measurements_by_policy[r['geometry_id'],r['seed'],candidate['policy']]
            worst_tau=min(float(x['kendall_tau']) for x in measured if x['condition']!='D0');worst_time=max(float(x['sort_seconds']) for x in measured)
            if worst_tau!=float(candidate['worst_kendall']) or worst_time!=float(candidate['worst_condition_sort_seconds']):raise ValueError('wrong worst-condition aggregation')
            if worst_tau>=tau and worst_time<=base*budget:eligible.append(candidate)
        selected=min(eligible,key=lambda x:(float(x['worst_condition_sort_seconds']),x['policy']))['policy'] if eligible else 'none'
        if selected!=r['selected_policy']:raise ValueError('ineligible or non-minimum-cost selection')
    return {'clouds':len(blocks),'measurement_records':len(data),'scenario_decisions':len(decisions),'status':'passed'}
def validate_published(application_root):
    generated=ROOT/'analysis/generated';output=generated/'outputs/extended_benchmarks'
    manifest=json.loads((output/'artifact_manifest.json').read_text())
    if manifest['generator_sha256']!=digest(ROOT/'analysis/scripts/make_extended_benchmark_artifacts.py'):raise ValueError('publication generator changed')
    for family,checksum in manifest['sources'].items():
        source=(application_root if family=='application' else ROOT/'experiments/outputs'/family)/'run_manifest.json'
        if digest(source)!=checksum:raise ValueError('published source changed: '+family)
        if family!='application':
            destination=generated/'outputs'/family
            if digest(destination/'run_manifest.json')!=checksum:raise ValueError('published source snapshot changed')
            analysis=source.parent/'analysis/analysis_manifest.json'
            artifacts=json.loads(analysis.read_text())['artifacts'] if analysis.exists() else {n:digest(source.parent/n) for n in ['metrics.csv','summary.csv']}
            for name,h in artifacts.items():
                if digest(destination/name)!=h:raise ValueError('published study artifact changed: '+name)
    for base,checks in [(output,manifest['artifacts']),(generated,manifest['published_artifacts'])]:
        for name,h in checks.items():
            path=(base/name).resolve();path.relative_to(base.resolve())
            if digest(path)!=h:raise ValueError('published artifact changed: '+name)
    return {'status':'passed','source_families':len(manifest['sources']),'published_figures_and_tables':len(manifest['published_artifacts'])}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path);p.add_argument('--published-only',action='store_true');p.add_argument('--application-root',type=Path,default=ROOT/'experiments/outputs/application_query/full_benchmark');a=p.parse_args()
    if a.output is None:a.output=ROOT/'experiments/logs/validation'/('extended_benchmarks_publication_validation.json' if a.published_only else 'extended_benchmarks_validation.json')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    if a.published_only:
        result={'publication':validate_published(a.application_root)};a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));return
    result={'clamping':validate_clamping(ROOT/'experiments/outputs/clamping_intervention'),'real_clamping':validate_real_clamping(ROOT/'experiments/outputs/real_clamping_checks'),'cost_stability':validate_cost(ROOT/'experiments/outputs/cost_stability_scenarios')};a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
