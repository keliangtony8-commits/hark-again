import { appName } from "../../brand";
import { useServerVersion } from "../../hooks/useServerVersion";
import { server } from "../../lib/api";
import { clientVersionLabel } from "../../lib/version";
import { Page, PageHeader, stagger } from "../../ui/kit";

/** 关于（v2.81，= App about_screen.dart）：这是什么 + 版本 + 连的哪台服务器。
 *  v2.86：名字和版本只来自 src/brand.ts（brand/sync.py 生成）；服务器版本（GET /api/version）单独一行，部署落后一眼看出；
 *  低于服务器要求的最低版本时“版本”行写“请更新”。 */
export default function AboutScreen() {
  const sv = useServerVersion();
  const raw = server.get() || location.origin;
  let host = raw;
  try { host = new URL(raw).host || raw; } catch { /* 不是完整 URL 就原样显示 */ }
  const row = (title: string, value: string) => (
    <div className="row"><div className="row-body"><div className="row-title">{title}</div></div><span className="row-value">{value}</span></div>
  );
  return (
    <Page header={<PageHeader title="关于" back />}>
      <p className="desc sub-line enter">{appName} 是你自己的私人助手：跑在你自己的服务器上，用你自己的模型密钥，数据只在那里。</p>
      <div className="list enter" style={stagger(1)}>
        {row("版本", clientVersionLabel(sv))}
        {row("服务器", host)}
        {sv && row("服务器版本", sv.version)}
      </div>
    </Page>
  );
}
