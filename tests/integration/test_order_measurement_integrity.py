"""Regression checks for pre-exec RSS inheritance and fixed-Hilbert key counts."""
import csv,json,os,subprocess,sys,tempfile
from pathlib import Path

def main():
    if not sys.platform.startswith("linux"):
        print(json.dumps({"status":"skipped","reason":"Linux exec/RSS regression"}));return
    binary=Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);points=root/'points.csv'
        points.write_text('0,0,0\n0,0,0\n1,1,1\n1,1,1\n0.5,0.25,0.75\n')
        peaks=[]
        for mib in [0,192]:
            out=root/f'order{mib}.csv';meta=root/f'meta{mib}.json';parent=root/f'parent{mib}.json'
            command=[str(binary),'--input',str(points),'--method','isotropic_hilbert','--bit-allocator','uniform','--refinement','off','--output',str(out),'--manifest',str(meta)]
            launcher='import json,os,resource,sys; b=bytearray(int(sys.argv[1])*1024*1024); open(sys.argv[2],"w").write(json.dumps({"ru_maxrss":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})); os.execv(sys.argv[3],sys.argv[3:])'
            subprocess.run([sys.executable,'-c',launcher,str(mib),str(parent),*command],check=True,capture_output=True,text=True)
            m=json.loads(meta.read_text());rows=list(csv.DictReader(out.open()));counts={}
            for row in rows:counts[row['key']]=counts.get(row['key'],0)+1
            expected=sum(n for n in counts.values() if n>1)
            assert expected==4
            assert m['quantization_diagnostics_scope']=='raw_aabb_keys_only'
            assert m['quantization_diagnostics']['duplicate_hilbert_key_point_count']==expected
            assert len({int(r['raw_index']) for r in rows})==5
            peaks.append(m['peak_rss_kb'])
            if sys.platform.startswith('linux'):
                assert m['peak_rss_source']=='linux_proc_self_status_VmHWM'
                assert 0<m['peak_rss_kb']<64*1024,m
                if mib:assert json.loads(parent.read_text())['ru_maxrss']>128*1024
        adapter_peaks=[]
        if len(sys.argv)>2:
            adapter=Path(sys.argv[2]).resolve()
            for mib in [0,192]:
                meta=root/f'adapter{mib}.json';out=root/f'adapter{mib}.csv'
                command=[str(adapter),'--input',str(points),'--output',str(out),'--policy','median','--metadata-output',str(meta)]
                subprocess.run([sys.executable,'-c',launcher,str(mib),str(root/'adapter_parent.json'),*command],check=True,capture_output=True,text=True)
                m=json.loads(meta.read_text());adapter_peaks.append(m['peak_rss_kb'])
                if sys.platform.startswith('linux'):
                    assert m['peak_rss_source']=='linux_proc_self_status_VmHWM'
                    assert 0<m['peak_rss_kb']<64*1024
        print(json.dumps({'status':'passed','image_peak_rss_kib':peaks,'pre_exec_allocation_mib':[0,192],'shared_key_points':4,'adapter_image_peak_rss_kib':adapter_peaks}))
if __name__=='__main__':main()
