import { useEffect, useState } from "react";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import Login from "./features/auth/Login";
import ChatScreen from "./features/chat/ChatScreen";
import ComputerScreen from "./features/computer/ComputerScreen";
import HomeScreen from "./features/home/HomeScreen";
import ConnectorsScreen from "./features/me/ConnectorsScreen";
import MemoryScreen from "./features/me/MemoryScreen";
import MeScreen from "./features/me/MeScreen";
import SkillsScreen from "./features/me/SkillsScreen";
import TaskDetailScreen from "./features/me/TaskDetailScreen";
import TasksScreen from "./features/me/TasksScreen";
import VaultScreen from "./features/me/VaultScreen";
import WalletScreen from "./features/me/WalletScreen";
import SecurityScreen from "./features/me/SecurityScreen";
import FeedbackScreen from "./features/me/FeedbackScreen";
import FeedbackDetail from "./features/me/FeedbackDetail";
import PagesScreen from "./features/me/PagesScreen";
import UsageScreen from "./features/me/UsageScreen";
import MeHub from "./features/me/MeHub";
import PreferencesScreen from "./features/me/PreferencesScreen";
import AboutScreen from "./features/me/AboutScreen";
import ProjectScreen from "./features/projects/ProjectScreen";
import ProjectsScreen from "./features/projects/ProjectsScreen";
import { auth, onUnauthorized } from "./lib/api";
import AppShell from "./shell/AppShell";
import { DialogHost } from "./ui/dialog";

/** 路由表 = App 的地图。新增页面只在这里登记一行。HashRouter 兼容安卓 WebView。
 *  “我的”不是栏目（顶栏头像进入），外壳只在 / /chat /projects 上显示浮动顶栏（shell/TopBar isShellRoot）。 */
export default function App() {
  const [authed, setAuthed] = useState(!!auth.get());
  useEffect(() => onUnauthorized(() => { auth.clear(); setAuthed(false); }), []);
  if (!authed) return <><Login onDone={() => setAuthed(true)} /><DialogHost /></>;

  return (
    <HashRouter>
      <DialogHost />
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<HomeScreen />} />
          <Route path="chat" element={<ChatScreen />} />
          <Route path="projects" element={<ProjectsScreen />} />
          <Route path="projects/:pid" element={<ProjectScreen />} />
          <Route path="projects/:pid/computer" element={<ComputerScreen />} />
          <Route path="me" element={<MeScreen />} />
          <Route path="me/memory" element={<MemoryScreen />} />
          <Route path="me/tasks" element={<TasksScreen />} />
          <Route path="me/tasks/:id" element={<TaskDetailScreen />} />
          <Route path="me/skills" element={<SkillsScreen />} />
          <Route path="me/connectors" element={<ConnectorsScreen />} />
          <Route path="me/vault" element={<VaultScreen />} />
          <Route path="me/wallet" element={<WalletScreen />} />
          <Route path="me/security" element={<SecurityScreen />} />
          <Route path="me/feedback" element={<FeedbackScreen />} />
          <Route path="me/feedback/:id" element={<FeedbackDetail />} />
          <Route path="me/computer" element={<ComputerScreen />} />
          <Route path="me/pages" element={<PagesScreen />} />
          <Route path="me/usage" element={<UsageScreen />} />
          <Route path="me/profile" element={<MeHub hub="profile" />} />
          <Route path="me/accounts" element={<MeHub hub="accounts" />} />
          <Route path="me/preferences" element={<PreferencesScreen />} />
          <Route path="me/about" element={<AboutScreen />} />
          {/* v0.47 前的“设置”页已拆进“我的”和“用量”：旧链接回到我的 */}
          <Route path="me/settings" element={<Navigate to="/me" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
