#!/usr/bin/env python3
"""Analyze frozen refinement and key-sharing records; does not run benchmarks or rewrite them."""
from __future__ import annotations
import argparse,csv,hashlib,json,statistics
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
def digest(p):
    result=hashlib.sha256()
    with p.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):result.update(chunk)
    return result.hexdigest()
def rows(p):
    with p.open() as f:return list(csv.DictReader(f))
def write(p,data):
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
def sharing(xyz,keys):
    if len(xyz)!=len(keys) or not len(keys):raise ValueError('invalid input/key lengths')
    _,first,coordinate_counts=np.unique(xyz,axis=0,return_index=True,return_counts=True)
    _,inverse,key_counts=np.unique(keys,return_inverse=True,return_counts=True)
    unique_keys,distinct_counts=np.unique(keys[first],return_counts=True)
    mixed=set(unique_keys[distinct_counts>1].tolist())
    return dict(shared_key_point_fraction=float(key_counts[key_counts>1].sum()/len(keys)),
        unique_xyz=len(first),shared_xyz_point_fraction=float(coordinate_counts[coordinate_counts>1].sum()/len(keys)),
        mixed_xyz_key_group_point_fraction=sum(int(n) for k,n in zip(*np.unique(keys,return_counts=True)) if int(k) in mixed)/len(keys),
        shared_key_fraction_on_unique_xyz=float(distinct_counts[distinct_counts>1].sum()/len(first)),
        largest_key_group=int(key_counts.max()),largest_distinct_xyz_per_key=int(distinct_counts.max()))
