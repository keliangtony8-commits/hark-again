import { appName } from "../../brand";
import { useServerVersion } from "../../hooks/useServerVersion";
import { server } from "../../lib/api";
import { clientVersionLabel } from "../../lib/version";
import { ListGroup, ListRow, Page, PageHeader, PageIntro } from "../../ui/kit";

/** 关于（v2.81，= App about_screen.dart）：这是什么 + 版本 + 连的哪台服务器。
 *  v2.86：名字和版本只来自 src/brand.ts（brand/sync.py 生成）；服务器版本（GET /api/version）单独一行，部署落后一眼看出；
 *  低于服务器要求的最低版本时“版本”行写“请更新”。 */
export default function AboutScreen() {
  const sv = useServerVersion();
  const raw = server.get() || location.origin;
  let host = raw;
  try { host = new URL(raw).host || raw; } catch { /* 不是完整 URL 就原样显示 */ }
  return (
    <Page header={<PageHeader title="关于" back />}>
      <PageIntro line={`${appName} 是你自己的私人助手：运行在你自己的服务器上，用你自己的模型密钥，数据只在那里。`} />
      <ListGroup enter={1}>
        <ListRow spot="version" title="版本" value={clientVersionLabel(sv)} />
        <ListRow title="服务器" value={host} />
        {sv && <ListRow title="服务器版本" value={sv.version} />}
        <ListRow title="字体" value="MiSans（小米）" />
      </ListGroup>
    </Page>
  );
}
