# 更新记录 / Changelog

格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。还没有发布过版本号，改动都记在 Unreleased 里。
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). No version has been released yet; everything goes under Unreleased.

## [Unreleased]

### Added 新增

- 仓库门面：`CODE_OF_CONDUCT.md`、`CHANGELOG.md`、`THIRD_PARTY_NOTICES.md`；`pyproject.toml` 补全项目元数据。
- CI 增加网页工作台（`web/`）的检查和构建作业，以及 Python 3.13（见下），并开启 Dependabot 每周检查 GitHub Actions 和 `web/` 的 npm 依赖。
- `scripts/README.md`：列出 `scripts/` 里每个脚本的用途，分使用者用和维护者用。

### Changed 变更

- `scripts/setup_harness_bridge.sh` 标为已弃用，运行时在 stderr 提示改用 `./install`。
- 头像图片只在 `covey/assets/avatars/` 留一份，网页构建、开发和部署前由脚本拷入。
- `web/.env` 改名为 `web/.env.example`，构建和部署时按它生成 `.env`。
- 根目录和 `web/` 的 `.gitignore` 补上环境文件、密钥、构建产物和编辑器缓存。
- README 的快速开始补上 Node.js 和 npm 的前提。

### Added (English)

- Project files: `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, `THIRD_PARTY_NOTICES.md`; complete project metadata in `pyproject.toml`.
- CI: a job that lints, tests and builds the web workbench (`web/`), Python 3.13 in the test matrix when it passes, and weekly Dependabot checks for GitHub Actions and the npm dependencies of `web/`.
- `scripts/README.md`: what each script in `scripts/` is for, split into user and maintainer scripts.

### Changed (English)

- `scripts/setup_harness_bridge.sh` is deprecated and says so on stderr; use `./install`.
- The avatar images live only in `covey/assets/avatars/`; scripts copy them into `web/` before its dev, build and deploy.
- `web/.env` is now `web/.env.example`; builds and deploys generate `.env` from it.
- `.gitignore` (root and `web/`) now covers environment files, keys, build output and editor caches.
- The README quick start lists Node.js and npm as requirements.
