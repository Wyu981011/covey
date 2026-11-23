#!/usr/bin/env node
// 头像只有一份：核心的 covey/assets/avatars/。网页要用的 client/src/cv/avatars/ 是从那里拷来的（目录在 .gitignore 里）。
// dev、build 和部署前（package.json 的 pre 钩子、deploy/selfhost/build.sh、deploy/miaoda/deploy.py）都先跑本脚本。
// 在 covey 仓库里：把核心那份拷过来（有变化才写）。
// 不在仓库里（自托管构建和妙搭应用仓库里是拷过去的 web/，没有 covey/）：目录已经在就什么也不做，不在就报错。
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SRC = path.resolve(WEB, '..', 'covey', 'assets', 'avatars');
const DST = path.join(WEB, 'client', 'src', 'cv', 'avatars');

const pngs = (dir) => (fs.existsSync(dir) ? fs.readdirSync(dir).filter((n) => n.endsWith('.png')) : []);

if (fs.existsSync(SRC)) {
  fs.mkdirSync(DST, { recursive: true });
  let copied = 0;
  for (const name of fs.readdirSync(SRC)) {
    if (!name.endsWith('.png') && name !== 'LICENSE.md') continue;
    const from = path.join(SRC, name);
    const to = path.join(DST, name);
    if (fs.existsSync(to) && fs.readFileSync(to).equals(fs.readFileSync(from))) continue;
    fs.copyFileSync(from, to);
    copied += 1;
  }
  for (const name of fs.readdirSync(DST)) { // 核心里删掉的图，这边也删
    if (!fs.existsSync(path.join(SRC, name))) fs.rmSync(path.join(DST, name));
  }
  if (copied) console.log(`[sync-avatars] ${copied} file(s) copied from ${SRC}`);
} else if (pngs(DST).length === 0) {
  console.error(`[sync-avatars] 没有头像：${SRC} 和 ${DST} 都不存在。从 covey 仓库里的 web/ 跑，或把 covey/assets/avatars/ 的图拷到 ${DST}`);
  process.exit(1);
}
