# Minister Portrait Files

Put manually generated portrait images in this folder:

- `frontend/public/portraits/`

The frontend now loads local files only and does **not** call `/api/minister/portrait`.

Required filenames:

- `xu_da.png` -> 徐达
- `chang_yuchun.png` -> 常遇春
- `li_shanchang.png` -> 李善长
- `liu_ji.png` -> 刘基
- `song_lian.png` -> 宋濂
- `zhu_sheng.png` -> 朱升
- `tang_he.png` -> 汤和
- `hu_dahai.png` -> 胡大海

Recommended image specs:

- Aspect ratio: `1:1`
- Size: `512x512` or `1024x1024`
- Format: `PNG`

Current status:

- The 8 placeholder PNGs present in this folder were self-drawn via
  `scripts/generate_portrait_placeholders.py` (ink-wash gradient + cinnabar
  seal frame + kai-style name, 512x512). Original in-house assets only.
- Replace them with AI-generated or hand-drawn portraits at any time; keep
  the exact filenames above.

Source note:

- `frontend/public/seal.mp3`（EdictWritingPanel 用印音效，实际为 8kHz WAV 数据、
  ~0.1s 短促提示音）为本项目既有占位素材、未经改动，来源与崇祯素材无关。
