# Tree benchmark evidence

All queries match the original-ID brute-force oracle and agree across backends and blocks.

Warm page-file DFS-layout effects and resident-memory native-tree effects are reported in separate groups. IDs are materialized and sorted inside query timing; hashing and oracle checks are outside. Counters unavailable from CGAL are null, not zero. RSS is process cumulative, including data and oracle. Preparation excludes input load and earlier SFC ordering; source ordering times remain in the run manifest. These measurements do not establish complete preparation amortization, physical cold-disk I/O, or DBMS performance. CGAL point/node allocation size is not measured. Intervals describe queries on each fixed dataset, not new independent scenes.
