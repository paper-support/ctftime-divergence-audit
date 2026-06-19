# AN2 — GCI-2024 ordinal-respecting trend test (revision)

- n = 42 main-sample countries; tiers present [1, 2, 3, 4]
- Group sizes Tier1..Tier4: [26, 10, 5, 1]

- **Kendall tau-b** (tie-aware, inverted tier vs performance composite) = **+0.076** (concordant 265, discordant 216)
- **Somers' D** (performance | tier) = **+0.102**
- **Jonckheere-Terpstra** trend test J = 216 (null E[J] = 240); permutation two-sided p = **0.548** (5,000 permutations, seed 42)

Interpretation: even under tie-aware/ordinal-respecting tests, GCI-2024 tier shows no monotonic association with country-attributed CTF performance; the 2024 vintage is a coarse complementary check, with main inferences resting on the cardinal 2017/2020 vintages.
