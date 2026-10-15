// v2.90.2 连接器页“服务器还差一步”的引导弹层（= App features/me/oauth_setup_sheet.dart，同一份文案）：只给部署者看，
// 告诉他在服务器上配一次 OAuth 应用。内容全部来自 GET /api/connectors 每项的 setup（去哪注册、回调地址、.env 变量名），
// 这里不自己拼；完整步骤在仓库 docs/oauth-setup.md。
import type { Connector } from "../../lib/types";
import CopyButton from "../../ui/CopyButton";
import { IconExternal } from "../../ui/icons";
import { ListGroup, ListRow, Sheet, stagger } from "../../ui/kit";
import "./me.css";

/** 重建读 .env 的两个容器（与 docs/oauth-setup.md 第 4 步一致）。 */
export const OAUTH_RESTART_COMMAND = "docker compose up -d --force-recreate backend worker";

const hostOf = (url: string) => { try { return new URL(url).host; } catch { return url; } };

function Code({ text, label }: { text: string; label: string }) {
  return (
    <div className="setup-code">
      {/* 只在 / 和空格处换行（网址、命令不从单词中间断开）；复制的仍是原文 */}
      <code>{text.split(/(?<=\/)/).map((part, i) => <span key={i}>{i > 0 && <wbr />}{part}</span>)}</code>
      <CopyButton text={text} label={label} />
    </div>
  );
}

export default function OAuthSetupSheet({ missing, onClose }: { missing: Connector[]; onClose: () => void }) {
  const names = missing.map((c) => c.name).join(" / ");
  const callback = missing.map((c) => c.setup?.callback ?? "").find(Boolean) ?? "";
  const env = missing.flatMap((c) => c.setup?.env ?? []).join("\n");
  let n = 0;
  return (
    <Sheet title={`配置 ${names} 授权`} onClose={onClose}>
      <p className="desc">一键授权由服务器上的 OAuth 应用完成。按以下三步配置一次，之后在连接器页点一下即可连接。</p>

      <div className="section-title setup-step"><span>1 · 创建 OAuth 应用</span></div>
      <ListGroup enter={n++}>
        {missing.map((c) => (
          <ListRow key={c.id} href={c.setup?.console} icon={<IconExternal />} title={`在 ${c.name} 开发者后台创建`} sub={hostOf(c.setup?.console ?? "")} />
        ))}
      </ListGroup>

      <div className="section-title setup-step"><span>2 · 回调地址（两处填写同一个）</span></div>
      <div className="enter" style={stagger(n++)}><Code text={callback} label="复制回调地址" /></div>

      <div className="section-title setup-step"><span>3 · 填写服务器 .env 并重启</span></div>
      <div className="enter" style={stagger(n++)}><Code text={env} label="复制变量名" /></div>
      <div className="enter setup-gap" style={stagger(n++)}><Code text={OAUTH_RESTART_COMMAND} label="复制重启命令" /></div>

      <p className="setup-note">
        {missing.some((c) => c.id === "google") ? "Google 还需开启 Gmail、日历、云端硬盘接口，并把你的账号加入测试用户。" : ""}
        完整步骤见仓库中的 docs/oauth-setup.md。
      </p>
    </Sheet>
  );
}
