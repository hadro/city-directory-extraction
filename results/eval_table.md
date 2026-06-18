### Eval comparison — macro-F1 (avg over present fields) (higher is better)
| eval set | gliner-medium | gemini-3.1-flash-lite | qwen-2b | qwen-0.8b-yaml | qwen-0.8b-yaml-fixed |
|---|---|---|---|---|---|
| ftd | — | — | — | — | 0.387 |
| lain | — | — | — | — | 0.675 |
| minneapolis | — | — | — | — | 0.592 |
| nyu | 0.381 | 0.672 | 0.281 | 0.358 | 0.760 |
| tulsa | — | — | — | — | 0.791 |

### Eval comparison — micro-F1 (frequency-weighted) (higher is better)
| eval set | gliner-medium | gemini-3.1-flash-lite | qwen-2b | qwen-0.8b-yaml | qwen-0.8b-yaml-fixed |
|---|---|---|---|---|---|
| ftd | — | — | — | — | 0.360 |
| lain | — | — | — | — | 0.655 |
| minneapolis | — | — | — | — | 0.650 |
| nyu | 0.594 | 0.910 | 0.375 | 0.473 | 0.755 |
| tulsa | — | — | — | — | 0.774 |

### Eval comparison — whole-row EM% (higher is better)
| eval set | gliner-medium | gemini-3.1-flash-lite | qwen-2b | qwen-0.8b-yaml | qwen-0.8b-yaml-fixed |
|---|---|---|---|---|---|
| ftd | — | — | — | — | 0.6 |
| lain | — | — | — | — | 15.6 |
| minneapolis | — | — | — | — | 12.2 |
| nyu | 8.0 | 70.0 | 0.4 | 4.0 | 25.8 |
| tulsa | — | — | — | — | 32.8 |
