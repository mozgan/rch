#!/usr/bin/env python3
"""Publish source-linked extended benchmark results; never edit the manuscript."""
from __future__ import annotations
import argparse,csv,hashlib,json,shutil,subprocess,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from analysis.scripts.check_extended_benchmarks import inventory,digest
from scripts.convert_dataset import load_manifest

def rows(path):
    with path.open() as f:return list(csv.DictReader(f))
def write(path,data):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
def tex_escape(value):return str(value).replace('_',r'\_').replace('%',r'\%').replace('&',r'\&')
def cost_figure(summary,destination):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    thresholds=[.5,.75,.9,.95];budgets=[2,5,10,20]
    indexed={(float(r['tau_min_scenario']),int(r['budget_multiplier'])):r for r in summary}
    fig,axes=plt.subplots(1,3,figsize=(12,4),sharey=True,layout='constrained')
    for ax,field,title in zip(axes,['rch_selected','pca_selected','none_selected'],['RCH selected','PCA selected','No eligible policy']):
        values=np.array([[int(indexed[t,b][field]) for b in budgets] for t in thresholds])
        im=ax.imshow(values,vmin=0,vmax=220,cmap='viridis',aspect='auto')
        ax.set_xticks(range(4),budgets);ax.set_yticks(range(4),thresholds)
        ax.set_xlabel('Hypothetical ordering budget / PCA');ax.set_title(title)
        for i in range(4):
            for j in range(4):ax.text(j,i,str(values[i,j]),ha='center',va='center',color='white' if values[i,j]<110 else 'black')
    axes[0].set_ylabel('Hypothetical minimum worst-condition Kendall')
    fig.colorbar(im,ax=axes,label='Tested clouds (out of 220)',shrink=.85)
    fig.savefig(destination);plt.close(fig)
