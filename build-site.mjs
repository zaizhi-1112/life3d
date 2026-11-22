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

const html = await readFile(join(island, "web", "index.html"), "utf8");
await writeFile(join(output, "index.html"), html
  .replace('<html lang="zh-CN">', '<html lang="zh-CN" data-read-only>')
  .replace("<title>二十三</title>", "<title>今日小物：把每一天打印出来，摆进我的人生小岛</title>")
  .replace('id="open-workbench"', 'id="open-workbench" hidden')
  .replaceAll("小屋管理", "小屋与信箱"));

// 记忆宫殿同样只读：能看、能第一人称逛，不能布置，也没有本机工作台入口。
const palace = await readFile(join(island, "web", "palace.html"), "utf8");
await writeFile(join(output, "palace.html"), palace
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
