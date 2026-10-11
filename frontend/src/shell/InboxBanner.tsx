import { useNavigate } from "react-router-dom";
import { useInbox } from "../hooks/useInbox";
import { IconChevron, IconInbox, IconSpark } from "../ui/icons";

/** 来了新报告/新建议时从顶部滑下的横幅。点开 = 读掉并打开它；4 秒后自动收起。 */
export default function InboxBanner() {
  const { banner, dismissBanner, markRead } = useInbox();
  const nav = useNavigate();
  if (!banner) return null;
  const report = banner.kind === "report";
  const open = () => {
    dismissBanner();
    markRead([banner.id]);
    if (banner.conversation_id) nav("/chat", { state: { open: banner.conversation_id } });
    else nav("/");
  };
  return (
    <button key={banner.id} className="inbox-banner glass raised" onClick={open}>
      <span className="row-icon">{report ? <IconInbox /> : <IconSpark />}</span>
      <span className="inbox-banner-body">
        <span className="inbox-banner-kind">{report ? "新报告" : "新建议"}</span>
        <span className="inbox-banner-title">{banner.title}</span>
      </span>
      <IconChevron />
    </button>
  );
}