def refinement(root):
    result=[];sources={}
    for mode in ['off','all']:
        p=root/mode/'table_3_locality.csv';sources[str(p)]=digest(p);data=rows(p)
        selected=[r for r in data if r['geometry_id'] in ['E1','E2'] and r['contamination_id']=='D0' and float(r['point_count'])==384]
        def key(r):return r['geometry_id'],int(float(r['seed']))
        candidates=[r for r in selected if r['algorithm_id']=='A6_rch' and r['bit_rule'][:2] in ['C2','C3','C4']]
        if len(candidates)!=30:raise ValueError('expected 30 primary configuration rows per refinement arm')
        for r in candidates:
            for baseline in ['A3_isotropic_hilbert','A2_morton','A2_morton:C3_frame_core_occupancy','A5b_robust_frame_morton']:
                reference=[x for x in selected if key(x)==key(r) and x['algorithm_id']==baseline.split(':')[0] and x['bit_rule']==(baseline.split(':')[1] if ':' in baseline else r['bit_rule'] if baseline=='A5b_robust_frame_morton' else 'C0_uniform')]
                if len(reference)!=1:raise ValueError('missing/duplicate paired baseline')
                b=reference[0]
                if r.get('refinement')!=mode or b.get('refinement')!=mode:raise ValueError('row refinement does not match arm')
                input_hashes=[]
                for x in [r,b]:
                    p=root/mode/'data'/f"{x['algorithm_id']}__{x['bit_rule']}__D0__{x['geometry_id']}__n384__s{key(x)[1]}.csv"
                    sources[str(p)]=digest(p);input_hashes.append(sources[str(p)])
                if len(set(input_hashes))!=1:raise ValueError('refined methods use different input points')
                result.append(dict(refinement=mode,geometry_id=r['geometry_id'],seed=key(r)[1],bit_rule=r['bit_rule'],baseline=baseline,rch_miad=float(r['miad']),baseline_miad=float(b['miad']),delta_miad=float(r['miad'])-float(b['miad']),input_sha256=input_hashes[0]))
    # Both methods and both refinement arms must use exactly the same points.
    hashes={}
    for r in result:hashes.setdefault((r['geometry_id'],r['seed'],r['bit_rule'],r['baseline']),set()).add(r['input_sha256'])
    if any(len(h)!=1 for h in hashes.values()):raise ValueError('off/all input mismatch')
    summary=[]
    for mode in ['off','all']:
        for baseline in ['A3_isotropic_hilbert','A2_morton','A2_morton:C3_frame_core_occupancy','A5b_robust_frame_morton']:
            selected=[r for r in result if r['refinement']==mode and r['baseline']==baseline];values=[r['delta_miad'] for r in selected]
            summary.append(dict(refinement=mode,baseline=baseline,configuration_rows=len(values),distinct_geometry_seed_clouds=len({(r['geometry_id'],r['seed']) for r in selected}),median_delta_miad=statistics.median(values),rch_lower=sum(x<0 for x in values),ties=sum(x==0 for x in values),scope='descriptive legacy primary configurations; rules share inputs; not 30 independent clouds'))
    return result,summary,sources
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--synthetic-root',type=Path,default=ROOT/'experiments/outputs/synthetic_dataset');parser.add_argument('--application-root',type=Path,default=ROOT/'experiments/outputs/application_query/full_benchmark');parser.add_argument('--output-dir',type=Path,default=ROOT/'analysis/generated/outputs/measurement_diagnostics');a=parser.parse_args();a.output_dir.mkdir(parents=True,exist_ok=True)
    pairs,summary,sources=refinement(a.synthetic_root);write(a.output_dir/'refined_vs_refined_pairs.csv',pairs);write(a.output_dir/'refined_vs_refined_summary.csv',summary)
    manifest=a.application_root/'run_manifest.json';m=json.loads(manifest.read_text());sources[str(manifest)]=digest(manifest);collisions=[];details={}
    for d in m['datasets']:
        path=ROOT/d['input_csv']
        if digest(path)!=d['input_csv_sha256']:raise ValueError('input checksum changed')
        sources[str(path)]=digest(path);xyz=np.loadtxt(path,delimiter=',',ndmin=2)
        for layout in ['A3_isotropic_hilbert','A6_rch','A6_rch_C2','A6_rch_C3','A6_rch_C4']:
            record=d['order_files'][layout];path=ROOT/record['path']
            if digest(path)!=record['sha256']:raise ValueError('order checksum changed')
            sources[str(path)]=digest(path);r=rows(path);ids=np.array([int(x['raw_index']) for x in r]);keys=np.array([int(x['key']) for x in r],dtype=np.uint64)
            if not np.array_equal(np.sort(ids),np.arange(len(xyz))):raise ValueError('invalid permutation')
            by_id=np.empty(len(keys),dtype=np.uint64);by_id[ids]=keys
            collisions.append(dict(dataset_id=d['dataset_id'],layout_id=layout,points=len(xyz),**sharing(xyz,by_id)))
        details[d['dataset_id']]=dict(bbox_min=xyz.min(0).tolist(),bbox_max=xyz.max(0).tolist(),coordinate_quantiles_001_50_999=np.quantile(xyz,[.001,.5,.999],axis=0).tolist())
    write(a.output_dir/'key_coordinate_sharing.csv',collisions)
    raw=ROOT/'data/raw/noaa_lidar/20070717_079283_w_ld_p31.copc.laz'
    if raw.exists():
        import laspy,yaml
        pin=next(d for d in yaml.safe_load((ROOT/'data/manifests/noaa_lidar.yml').read_text())['datasets'] if d['id']=='noaa_southwest_florida')
        if digest(raw)!=pin['sha256']:raise ValueError('Florida raw checksum differs from pinned source')
        las=laspy.read(raw)
        delivered=np.column_stack([las.x,las.y,las.z])
        florida=next(d for d in m['datasets'] if d['dataset_id']=='noaa_southwest_florida')
        converted=np.loadtxt(ROOT/florida['input_csv'],delimiter=',',ndmin=2)
        if not np.array_equal(delivered,converted):raise ValueError('raw delivered XYZ and converted records differ')
        _,counts=np.unique(np.column_stack([las.X,las.Y,las.Z]),axis=0,return_counts=True)
        details['florida_raw_integer_xyz_check']=dict(raw_sha256=digest(raw),raw_xyz_matches_converted_records=True,records=len(las.points),unique_xyz=len(counts),minimum_multiplicity=int(counts.min()),maximum_multiplicity=int(counts.max()),multiplicity_histogram={str(k):int(v) for k,v in zip(*np.unique(counts,return_counts=True))})
    (a.output_dir/'coordinate_details.json').write_text(json.dumps(details,indent=2)+'\n')
    table=['\\begin{tabular}{llrr}','Mode & Baseline & Median RCH minus baseline MIAD & RCH lower \\\\','\\hline']
    for r in summary:table.append(f"{r['refinement']} & {r['baseline'].replace('_',chr(92)+'_')} & {r['median_delta_miad']:.6f} & {r['rch_lower']}/30 \\\\")
    table+=['\\end{tabular}'];(a.output_dir/'table_synthetic_refined_vs_refined.tex').write_text('\n'.join(table)+'\n')
    mismatches=[n for n,h in m.get('source_sha256',{}).items() if not (ROOT/n).exists() or digest(ROOT/n)!=h]
    state=dict(scope='analysis of preserved measurements, not a benchmark rerun; changed source hashes are explicit',application_source_mismatches=mismatches,sources_sha256=sources,generator_sha256=digest(Path(__file__)),artifacts_sha256={p.name:digest(p) for p in a.output_dir.iterdir() if p.is_file() and p.name!='analysis_manifest.json'})
    (a.output_dir/'analysis_manifest.json').write_text(json.dumps(state,indent=2)+'\n');print(json.dumps({'refinement_summary':summary,'collision_rows':len(collisions),'current_application_source_mismatches':mismatches}))
if __name__=='__main__':main()
