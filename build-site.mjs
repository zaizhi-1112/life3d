import { copyFile, cp, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL(".", import.meta.url));
const island = join(root, "二十三");
const output = join(root, "public");

await mkdir(output, { recursive: true });
const files = [
  "style.css", "people-manager.css", "world.js", "island-panels.js",
  "island-scenes.js", "exhibit-detail.js", "people-manager.js",
  "asset-manager.js", "asset-manager.css", "ocean.js", "sound.js",
  "palace.js", "palace-furniture.js", "palace.css",
];
await Promise.all(files.map(file => copyFile(join(island, "web", file), join(output, file))));
await cp(join(island, "web", "vendor", "three"), join(output, "vendor", "three"), { recursive: true });

// 右下角的 GitHub 仓库入口，两个公开页面都带。
const repoLink = '<a class="repo-link" href="https://github.com/zaizhi-1112/life3d" target="_blank" rel="noopener" aria-label="打开这个项目的 GitHub 仓库">'
  + '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>'
  + 'GitHub 仓库</a>';
const withRepo = page => page.replace("</body>", repoLink + "\n</body>");

const html = await readFile(join(island, "web", "index.html"), "utf8");
await writeFile(join(output, "index.html"), withRepo(html)
  .replace('<html lang="zh-CN">', '<html lang="zh-CN" data-read-only>')
  .replace("<title>二十三</title>", "<title>今日小物：把每一天打印出来，摆进我的人生小岛</title>")
  .replace('id="open-workbench"', 'id="open-workbench" hidden')
  .replaceAll("小屋管理", "小屋与信箱"));

// 记忆宫殿同样只读：能看、能第一人称逛，不能布置，也没有本机工作台入口。
const palace = await readFile(join(island, "web", "palace.html"), "utf8");
await writeFile(join(output, "palace.html"), withRepo(palace)
  .replace('<html lang="zh-CN">', '<html lang="zh-CN" data-read-only>')
  .replace('<title>记忆宫殿 · 二十三</title>', '<title>记忆宫殿 · 今日小物</title>')
  .replace('id="open-workbench"', 'id="open-workbench" hidden')
  .replace('id="open-shelf"', 'id="open-shelf" hidden'));

async function copyDemoFile(source, kind, extension) {
  const relative = source.replace(/^demo\//, "");
  if (!new RegExp(`^${kind}/[a-z0-9_-]+\\.${extension}$`, "i").test(relative)) {
    throw new Error(`无效的演示资源路径 ${relative}`);
  }
  await copyFile(join(island, "demo", relative), join(output, relative));
  return "/" + relative;
}

for (const subdirectory of ["assets", "data", "models", "photos"]) {
  await mkdir(join(output, subdirectory), { recursive: true });
}
for (const file of await readdir(join(island, "assets"))) {
  if (file.endsWith(".glb")) {
    await copyFile(join(island, "assets", file), join(output, "assets", file));
  }
}

const world = JSON.parse(await readFile(join(island, "demo", "world.json"), "utf8"));
for (const group of ["exhibits", "sculptures", "houses"]) {
  world[group] = await Promise.all(world[group].map(async ({
    original, photo_file, photo_url, model, ...row
  }) => ({
    ...row,
    model: await copyDemoFile(model, "models", "(?:glb|stl)"),
    ...(photo_file ? {photo_url: await copyDemoFile(photo_file, "photos", "(?:jpg|jpeg|png|webp)")} : {}),
  })));
}
await writeFile(join(output, "data", "world.json"), JSON.stringify(world));
