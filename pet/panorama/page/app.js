/* 配置全景的页面程序：start(G) 把一份图画出来，并接好页面上的交互。
   数据从哪来不归这里管——离线快照把它嵌在页面里，本机服务的页面向 /api/graph 要（见 boot.js）。
   这里没有任何功能名和界面文字：版面、走线只按图的结构算，文字都在 G.strings 里。
   四步各一个模块：layout（版面）→ roads（走线）→ draw（画）→ interact（交互）。 */
import {layout} from './layout.js';
import {roads} from './roads.js';
import {draw} from './draw.js';
import {interact} from './interact.js';

/* kept 是上一张图的 capture() 结果：有它就是「数据换了，原地重画」，没有就是第一次画。
   返回的 view：select(id) 选中一个节点；openSettings(组) 打开那一组设置；capture() 记下用户正看着什么；dispose() 摘掉这一次挂的监听。
   重画的顺序固定是：kept = view.capture() → view.dispose() → view = start(新数据, kept)。
   api 是「带着令牌向本机服务要东西」的函数（boot.js 给）；离线快照没有服务，不给，页面上要问服务的功能就停用。 */
export function start(G, kept, api) {
const M = layout(G);
const E = roads(M);
const view = interact(M, E, draw(M, E, !!kept, !!api), kept, api);
return {width: M.W, height: M.H, select: view.select, openSettings: view.openSettings, capture: view.capture, dispose: view.dispose};
}
