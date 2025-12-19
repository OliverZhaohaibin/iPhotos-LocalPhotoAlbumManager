## 2024-02-14 - Optimizing Glob Expansion
**Learning:** Python's `fnmatch` and regex compilation can be surprisingly expensive in tight loops (e.g., scanning 100k files). Pre-computing or caching intermediate steps like glob expansion yields significant gains.
**Action:** When scanning large file sets, always move constant work (like regex compilation or glob expansion) out of the loop. Use `functools.lru_cache` for expensive string processing functions that are called repeatedly with the same inputs.