def table(path,headers,data,caption):
    lines=[r'\begin{table}[tbp]\centering\scriptsize',r'\caption{'+caption+'}',r'\begin{tabular}{'+'l'*len(headers)+'}',r'\hline',' & '.join(headers)+r' \\']
    lines += [' & '.join(tex_escape(x) for x in row)+r' \\' for row in data];lines += [r'\hline',r'\end{tabular}',r'\end{table}'];path.write_text('\n'.join(lines)+'\n')
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application-root',type=Path,default=ROOT/'experiments/outputs/application_query/full_benchmark')
    args=parser.parse_args()
    generated=ROOT/'analysis/generated';output=generated/'outputs/extended_benchmarks';output.mkdir(parents=True,exist_ok=True);sources={};published={}
    families=['clamping_intervention','cost_stability_scenarios','real_clamping_checks']
    for family in families:
        root=ROOT/'experiments/outputs'/family;inventory(root);sources[family]=digest(root/'run_manifest.json');dest=generated/'outputs'/family;dest.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/'run_manifest.json',dest/'run_manifest.json')
        if (root/'analysis').is_dir():
            for p in (root/'analysis').iterdir():
                if p.is_file():shutil.copyfile(p,dest/p.name)
        else:
            for name in ['metrics.csv','summary.csv']:shutil.copyfile(root/name,dest/name)
    # Reveal the encoder-context effect explicitly; do not attribute it to clipping.
    metrics=rows(ROOT/'experiments/outputs/clamping_intervention/metrics.csv');indexed={(r['geometry_id'],r['seed'],r['condition'],r['arm']):r for r in metrics};embedding=[]
    for g,s in sorted({(r['geometry_id'],r['seed']) for r in metrics}):
        for metric in ['kendall_tau','normalized_miad_all','normalized_miad_inlier']:
            effect=float(np.mean([float(indexed[g,s,f'D{d}','clamp_on'][metric])-float(indexed[g,s,f'D{d}','native'][metric]) for d in range(1,5)]));embedding.append(dict(geometry_id=g,seed=s,metric=metric,cloud_mean_embedding_minus_native=effect))
    write(output/'embedding_context_effects.csv',embedding)
    embedding_summary=[dict(metric=m,n_clouds=sum(r['metric']==m for r in embedding),median_cloud_effect=float(np.median([r['cloud_mean_embedding_minus_native'] for r in embedding if r['metric']==m]))) for m in sorted({r['metric'] for r in embedding})];write(output/'embedding_context_summary.csv',embedding_summary)
    for family,figure in [('clamping_intervention','fig_clamping_intervention'),('cost_stability_scenarios','fig_cost_stability_scenarios')]:
        pdf=generated/'outputs'/family/(figure+'.pdf');destination=generated/'figures'/(figure+'.pdf')
        if family=='cost_stability_scenarios':cost_figure(rows(generated/'outputs'/family/'scenario_summary.csv'),destination)
        else:shutil.copyfile(pdf,destination)
        subprocess.run(['pdftops','-eps',str(destination),str(destination.with_suffix('.eps'))],check=True);published[str(destination.relative_to(generated))]=digest(destination)
    clamping=rows(generated/'outputs/clamping_intervention/summary.csv');p=generated/'tables/table_clamping_intervention.tex';table(p,['Contrast','Metric','Effect','95\\% interval'],[(r['comparison'],r['metric'],f"{float(r['median_cloud_mean_effect']):.6g}",f"[{float(r['ci95_low']):.6g}, {float(r['ci95_high']):.6g}]") for r in clamping],'Controlled clipping and fixed-key tie effects; 220 independent clouds, cloud-block descriptive intervals. MIAD is normalized by the clean bbox diagonal. The extended encoder differs from the native context.');published[str(p.relative_to(generated))]=digest(p)
    scenarios=rows(generated/'outputs/cost_stability_scenarios/scenario_summary.csv');p=generated/'tables/table_cost_stability_scenarios.tex';table(p,['Minimum Kendall','Ordering budget / PCA','RCH chosen','PCA chosen','None'],[(r['tau_min_scenario'],r['budget_multiplier'],r['rch_selected'],r['pca_selected'],r['none_selected']) for r in scenarios],'Hypothetical requirement scenarios, not application SLAs. Budget covers ordering-call time only. Native policies may differ in resolution. Counts concern 220 tested clouds; selection is retrospective.');published[str(p.relative_to(generated))]=digest(p)
    app_root=args.application_root;manifest=json.loads((app_root/'run_manifest.json').read_text());sources['application']=digest(app_root/'run_manifest.json');pinned={d['id']:d for d in load_manifest(ROOT/'data/manifests/real_datasets.yml')['datasets']};catalog=[];locality=[];overfetch=[]
    for d in manifest['datasets']:
        spec=pinned[d['dataset_id']];catalog.append(dict(dataset_id=d['dataset_id'],point_count=d['point_count'],source_project=spec.get('acquisition_project',spec.get('label')),sensor_model=spec.get('sensor_model','not established in this audit'),sensor_scope=spec.get('sensor_scope','unknown'),source_url=spec.get('metadata_url',spec.get('url')),archive_sha256=spec['sha256'],horizontal_epsg=spec.get('horizontal_epsg',''),vertical_epsg=spec.get('vertical_epsg',''),units='metre' if spec.get('coordinate_scale_to_metre') else 'source mesh units; not harmonized',record_policy=d.get('record_policy','source records as supplied')))
        xyz=np.loadtxt(ROOT/d['input_csv'],delimiter=',',ndmin=2);assert xyz.shape==(d['point_count'],3);scale=float(np.linalg.norm(np.ptp(xyz,axis=0)))
        for layout in ['A3_isotropic_hilbert','A6_rch','A6_rch_C2','A6_rch_C3','A6_rch_C4']:
            source=d['order_files'][layout];order_rows=rows(ROOT/source['path']);order=np.array([int(x['raw_index']) for x in order_rows]);keys=np.array([int(x['key']) for x in order_rows],dtype=np.uint64);_,counts=np.unique(keys,return_counts=True);miad=float(np.linalg.norm(np.diff(xyz[order],axis=0),axis=1).mean());diag=d['ordering_diagnostics'][layout].get('quantization_diagnostics',{});clipped=diag.get('domain_clipped_point_count') if layout.startswith('A6_') else None
            locality.append(dict(dataset_id=d['dataset_id'],layout_id=layout,point_count=len(xyz),miad=miad,normalized_miad=miad/scale,coordinate_units=catalog[-1]['units'],shared_key_point_fraction=int(counts[counts>1].sum())/len(xyz),clipped_point_fraction=clipped/len(xyz) if clipped is not None else '',scope='one fixed input; no independent repetitions or cross-dataset raw-MIAD pooling'))
        measured=rows(ROOT/d['warm_cache_query_metrics']['path']);groups={}
        for r in measured:groups.setdefault((r['layout_id'],r['query_id']),[]).append(r)
        for layout in manifest['ordering']['layouts']:
            values=[];empty=0
            for (l,q),repeats in groups.items():
                if l!=layout:continue
                signatures={(int(r['records_examined']),int(r['result_count'])) for r in repeats}
                if len(signatures)!=1:raise ValueError('candidate/result counts changed between repeats')
                kprime,k=signatures.pop()
                if kprime<k:raise ValueError('candidate stage undercounts exact results')
                if k==0:empty+=1
                else:values.append((kprime-k)/k)
            overfetch.append(dict(dataset_id=d['dataset_id'],layout_id=layout,nonempty_queries=len(values),empty_queries=empty,median_candidate_overfetch_per_match=float(np.median(values)) if values else '',mean_candidate_overfetch_per_match=float(np.mean(values)) if values else '',p95_candidate_overfetch_per_match=float(np.quantile(values,.95)) if values else '',definition='(records_examined - exact_result_count) / exact_result_count for nonempty queries; different candidate stage from HistSFC Eq1'))
    write(output/'sensor_site_catalog.csv',catalog);write(output/'full_scene_locality.csv',locality);write(output/'sfc_candidate_overfetch.csv',overfetch)
    p=generated/'tables/table_sensor_site_catalog.tex';table(p,['Input','Points','Project sensor model'],[(r['dataset_id'],r['point_count'],r['sensor_model']) for r in catalog],'Seven fixed point-cloud inputs, including four LiDAR projects. Sensor models describe projects, not known serial numbers for each tile.');published[str(p.relative_to(generated))]=digest(p)
    p=generated/'tables/table_real_lidar_locality.tex';table(p,['Input','Layout','MIAD','Shared-key points'],[(r['dataset_id'],r['layout_id'],f"{r['miad']:.7g}",f"{r['shared_key_point_fraction']:.5f}") for r in locality if r['dataset_id'].startswith(('usgs_','noaa_'))],'Locality on complete delivered LiDAR files in metres; original coordinates retained. One fixed case per site; shared-key fractions independently counted from output keys.');published[str(p.relative_to(generated))]=digest(p)
    (output/'scope.md').write_text('Complete-file locality and query measurements use one shared seven-dataset application manifest. LiDAR files are delivered classified/COPC products, not raw waveforms. COPC input order may already be spatially clustered. Sensor models are supported by preserved project metadata; tile serial numbers are unknown. Query overfetch excludes empty queries from ratios and does not replicate HistSFC or SplitSFC. Four-site clamping subclouds are conditional sensitivity checks, not independent scene replications.\n')
    (output/'artifact_manifest.json').write_text(json.dumps({'sources':sources,'generator_sha256':digest(Path(__file__)),'artifacts':{p.name:digest(p) for p in output.iterdir() if p.is_file() and p.name!='artifact_manifest.json'},'published_artifacts':published},indent=2)+'\n')
    print(json.dumps({'source_datasets':len(catalog),'full_scene_locality_rows':len(locality),'overfetch_rows':len(overfetch),'published_artifacts':len(published)}))
if __name__=='__main__':main()
