"""Native-key replay and controlled-clamp invariants on adversarial point clouds."""
from pathlib import Path
import csv,json,subprocess,sys,tempfile
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))

def read(path):
    with path.open() as f:return list(csv.DictReader(f))

def main():
    binary=Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(dir=ROOT/'build',prefix='clamp_test_') as name:
        work=Path(name);rng=np.random.default_rng(2026)
        clean=rng.normal(size=(128,3))*[10,2,.4]
        clean=np.vstack([clean,clean[:3]])
        contaminated=np.vstack([clean,[[200.,150.,90.],[-180.,-220.,-150.]]*12])
        paths=[]
        for i,points in enumerate([clean,contaminated]):
            path=work/f'D{i}.csv';np.savetxt(path,points,delimiter=',',fmt='%.17g');paths.append(path)
        command=[str(binary),'--output',str(work/'out')]
        for p in paths:command += ['--input',str(p)]
        subprocess.run(command,check=True,capture_output=True)
        meta=json.loads((work/'out/embedding.json').read_text());assert len(meta['extended_bits'])==3
        for i,points in enumerate([clean,contaminated]):
            grid=read(work/f'out/D{i}.grid.csv');assert len(grid)==len(points)
            orders={arm:read(work/f'out/D{i}.{arm}.order.csv') for arm in ['native','tie_projected','clamp_on','clamp_off']}
            for arm,rows in orders.items():assert sorted(int(r['raw_index']) for r in rows)==list(range(len(points)))
            original={int(r['raw_index']):r['key'] for r in orders['native']}
            assert all(original[int(r['raw_index'])]==r['key'] for r in orders['tie_projected'])
            assert [r['key'] for r in orders['native']]==[r['key'] for r in orders['tie_projected']]
            on={int(r['raw_index']):r['key'] for r in orders['clamp_on']}
            off={int(r['raw_index']):r['key'] for r in orders['clamp_off']}
            for row in grid:
                id_=int(row['raw_index']);changed=any(row['q'+str(j)]!=row['unclipped'+str(j)] for j in range(3))
                assert (on[id_]!=off[id_])==changed
        assert subprocess.run(command,capture_output=True).returncode!=0
        bad=work/'bad.csv';np.savetxt(bad,contaminated[::-1],delimiter=',')
        assert subprocess.run([str(binary),'--output',str(work/'badout'),'--input',str(paths[0]),'--input',str(bad)],capture_output=True).returncode!=0
    print('PASS: native key/order replay, tuple/key intervention, fixed-key tie scope, duplicate IDs, prefix rejection')
if __name__=='__main__':main()
