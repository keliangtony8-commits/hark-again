import { PLAN_MODE_OFF, PLAN_MODE_ON } from "../../lib/planReview";
import { IconMap } from "../../ui/icons";

/** 计划模式开关（v1.71，= App PlanModeChip）：关着只是一枚淡色图标，开着显示“计划”并用强调底（和非默认模型同一规则）。
 *  状态归 useChat（planMode / setPlanMode）；方案被批准后服务器推 conversation.mode，钮自己关掉。 */
export default function PlanModeChip({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  return (
    <button type="button" className={`model-chip plan-chip${on ? " strong is-on" : ""}`} aria-pressed={on}
      aria-label={on ? PLAN_MODE_ON : PLAN_MODE_OFF} title={on ? PLAN_MODE_ON : PLAN_MODE_OFF} onClick={() => onChange(!on)}>
      <span key={String(on)} className="model-chip-label"><IconMap size={14} />{on && <span className="chip-text">计划</span>}</span>
    </button>
  );
}
