import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";

const chalk = "#eddfc3", gold = "#d2a35f", wood = "#885d48", blue = "#7395a0", green = "#79947a", roof = "#b96d56";
const painted = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: .82 });
const models = new Map();

function makeMiniature(kind) {
  if (models.has(kind)) return new THREE.Mesh(models.get(kind), painted);
  const pieces = [];
  function add(geo, p, color, rotation = 0) {
    const g = geo.toNonIndexed();
    const c = new THREE.Color(color), a = new Float32Array(g.attributes.position.count * 3);
    for (let i = 0; i < a.length; i += 3) c.toArray(a, i);
    g.setAttribute("color", new THREE.BufferAttribute(a, 3));
    g.rotateZ(rotation).translate(...p);
    pieces.push(g);
    geo.dispose();
  }
  function box(x,y,z,w,h,d,c,r) { add(new THREE.BoxGeometry(w,h,d),[x,y,z],c,r); }
  function disc(x,y,z,rt,rb,h,c,n=18) { add(new THREE.CylinderGeometry(rt,rb,h,n),[x,y,z],c); }
  const sign = (x,z) => {box(x,.5,z,.09,1,.12,wood);box(x,1,z,.82,.47,.12,green);};
  const window = (x,y,z) => {box(x,y,z,.42,.46,.07,wood);box(x,y,z+.045,.32,.34,.04,"#f7c780");};
  if(kind==="waysign"){
    box(0,.23,0,.095,.46,.095,wood);
    box(0,.46,0,.70,.36,.092,"#a47c55");box(0,.46,.052,.61,.275,.018,"#c6a57a");
    for(const x of [-.25,.25])disc(x,.47,.066,.018,.018,.04,wood,6);
    box(-.035,.50,.067,.32,.015,.012,"#755a44");box(-.075,.425,.067,.24,.015,.012,"#755a44");
  }else if(kind==="mailbox"){
    box(0,.36,0,.105,.72,.11,wood);box(0,.70,0,.48,.27,.34,green);
    box(0,.865,0,.52,.065,.37,blue);box(0,.71,.177,.365,.19,.025,"#9caf96");
    box(0,.756,.194,.255,.028,.016,"#554f42");box(.272,.87,0,.025,.28,.038,wood);
    box(.295,.97,.04,.04,.11,.13,roof);
  }else if (kind === "workshop") {
    disc(0,.10,0,1.45,1.54,.20,chalk,36); disc(0,.25,0,1.25,1.35,.14,gold,36);
    box(0,1.31,-.05,1.78,1.96,1.38,chalk);
    box(0,1.14,.67,1.22,1.68,.07,wood); box(0,1.11,.73,.99,1.53,.05,"#d78642");
    box(0,1.06,.77,.76,1.38,.04,"#ffcc7a"); box(0,1.23,.80,.045,1.05,.025,"#b9824b");
    box(0,1.54,.81,.76,.05,.028,"#b9824b");
    box(-.52,2.39,0,1.17,.15,1.73,green,.31); box(.52,2.39,0,1.17,.15,1.73,green,-.31);
    box(0,1.99,.88,1.25,.11,.45,wood);
    for (const x of [-.76,.76]) {box(x,1.42,.77,.125,.35,.14,gold);box(x,1.42,.86,.084,.23,.07,"#ffe4a6");}
  } else if(kind === "index-cards" || kind === "press-sheets" || kind === "cue-tools") {
    // 主件已有实物模型时，只把随手使用的纸张、翻页笔等留在小边台上。
    box(0,.50,0,1.36,.11,.95,wood);
    for(const x of [-.54,.54]) for(const z of [-.36,.36]) box(x,.23,z,.09,.46,.09,green);
    if(kind === "cue-tools") {
      add(new THREE.CylinderGeometry(.10,.10,.84,14),[-.06,.67,-.19],chalk,Math.PI/2);
      box(-.20,.60,.19,.44,.07,.11,wood);box(.36,.61,.19,.35,.09,.14,blue);
    } else {
      const newspaper=kind==="press-sheets";
      for(let i=0;i<7;i++)box(-.16,.57+i*.037,0,newspaper?.89:.66,.033,newspaper?.75:.52,i%3?chalk:"#c7bfa9");
      if(newspaper) {box(-.35,.83,-.07,.37,.025,.21,blue);box(.39,.59,0,.065,.05,.72,gold);}
      else {for(let i=0;i<3;i++)box(-.16,.817,.12-i*.083,.41,.011,.016,blue);}
    }
  } else if(kind === "thermos") {
    disc(-.18,.46,0,.21,.24,.90,green);disc(-.18,.94,0,.17,.14,.09,gold);
    disc(-.18,1.05,0,.115,.12,.16,wood);
    add(new THREE.TorusGeometry(.19,.033,5,14),[.015,.66,0],wood);
    disc(.43,.13,.12,.145,.135,.26,chalk);
  } else if(kind === "linen") {
    for(let i=0;i<4;i++)box(-.13,.09+i*.16,0,1.03,.155,.73,[green,chalk,blue,chalk][i]);
    box(-.31,.69,.02,.42,.055,.48,gold,-.07);box(.10,.69,.02,.42,.055,.48,chalk,.07);
  } else if(kind === "parcels") {
    for(const [x,y,z,w,h,d] of [[-.30,.26,0,.83,.52,.66],[-.31,.73,-.03,.68,.42,.56],[.52,.21,.18,.56,.42,.48]]) {
      box(x,y,z,w,h,d,"#be9367");box(x,y+h/2+.01,z,.08,.018,d,wood);
      box(x+.16*w,y+.08*h,z+d/2+.009,.30*w,.2*h,.014,chalk);
    }
  } else if(kind === "waiting-chairs") {
    for(const x of [-.37,.37]){
      box(x,.45,.02,.57,.095,.52,wood);box(x,.77,-.22,.57,.54,.085,green);
      for(const z of [-.16,.2])box(x,.22,z,.36,.44,.08,wood);
    }
    box(.37,.534,.04,.40,.065,.36,gold);box(.37,.575,.055,.32,.025,.27,chalk);
  } else if(kind === "laptop") {
    box(0,.8,0,2.3,.14,1.4,wood);
    for(const x of [-.9,.9]) for(const z of [-.5,.5]) box(x,.36,z,.13,.72,.13,green);
    box(-.32,.92,.18,1.18,.09,.7,blue);box(-.32,1.32,-.15,1.18,.76,.09,green);
    box(-.32,1.32,-.09,1.02,.59,.04,"#e6c995");
    for(let i=0;i<4;i++)box(.67,.91+i*.05,.12,.46,.05,.53,i%2?chalk:gold);
  } else if(kind === "bunk") {
    for(const x of [-.95,.95]) for(const z of [-.47,.47]) box(x,.94,z,.095,1.88,.095,wood);
    for(const y of [.28,1.25]){
      box(0,y,0,2.05,.13,1.03,wood);box(0,y+.12,0,1.89,.14,.90,blue);
      box(-.69,y+.23,0,.38,.11,.74,chalk);box(.27,y+.22,0,1.20,.08,.91,green);
    }
    for(let i=0;i<5;i++) box(.74,.24+i*.29,.54,.39,.058,.075,wood);
    for(const x of [.53,.95]) box(x,.9,.54,.065,1.8,.08,wood);
    disc(-1.3,.37,.12,.14,.16,.74,gold);disc(-1.3,.78,.12,.085,.09,.1,wood);
    // 床边自装的小话筒和独立的圆形防喷网。
    disc(1.32,.05,.16,.20,.24,.10,wood);
    box(1.32,.47,.16,.065,.82,.065,wood);
    disc(1.32,.96,.16,.12,.12,.30,blue,12);
    add(new THREE.TorusGeometry(.16,.022,5,14),[1.32,1.02,.34],wood);
  } else if(kind === "yard") {
    box(0,.85,-.36,2.45,1.70,.38,chalk);
    box(-.08,1.14,-.13,1.35,.79,.12,wood);box(-.08,1.14,-.048,1.22,.66,.06,blue);
    box(-.08,1.14,-.008,.075,.69,.06,wood);box(-.08,.74,-.01,1.55,.12,.42,wood);
    for(const x of [-.40,.28]){
      disc(x,.87,.09,.112,.091,.20,x<0?gold:green);
      add(new THREE.TorusGeometry(.064,.018,5,9),[x+.11,.88,.08],wood);
    }
    for(const [x,y,z,w,h,d] of [[.89,.25,.42,.65,.50,.56],[.87,.67,.42,.56,.34,.51]]){
      box(x,y,z,w,h,d,"#bf9768");box(x,y+h/2+.01,z,.075,.02,d,wood);
    }
    const bx=-.56,bz=.76;
    for(const x of [bx-.42,bx+.42])add(new THREE.TorusGeometry(.26,.041,6,16),[x,.29,bz],wood);
    box(bx,.36,bz,.61,.058,.06,green,.14);box(bx-.16,.48,bz,.055,.42,.06,green,-.52);
    box(bx+.20,.49,bz,.056,.51,.06,green,.50);box(bx+.34,.62,bz,.06,.64,.06,wood,-.24);
    box(bx-.21,.70,bz,.25,.065,.17,wood);box(bx+.43,.78,bz,.30,.18,.23,gold);
  } else if(kind === "metro") {
    for(let i=0;i<5;i++)box(-.34,.07+i*.075,.68-i*.25,1.07,.14+i*.15,.28,chalk);
    for(const x of [-.98,.30]){
      box(x,.69,-.18,.12,1.38,.12,green);box(x,.44,.48,.09,.88,.09,green);
      box(x,.95,.18,.10,.08,.86,green);
    }
    box(-.34,1.5,-.22,1.52,.23,.45,green);box(-.34,1.5,.02,.97,.095,.025,chalk);
    box(.97,1.18,-.46,.85,.65,.11,wood);box(.97,1.18,-.385,.72,.53,.045,blue);
    for(const x of [.73,1.24]){
      box(x,.45,.12,.42,.085,.38,wood);box(x,.66,-.07,.43,.44,.08,green);
      for(const zz of [-.02,.25])box(x,.21,zz,.29,.42,.075,wood);
    }
    box(1.24,.52,.14,.30,.045,.29,gold);
  } else if(kind === "case") {
    box(-.51,.60,0,1.06,1.02,.63,green);
    for(const x of [-.85,-.23]){box(x,.61,.334,.065,.89,.04,gold);disc(x,.08,0,.10,.10,.16,wood);}
    box(-.65,1.31,0,.06,.45,.08,wood);box(-.38,1.31,0,.06,.45,.08,wood);box(-.515,1.52,0,.32,.065,.09,wood);
    for(let i=0;i<3;i++)box(.67,.088+i*.165,.08,.95,.16,.73,[blue,chalk,roof][i]);
    box(.63,.58,.11,.64,.10,.49,chalk,-.09);
  } else if(kind === "printer") {
    box(0,.67,0,2.28,.13,1.38,wood);
    for(const x of [-.85,.85]) for(const z of [-.44,.44]) box(x,.31,z,.13,.62,.13,green);
    box(-.34,1.01,-.08,1.22,.51,.83,blue);box(-.34,1.30,-.18,1.09,.12,.57,chalk);
    box(-.34,1.06,.36,.76,.11,.04,wood);box(-.34,.97,.52,.67,.045,.35,chalk);
    for(let i=0;i<4;i++)box(.69,.76+i*.045,.13,.52,.04,.78,i%2?chalk:"#c5b397");
    box(.7,.98,.13,.38,.025,.25,green);box(.74,.98,-.15,.32,.025,.04,wood);
  } else if (kind === "school" || kind === "dorm" || kind === "home") {
    const dorm = kind === "dorm", home = kind === "home";
    const width = dorm ? 2.6 : 2, h = dorm ? 1.8 : 1.16;
    box(0,h/2,0,width,h,1.14,home ? chalk : "#d0a78a");
    if (home) {box(-.54,h+.18,0,1.20,.18,1.45,roof,.33);box(.54,h+.18,0,1.2,.18,1.45,roof,-.33);}
    else box(0,h+.1,0,width+.2,.2,1.32,green);
    for (const x of (dorm ? [-.9,-.26,.42,.96] : [-.59,.58])) {
      window(x,.68,.59); if(dorm) window(x,1.39,.59);
    }
    if (home) {box(0,.39,.62,.34,.78,.12,wood);sign(1.25,.51);}
    else {box(-.8,.15,.97,1.1,.3,.28,wood); box(-.8,.42,.84,1.1,.27,.12,wood);}
  } else if (kind === "stall" || kind==="counter") {
    for(const x of [-.75,.75]) box(x,.86,0,.08,1.72,.08,wood);
    for(let i=0;i<7;i++) box((i-3)*.26,1.74,.08,.26,.13,1.19,i%2?chalk:roof);
    box(0,.58,.22,1.72,.16,.94,wood);box(0,.29,.28,1.47,.52,.67,green);
    for(let i=0;i<4;i++) box((i-1.5)*.32,.71,.27,.22,.1,.34,i%2?gold:blue);
    if(kind==="stall") {
      box(1.43,.98,0,.95,1.5,.1,wood); box(1.43,.98,.08,.78,1.29,.07,chalk);
      box(1.28,1.16,.13,.26,.35,.04,blue,-.1); box(1.58,.87,.13,.2,.23,.04,roof,.13);
    }
  } else if (kind === "train" || kind === "journey") {
    box(0,.20,0,2.45,.4,.94,chalk);box(0,.77,0,2.24,.76,.89,blue);box(0,1.19,0,2.28,.14,.98,green);
    for(let i=0;i<4;i++) box((i-1.5)*.50,.82,.46,.36,.42,.05,"#ffdc9e");
    for(const x of [-.8,.8]) box(x,.08,0,.38,.16,1.03,wood);
    sign(-1.54,.15);
  } else if(kind === "studio") {
    box(0,.85,0,2.3,.13,1.15,wood);
    for(const x of [-.94,.94]) for(const z of [-.42,.42]) box(x,.4,z,.11,.8,.11,wood);
    box(-.22,.98,-.1,.16,.22,.14,wood); box(-.22,1.34,-.14,1.04,.65,.12,green);
    box(-.22,1.34,-.06,.88,.49,.04,blue); box(.13,.95,.26,.73,.05,.29,chalk);
    disc(.79,1.10,.08,.16,.14,.39,gold);
    add(new THREE.CylinderGeometry(.085,.085,.72,12),[.55,1.01,-.36],chalk,Math.PI/2);
    box(-.82,1.15,.15,.045,.46,.045,wood);disc(-.82,1.43,.15,.10,.10,.24,blue);
    box(-.50,.96,.35,.28,.065,.08,wood);box(-1.4,.42,.61,.66,.12,.68,roof);
    box(-1.4,.67,.93,.66,.52,.11,roof);disc(-1.4,.20,.61,.11,.22,.39,wood);
  } else if(kind === "exam") {
    box(0,.75,0,1.92,.16,1.12,wood);
    for(const x of [-.72,.72]) for(const z of [-.38,.38]) box(x,.35,z,.12,.70,.12,green);
    for(let i=0;i<3;i++) box(-.45,.89+i*.1,0,.58,.09,.63,[gold,blue,chalk][i]);
    box(.48,.87,.15,.59,.04,.6,chalk);disc(.64,1.04,-.23,.13,.12,.39,roof);
  } else {
    // 沿路三种小物：折开的书、灯笼和装信的小木盒。
    if(kind === "help") {
      box(0,.24,0,.70,.47,.49,green);box(0,.53,0,.78,.12,.55,wood);
      box(.07,.69,.04,.46,.29,.06,chalk,-.18);
    } else if(kind === "joy") {
      disc(0,.08,0,.24,.28,.16,wood);disc(0,.41,0,.25,.2,.52,gold,8);disc(0,.73,0,.14,.28,.13,roof,8);
    } else {box(-.18,.12,0,.4,.12,.58,chalk,-.17);box(.18,.12,0,.4,.12,.58,chalk,.17);}
  }
  const geometry = mergeGeometries(pieces);
  pieces.forEach(g => g.dispose());
  models.set(kind, geometry);
  return new THREE.Mesh(geometry, painted);
}

