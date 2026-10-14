import { server } from "../../lib/api";
import { Page, PageHeader, stagger } from "../../ui/kit";

/** 关于（v2.81，= App about_screen.dart）：这是什么 + 连的哪台服务器 + 版本（构建时 VITE_APP_VERSION，没给就不显示）。 */
const version = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env?.VITE_APP_VERSION ?? "";

export default function AboutScreen() {
  const raw = server.get() || location.origin;
  let host = raw;
  try { host = new URL(raw).host || raw; } catch { /* 不是完整 URL 就原样显示 */ }
  return (
    <Page header={<PageHeader title="关于" back />}>
      <p className="desc sub-line enter">你自己的私人助手：跑在你自己的服务器上，用你自己的模型密钥，数据只在那里。</p>
      <div className="list enter" style={stagger(1)}>
        {version && <div className="row"><div className="row-body"><div className="row-title">版本</div></div><span className="row-value">{version}</span></div>}
        <div className="row"><div className="row-body"><div className="row-title">服务器</div></div><span className="row-value">{host}</span></div>
      </div>
    </Page>
  );
}
