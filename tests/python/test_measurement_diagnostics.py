import unittest
import numpy as np
from analysis.scripts.analyze_measurement_diagnostics import sharing

class SharingTest(unittest.TestCase):
    def test_identical_coordinates_are_distinct_from_mixed_coordinate_collisions(self):
        x=np.array([[0.,0.,0.],[0.,0.,0.],[1.,0.,0.],[2.,0.,0.]])
        r=sharing(x,np.array([7,7,7,8],dtype=np.uint64))
        self.assertEqual(r['shared_xyz_point_fraction'],.5)
        self.assertEqual(r['shared_key_point_fraction'],.75)
        self.assertEqual(r['mixed_xyz_key_group_point_fraction'],.75)
        self.assertAlmostEqual(r['shared_key_fraction_on_unique_xyz'],2/3)
    def test_duplicate_only_groups_do_not_imply_coordinate_tie_locality_loss(self):
        r=sharing(np.array([[0.,0.,0.],[0.,0.,0.],[1.,1.,1.],[1.,1.,1.]]),np.array([2,2,9,9],dtype=np.uint64))
        self.assertEqual(r['shared_key_point_fraction'],1.)
        self.assertEqual(r['mixed_xyz_key_group_point_fraction'],0.)
        self.assertEqual(r['shared_key_fraction_on_unique_xyz'],0.)
    def test_bad_lengths_fail(self):
        with self.assertRaises(ValueError):sharing(np.zeros((2,3)),np.array([1]))
if __name__=='__main__':unittest.main()
