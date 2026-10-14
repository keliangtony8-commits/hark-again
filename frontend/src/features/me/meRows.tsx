import type { ComponentType } from "react";
import { Link } from "react-router-dom";
import { IconChevron } from "../../ui/icons";

/** “我的”系列页的一行（v2.81，= App RowTile 不带副标题）：图标 + 标题 + 行尾当前值 + 箭头。说明只写在子页顶部一次。 */
export type MeRow = { to: string; icon: ComponentType; title: string; value?: string };

export function MeRows({ rows }: { rows: MeRow[] }) {
  return (
    <div className="list">
      {rows.map(({ to, icon: Icon, title, value }) => (
        <Link key={to} to={to} className="row">
          <span className="row-icon"><Icon /></span>
          <div className="row-body"><div className="row-title">{title}</div></div>
          {value && <span className="row-value">{value}</span>}
          <span className="row-trail"><IconChevron /></span>
        </Link>
      ))}
    </div>
  );
}
