// Space annotation after netresearch/herdr-bg-activity: links to the services
// started in a space (":5175", "contexts ↗"), the symbols of its agents and how many
// background tasks they still own ("✻ ⧗ 1"). The data comes from the shared keys
// agents-bg publishes (see mods/agents-bg/bg.js).

import { div } from "gpui-kit";
import { h_flex } from "gpui-base";
import { agents, shared } from "herdr";

const SHARED_KEY = "bg-activity.info";
const LINKS_KEY = "bg-activity.links";
const SYMBOL = { claude: "✻", "claude-code": "✻", pi: "π" };

// "⧗ 1 monitor, 2 shells" -> 3: the leading number of each comma-separated part.
function bgCount(bg) {
  if (!bg) return 0;
  return bg.replace("⧗", "").split(",").reduce((n, part) => n + (Number.parseInt(part.trim(), 10) || 0), 0);
}

function linkChips(t, list, id) {
  return (list ?? []).map((l) =>
    div().id(`link-${id}-${l.key}`).flex_none().text_color(t.accent).cursor_pointer()
      .hover((s) => s.text_color(t.foreground).underline())
      .tooltip(`${l.title}\nclick: open in browser`)
      .on_click((_e, cx) => { cx.stop_propagation(); cx.open_url(l.url); })
      .child(l.text));
}

export function spaceTail(t, spaceId) {
  const list = agents().filter((a) => a.space === spaceId);
  const info = shared(SHARED_KEY) ?? {};
  const links = shared(LINKS_KEY)?.bySpace?.[spaceId] ?? [];
  const symbols = [...new Set(list.map((a) => SYMBOL[a.app] ?? SYMBOL[a.program?.key] ?? null).filter(Boolean))];
  symbols.sort((a, b) => a.localeCompare(b));
  const count = list.reduce((n, a) => n + bgCount(info[a.address]?.bg), 0);
  if (!symbols.length && !count && !links.length) return null;
  return h_flex().flex_none().gap(5).items_center().text_size(11.5)
    .children(linkChips(t, links, spaceId))
    .when(symbols.length > 0, (el) => el.child(div().text_color(t.dim).child(symbols.join(" "))))
    .when(count > 0, (el) => el.child(div().text_color(t.ansi3).child(`⧗ ${count}`)));
}
