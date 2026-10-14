import { useCallback, useRef, useState } from "react";
import { setSolid, useLook } from "../../lib/look";
import { APPEARANCES, setAppearance, useAppearance } from "../../lib/theme";
import { Page, PageHeader, Segmented, Toggle, stagger } from "../../ui/kit";
import { Avatar } from "../../ui/glass";
import AvatarColorPop from "./AvatarColorPop";
import ReplyLanguageRow from "./ReplyLanguageRow";
import "./me.css";

/** 偏好设置（v2.81，= App preferences_screen.dart）：外观 · 减少透明度 · 回复语言。原来摊在“我的”页上，收进这一页。
 *  电脑端屏幕宽，外观/语言仍用分段按钮一眼选（App 是一行 + 动作单选）。头像颜色：行尾小头像，点开同一个色盘弹层。 */
export default function PreferencesScreen() {
  const appearance = useAppearance();
  const { solid } = useLook();
  const [pop, setPop] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const closePop = useCallback(() => setPop(false), []);
  return (
    <Page header={<PageHeader title="偏好设置" back />}>
      <p className="desc sub-line enter">界面的样子和我回你的语言，改了立刻生效。</p>
      <div className="list enter" style={stagger(1)}>
        <div className="row me-appearance"><div className="row-body"><div className="row-title">外观</div></div>
          <Segmented label="外观" value={appearance} options={APPEARANCES} onChange={setAppearance} /></div>
        <div className="row"><div className="row-body"><div className="row-title">减少透明度</div></div>
          <Toggle on={solid} onChange={setSolid} label="减少透明度" /></div>
        <div className="row pref-avatar"><div className="row-body"><div className="row-title">头像颜色</div></div>
          <div className="pref-avatar-box" ref={box}>
            <Avatar onClick={() => setPop((v) => !v)} label="换头像颜色" />
            {pop && <AvatarColorPop onClose={closePop} boundary={box} />}
          </div></div>
        <ReplyLanguageRow />
      </div>
    </Page>
  );
}
