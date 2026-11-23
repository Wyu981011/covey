# 第三方代码与资源 / Third-party notices

本仓库自己的代码用 [MIT](LICENSE) 许可。下面是仓库里带进来的第三方代码和资源。
Covey's own code is under the [MIT license](LICENSE). The third-party code and assets bundled in this repository are listed below.

| 路径 / Path | 内容 / What | 许可 / License |
| --- | --- | --- |
| `covey/core/qrcodegen.py` | Project Nayuki 的 [QR Code generator library](https://www.nayuki.io/page/qr-code-generator-library)（Python）；许可文本在文件头 / license text in the file header | MIT |
| `covey/core/toml_compat.py` | [tomli](https://github.com/hukkin/tomli) 2.5.0（Taneli Hukkinen），Python 3.10 没有 tomllib 时用它读 TOML；许可文本在文件头 / tomli 2.5.0, the TOML reader used where Python 3.10 has no tomllib; license text in the file header | MIT |
| `web/client/src/cv/fonts/inter-latin-wght-normal.woff2` | 字体 Inter，Copyright (c) 2016 The Inter Project Authors / the Inter font | SIL Open Font License 1.1，全文 / full text: [web/licenses/Inter-OFL.txt](web/licenses/Inter-OFL.txt) |
| `web/client/src/cv/fonts/jetbrains-mono-latin-wght-normal.woff2` | 字体 JetBrains Mono，Copyright 2020 The JetBrains Mono Project Authors / the JetBrains Mono font | SIL Open Font License 1.1，全文 / full text: [web/licenses/JetBrainsMono-OFL.txt](web/licenses/JetBrainsMono-OFL.txt) |
| `covey/assets/avatars/` | 头像：`G-*.png` 取自 DiceBear「Moods」、`M-*.png` 取自 DiceBear「Clay」（CC0）；`butler.png` 由 Gemini 生成；`sea-*.png` 为自绘原创 / avatars: DiceBear "Moods" and "Clay" (CC0), a generated logo, and original drawings | 各文件来源见 / per-file sources: [covey/assets/avatars/LICENSE.md](covey/assets/avatars/LICENSE.md) |
| `web/` 的 npm 依赖 / npm dependencies of `web/` | 不随仓库分发源码，由 `npm ci` 按 [web/package-lock.json](web/package-lock.json) 安装；各包的许可随包分发，依赖清单见 [web/package.json](web/package.json) / not vendored: installed by `npm ci` from the lock file; each package ships its own license | 各包自己的许可 / each package's own license |

网页的字体许可汇总在 [web/licenses/README.md](web/licenses/README.md)。
