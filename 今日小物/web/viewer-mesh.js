"use strict";

// The slicer exports binary STL with 50 bytes per triangular face.
const maxTriangles = 500000;
const maxBytes = 84 + 50 * maxTriangles;

self.onmessage = async ({data}) => {
  try {
    const url = new URL(data, self.location.href);
    if (url.origin !== self.location.origin) throw new Error("只能打开本机模型。");
    const response = await fetch(url, {mode: "same-origin", redirect: "error"});
    if (!response.ok) throw new Error("模型文件读取失败，请检查本机应用后重试。");
    const size = Number(response.headers.get("Content-Length"));
    if (!Number.isInteger(size) || size < 134 || size > maxBytes) throw new Error("模型文件大小异常。");
    const bytes = await response.arrayBuffer();
    if (bytes.byteLength !== size) throw new Error("模型文件未传输完整。");
    const stl = new DataView(bytes);
    const count = stl.getUint32(80, true);
    if (!count || 84 + count * 50 !== size) throw new Error("无法读取这个切片模型的三角面。");

    const positions = new Float32Array(count * 9);
    const low = [Infinity, Infinity, Infinity];
    const high = [-Infinity, -Infinity, -Infinity];
    let index = 0;
    for (let face = 0; face < count; face++) {
      let offset = 84 + face * 50 + 12;
      for (let vertex = 0; vertex < 3; vertex++) {
        for (let axis = 0; axis < 3; axis++, offset += 4) {
          const value = stl.getFloat32(offset, true);
          if (!Number.isFinite(value)) throw new Error("模型含有异常坐标。");
          positions[index++] = value;
          low[axis] = Math.min(low[axis], value);
          high[axis] = Math.max(high[axis], value);
        }
      }
    }
    const center = low.map((value, axis) => (value + high[axis]) / 2);
    let radiusSquared = 0;
    for (let i = 0; i < positions.length; i += 3) {
      const x = positions[i] - center[0], y = positions[i + 1] - center[1], z = positions[i + 2] - center[2];
      radiusSquared = Math.max(radiusSquared, x * x + y * y + z * z);
    }
    if (!radiusSquared) throw new Error("模型缺少立体尺寸。");
    self.postMessage({positions, center, radius: Math.sqrt(radiusSquared)}, [positions.buffer]);
  } catch (error) {
    self.postMessage({error: error instanceof TypeError ? "无法连接本机应用，请检查后重试。" : error.message});
  }
};
