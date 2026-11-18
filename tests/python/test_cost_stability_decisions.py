"""Requirement/budget scenarios must reject ineligible policies and allow no solution."""
import csv,json,tempfile,unittest
from pathlib import Path
from experiments.runners.run_cost_stability_scenarios import analyze,write

class CostStabilityDecisionTest(unittest.TestCase):
    def test_worst_condition_and_budget_control_eligibility(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'run_manifest.json').write_text('{}')
            rows=[]
            for policy,cost,tau in [('PCA:C3',1.0,.4),('RCH:C3',4.0,.9)]:
                for d in range(5):
                    rows.append(dict(geometry_id='fixture',seed='0',policy=policy,condition=f'D{d}',sort_seconds=cost,kendall_tau=1.0 if d==0 else (tau if d==4 else .99)))
            write(root/'measurements.csv',rows);analyze(root,root/'analysis')
            data=list(csv.DictReader((root/'analysis/scenario_summary.csv').open()))
            def cell(tau,budget):return next(r for r in data if float(r['tau_min_scenario'])==tau and int(r['budget_multiplier'])==budget)
            self.assertEqual(cell(.75,5)['rch_selected'],'1')
            self.assertEqual(cell(.75,2)['none_selected'],'1')
            self.assertEqual(cell(.95,20)['none_selected'],'1')
            self.assertEqual(cell(.9,5)['rch_only_eligible'],'1')
if __name__=='__main__':unittest.main()
