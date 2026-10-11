import { Page, PageHeader } from "../../ui/kit";
import UsageCard from "./UsageCard";

/** 用量与花费（我的 → 用量卡的“查看用量”，或主页的预算提醒卡）。和 App /me/usage 同一页。 */
export default function UsageScreen() {
  return <Page header={<PageHeader title="用量与花费" back />}><UsageCard /></Page>;
}
