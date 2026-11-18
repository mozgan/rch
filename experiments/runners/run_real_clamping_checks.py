#!/usr/bin/env python3
"""Conditional clamping checks on recorded subclouds from four separate LiDAR sites."""
from __future__ import annotations
import argparse,csv,json,subprocess,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from experiments.runners.run_application_query_smoke import load_dataset_provenance
from experiments.runners.run_clamping_ablation import ARMS,digest,write_csv
from experiments.runners.run_matrix import read_order_csv,kendall_tau_against_clean
from data.synthetic.generators.contamination import contaminate
from data.synthetic.generators.common import write_xyz_csv
SITES=('usgs_cameron_peak','noaa_santiam_river','noaa_long_island','noaa_southwest_florida')
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--binary',type=Path,required=True);p.add_argument('--output-dir',type=Path,default=ROOT/'experiments/outputs/real_clamping_checks');a=p.parse_args()
    # Normalize CLI paths before comparing them with the absolute repository root.
    a.output_dir=a.output_dir.resolve()
    a.binary=a.binary.resolve()
    if a.output_dir.exists():raise ValueError('output root already exists')
    a.output_dir.mkdir(parents=True);rows=[];sources=[]
    for site in SITES:
        record=load_dataset_provenance(site,ROOT/'data/raw/usgs_3dep',ROOT/'data/processed/usgs_3dep');points=record.pop('points');sources.append(record)
        for seed in range(5):
            work=a.output_dir/site/f'seed_{seed}';work.mkdir(parents=True)
            ids=np.random.default_rng(20261109+seed).choice(len(points),1024,replace=False)
            (work/'source_ids.json').write_text(json.dumps(ids.tolist())+'\n')
            clean=[points[i] for i in ids];scale=float(np.linalg.norm(np.ptp(np.array(clean),axis=0)));conditions=[('clean',0),('uniform_bbox',.05),('uniform_bbox',.15),('uniform_bbox',.25),('clustered',.25)];paths=[];arrays=[]
            for d,(mode,fraction) in enumerate(conditions):
                path=work/f'D{d}.csv';cloud=contaminate(clean,mode,fraction,seed);write_xyz_csv(path,cloud);paths.append(path);arrays.append(np.array(cloud))
            command=[str(a.binary.resolve()),'--output',str(work/'intervention')]
            for path in paths:command+=['--input',str(path.resolve())]
            subprocess.run(command,check=True,capture_output=True,text=True)
            for d,xyz in enumerate(arrays):
                for arm in ARMS:
                    order=read_order_csv(work/'intervention'/f'D{d}.{arm}.order.csv');reference=read_order_csv(work/'intervention'/f'D0.{arm}.order.csv');inliers=[i for i in order if i<1024]
                    rows.append(dict(dataset_id=site,subsample_seed=seed,condition=f'D{d}',arm=arm,clean_points=1024,full_scene_points=len(points),kendall_tau=kendall_tau_against_clean(reference,order,1024),normalized_miad_all=float(np.linalg.norm(np.diff(xyz[order],axis=0),axis=1).mean())/scale,normalized_miad_inlier=float(np.linalg.norm(np.diff(xyz[inliers],axis=0),axis=1).mean())/scale))
        print('real clamping:',site,'5 recorded subclouds',flush=True)
    write_csv(a.output_dir/'metrics.csv',rows);summary=[];index={(r['dataset_id'],r['subsample_seed'],r['condition'],r['arm']):r for r in rows}
    for site in SITES:
        for metric in ['kendall_tau','normalized_miad_all','normalized_miad_inlier']:
            per_subset=[]
            for seed in range(5):per_subset.append(float(np.mean([index[site,seed,f'D{d}','clamp_on'][metric]-index[site,seed,f'D{d}','clamp_off'][metric] for d in range(1,5)])))
            summary.append(dict(dataset_id=site,metric=metric,median_subcloud_mean_clamp_on_minus_off=float(np.median(per_subset)),minimum=float(min(per_subset)),maximum=float(max(per_subset)),n_subclouds=5,scope='conditional on one fixed scene; overlapping samples are not independent sensor/site observations; no population CI'))
    write_csv(a.output_dir/'summary.csv',summary)
    state={'schema':'rch.real_clamping_checks','source_datasets':sources,'sites':list(SITES),'subclouds_per_site':5,'binary_sha256':digest(a.binary),'source_sha256':{str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__).resolve(),ROOT/'src/cli/rch_clamping_ablation.cpp',ROOT/'data/synthetic/generators/contamination.py']},'files_sha256':{str(p.relative_to(a.output_dir)):digest(p) for p in a.output_dir.rglob('*') if p.is_file()}}
    (a.output_dir/'run_manifest.json').write_text(json.dumps(state,indent=2)+'\n')
if __name__=='__main__':main()
