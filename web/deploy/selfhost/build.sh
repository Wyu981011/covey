#!/usr/bin/env bash
# 自托管网页的构建：把这份 web/ 拷到目标目录（不带 node_modules 和构建产物），装依赖，构建服务端和前端，
# 打印 COVEY_WEB_SELFHOST_DIR 该填的路径（<目标目录>/dist-selfhost）。说明见同目录 README.md。
#
# 用法：bash web/deploy/selfhost/build.sh <目标目录（绝对路径）> [--restart]
#   目标目录可以反复用：再跑一次就是升级。package-lock.json 没变时不重装依赖。
#   --restart：构建完让正在跑的网页进程退出，Manager 几秒内拉起新版（没在跑就什么也不做）。
# 要 Node 22 以上和 npm。设了 npm_config_registry 时，依赖从那个源装（锁文件里记的源地址一并换掉）。
set -euo pipefail

say() { printf '%s\n' "$*"; }
die() { printf '出错：%s\n' "$*" >&2; exit 1; }

TARGET="${1:-}"
RESTART=0
[ "${2:-}" = "--restart" ] && RESTART=1
[ -n "$TARGET" ] || die "要给目标目录：bash web/deploy/selfhost/build.sh /absolute/path/to/covey-web"
case "$TARGET" in /*) ;; *) die "目标目录要写绝对路径：$TARGET" ;; esac
TARGET="${TARGET%/}"

WEB="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[ -f "$WEB/package.json" ] && [ -f "$WEB/package-lock.json" ] || die "找不到 web/ 的 package.json：$WEB"
case "$TARGET/" in "$WEB/"*) die "目标目录不能在源码 web/ 里面：$TARGET" ;; esac

command -v node >/dev/null || die "没有 node：先装 Node 22 以上"
command -v npm >/dev/null || die "没有 npm"
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[ "$NODE_MAJOR" -ge 22 ] || die "Node 版本太低（$(node -v)），要 22 以上"

if [ -n "${npm_config_registry:-}" ]; then
  export npm_config_replace_registry_host=always
fi

MARK=".covey-selfhost-build"  # 本脚本建的目录才有它；没有它的非空目录一律不碰，免得写错路径删了别的东西
if [ -d "$TARGET" ] && [ -n "$(ls -A "$TARGET")" ] && [ ! -f "$TARGET/$MARK" ]; then
  die "目标目录不是空的，也不是本脚本建的（没有 $MARK）：$TARGET。换一个新目录"
fi
mkdir -p "$TARGET"
say "1. 拷源码：$WEB → $TARGET"
# 目标目录里除 node_modules 外全部换成这份源码（升级时旧文件、旧构建产物都清掉）。
# data/、logs/ 不动：手工 npm run start:selfhost、没设 COVEY_WEB_DB_DIR 时库就在 data/db（Manager 拉起时库在 Covey 数据根的 web/db，不在这里）
find "$TARGET" -mindepth 1 -maxdepth 1 ! -name node_modules ! -name "$MARK" ! -name data ! -name logs -exec rm -rf {} +
(cd "$WEB" && tar --exclude=./node_modules --exclude='./dist' --exclude='./dist-*' --exclude=./data --exclude=./logs \
  --exclude=./.env.local -cf - .) | (cd "$TARGET" && tar -xf -)
printf '%s\n' "covey web selfhost build; source $WEB" > "$TARGET/$MARK"

STAMP="$TARGET/node_modules/.covey-lock.sha256"
# 用 node 算 sha256：macOS 默认没有 sha256sum
LOCK_SUM="$(node -e 'process.stdout.write(require("crypto").createHash("sha256").update(require("fs").readFileSync(process.argv[1])).digest("hex"))' "$TARGET/package-lock.json")"
if [ -d "$TARGET/node_modules" ] && [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$LOCK_SUM" ]; then
  say "2. 依赖：package-lock.json 没变，不重装"
else
  say "2. 装依赖：npm ci（第一次要几分钟）"
  (cd "$TARGET" && npm ci --no-audit --no-fund)
  printf '%s\n' "$LOCK_SUM" > "$STAMP"
fi

say "3. 构建：npm run build:selfhost"
(cd "$TARGET" && NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=4096}" npm run -s build:selfhost)
DIST="$TARGET/dist-selfhost"
[ -f "$DIST/server/selfhost/main.js" ] || die "构建后没有 $DIST/server/selfhost/main.js"
[ -f "$DIST/client/index.html" ] || die "构建后没有 $DIST/client/index.html"

if [ "$RESTART" = 1 ]; then
  ENTRY="$DIST/server/selfhost/main.js"
  PIDS="$(pgrep -f -- "$ENTRY" || true)"
  if [ -n "$PIDS" ]; then
    say "4. 让正在跑的网页进程退出（pid $PIDS），Manager 几秒内拉起新版"
    # 只发给命令行正好是这个入口的进程；它收到 SIGTERM 会先关库再退出
    for pid in $PIDS; do kill -TERM "$pid" 2>/dev/null || true; done
  else
    say "4. 没有在跑的网页进程，不用重启"
  fi
fi

say ""
say "构建好了。COVEY_WEB_SELFHOST_DIR=$DIST"
say "第一次装：python3 -B -m covey.service.web_selfhost --dir $DIST   （在 Covey 代码目录里跑，按它打印的开关设服务清单）"
say "升级：加 --restart 重跑本脚本，或手动让网页进程退出（Manager 会拉起新版）"
