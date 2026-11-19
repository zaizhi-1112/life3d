import * as THREE from "three";

// 把远处模型同一小格里的顶点合并。近景始终使用原来的展示模型。
export function distantGeometry(source, divisions = 12, minimum = 2000) {
  const positions = source.attributes.position;
  if (!positions || positions.count < minimum || source.groups.length>1) return null;
  source.computeBoundingBox();
  const {min, max} = source.boundingBox;
  const longest = Math.max(max.x - min.x, max.y - min.y, max.z - min.z);
  if (longest <= 0) return null;

  const scale = divisions / longest;
  const stride = divisions + 2;
  const clusters = new Map(), counts = [], sums = [], colors = [];
  const remap = new Uint32Array(positions.count);
  const palette = source.attributes.color;
  for (let i = 0; i < positions.count; i++) {
    const x = positions.getX(i), y = positions.getY(i), z = positions.getZ(i);
    const key = Math.floor((x - min.x) * scale) +
      stride * Math.floor((y - min.y) * scale) + stride * stride * Math.floor((z - min.z) * scale);
    let n = clusters.get(key);
    if (n === undefined) {
      n = counts.length;
      clusters.set(key, n);
      counts.push(0);
      sums.push(0, 0, 0);
      if (palette) colors.push(0, 0, 0);
    }
    remap[i] = n;
    counts[n]++;
    sums[n * 3] += x;
    sums[n * 3 + 1] += y;
    sums[n * 3 + 2] += z;
    if (palette) {
      colors[n * 3] += palette.getX(i);
      colors[n * 3 + 1] += palette.getY(i);
      colors[n * 3 + 2] += palette.getZ(i);
    }
  }
  const indices = source.index?.array, size = indices?.length || positions.count, faces = [], corners = [];
  const textured=!!source.attributes.uv;
  for (let i = 0; i + 2 < size; i += 3) {
    const a = remap[indices ? indices[i] : i];
    const b = remap[indices ? indices[i+1] : i+1];
    const c = remap[indices ? indices[i+2] : i+2];
    if (a !== b && b !== c && a !== c) {
      faces.push(a,b,c);
      if(textured)corners.push(indices?indices[i]:i,indices?indices[i+1]:i+1,indices?indices[i+2]:i+2);
    }
  }
  if (faces.length < 12 || faces.length > size * .73) return null;
  for (let i = 0; i < sums.length; i++) {
    const count = counts[Math.floor(i / 3)];
    sums[i] /= count;
    if (palette) colors[i] /= count;
  }
  const result = new THREE.BufferGeometry();
  if(textured){
    // A UV seam has two texture addresses at the same position. Retain each surviving face's
    // own corner address; averaging these addresses samples an unrelated area of the atlas.
    const cornersToVertex=new Map(),vertices=[],uv=[],vertexColors=[],normals=[],index=[];
    const maps=source.attributes.uv,n=source.attributes.normal;
    for(let i=0;i<corners.length;i++){
      const original=corners[i],cluster=faces[i];
      let vertex=cornersToVertex.get(original);
      if(vertex===undefined){
        vertex=cornersToVertex.size;cornersToVertex.set(original,vertex);
        vertices.push(sums[3*cluster],sums[3*cluster+1],sums[3*cluster+2]);
        uv.push(maps.getX(original),maps.getY(original));
        if(n)normals.push(n.getX(original),n.getY(original),n.getZ(original));
        if(palette)vertexColors.push(palette.getX(original),palette.getY(original),palette.getZ(original));
      }
      index.push(vertex);
    }
    result.setAttribute("position",new THREE.Float32BufferAttribute(vertices,3));
    result.setAttribute("uv",new THREE.Float32BufferAttribute(uv,2));
    if(palette)result.setAttribute("color",new THREE.Float32BufferAttribute(vertexColors,3));
    result.setIndex(index);
    if(n)result.setAttribute("normal",new THREE.Float32BufferAttribute(normals,3));else result.computeVertexNormals();
    return result;
  }
  result.setAttribute("position", new THREE.Float32BufferAttribute(sums, 3));
  if (palette) result.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  result.setIndex(faces);
  result.computeVertexNormals();
  return result;
}