export function miniature(kind) {
  const mesh = makeMiniature(kind);
  mesh.castShadow = mesh.receiveShadow = true;
  return mesh;
}

export function eraMiniature(era, index, featured) {
  const companions = [
    ["laptop-index","index-cards"], ["night-bunk","thermos"], ["open-suitcase","linen"],
    ["paper-noticeboard","counter"], ["delivery-crate","parcels"], ["alley-stairs","waiting-chairs"],
    ["desk-corner","cue-tools"], ["news-printer","press-sheets"],
  ];
  const pair=companions.find(([asset])=>featured.some(item=>item.id==="sc-"+asset && item.placement?.era===era.start));
  if(pair) return miniature(pair[1]);
  const hints = [era.scene_hint || "", era.title || ""];
  const motifs = [[/桌面打印机|叠未折的报纸/,"printer"],[/双层床|热水瓶/,"bunk"],[/手写索引卡|半开的笔记本/,"laptop"],[/拉杆箱|入学指南/,"case"],[/单车|窗边两只杯子/,"yard"],[/地铁出入口|简历夹/,"metro"],[/摊|表白墙|校园卡/,"stall"],[/工位|显示器|传媒|办公桌/,"studio"],[/地铁|胡同|实习/,"train"],[/合租|家|居所|阳台/,"home"],[/宿舍|大一/,"dorm"],[/书桌|笔记|高考后/,"exam"],[/旅|行李|暑假|闯/,"journey"],[/校园|教室|高中/,"school"]];
  for(const hint of hints) { const match = motifs.find(([rx])=>rx.test(hint)); if(match) return miniature(match[1]); }
  return miniature(["school","exam","dorm","journey","stall","home","train","studio"][index%8]);
}
