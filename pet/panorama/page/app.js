/* 配置全景的页面程序：start(G) 把一份图画出来，并接好页面上的交互。
   数据从哪来不归这里管——离线快照把它嵌在页面里，本机服务的页面向 /api/graph 要（见 boot.js）。
   这里没有任何功能名和界面文字：版面、走线只按图的结构算，文字都在 G.strings 里。
   四步各一个模块：layout（版面）→ roads（走线）→ draw（画）→ interact（交互）。 */
import {layout} from './layout.js';
import {roads} from './roads.js';
import {draw} from './draw.js';
import {interact} from './interact.js';

export function start(G) {
const M = layout(G);
const E = roads(M);
interact(M, E, draw(M, E));
return {width: M.W, height: M.H};
}
