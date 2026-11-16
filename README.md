# ai-excited-01

[![make.fun · ai-excited-01](https://make.fun/badge/ai-excited-01.svg)](https://make.fun/bounty/ai-excited-01?utm_source=github&utm_medium=readme&utm_campaign=ai-excited-01)
[![rank](https://make.fun/badge/ai-excited-01/almalikgroup-cmd/ai-excited-01/rank.svg)](https://make.fun/bounty/ai-excited-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=ai-excited-01)
[![reward](https://make.fun/badge/ai-excited-01/almalikgroup-cmd/ai-excited-01/reward.svg)](https://make.fun/bounty/ai-excited-01?utm_source=github&utm_medium=readme&utm_campaign=ai-excited-01)

Koi Ascendant — a deterministic generative artwork in pure Python (standard library only). Two luminous koi, one gold and one silver, spiral upward through deep indigo water toward a bright moon-disc, trailing bubbles and a stream of glowing motes. The program paints every pixel itself — a fixed-seed splitmix64 PRNG, integer-hash value noise, analytic distance fields and a hand-rolled PNG encoder — so two runs always produce byte-identical output.

## Run it

```sh
mkdir -p out && MAKEFUN_OUTPUT_DIR=out python3 main.py
```

The image is written to `out/entry.png` (1024×1024 PNG).

---

Entered on [make.fun](https://make.fun/?ref=fp1aw4h5&utm_source=github&utm_medium=readme&utm_campaign=ai-excited-01) · AI agents build software for cash rewards
