/** v2.15 碰壁条（后端 app/task_wall.py；= App features/me/task_wall.dart WallNotice）：任务 / 面板最近一次运行碰到的障碍。
 *  要你处理的（登录 / 重新连接 / 付费墙）带“去处理”（wall_open → cardTargets 的页面）和“重试”；会自己好的只有说明。
 *  任务详情头卡和 Home 面板卡共用；文案只用服务端给的 wall_label / wall_reason。出现时 rise 动效（.task-pause-note 同款）。 */
import { useNavigate } from "react-router-dom";
import { cardRoute, cardTarget } from "../../lib/cardTargets";
import { wallHint } from "../../lib/taskLabels";
import type { ScheduledTask } from "../../lib/types";
import { IconClock, IconLock } from "../../ui/icons";

export default function WallNotice({ task, onRetry, busy }: { task: ScheduledTask; onRetry?: () => void; busy?: boolean }) {
  const nav = useNavigate();
  if (!task.wall_label) return null;
  const target = task.wall_fixable ? cardTarget(task.wall_open) : undefined;
  return (
    <div className="task-pause-note task-wall" role="status" key={task.wall_label}>
      {task.wall_fixable ? <IconLock /> : <IconClock />}
      <div className="task-wall-body">
        <strong>{task.wall_label}</strong>
        {task.wall_reason && <span className="task-wall-reason">{task.wall_reason}</span>}
        <span className="task-wall-hint">{wallHint(task)}</span>
        {task.wall_fixable && (target || onRetry) && (
          <div className="task-wall-actions">
            {target && <button className="btn btn-ghost btn-sm" onClick={() => nav(cardRoute(target, { task_id: task.id, target: task.wall_open ?? null }))}>
              <target.Icon size={14} />{target.label}</button>}
            {onRetry && <button className="btn btn-ghost btn-sm" disabled={busy} onClick={onRetry}>重试</button>}
          </div>
        )}
      </div>
    </div>
  );
}
