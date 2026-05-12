import { Layout, Menu, Typography, Badge, Space, Tag } from "antd";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import { 
  DashboardOutlined, 
  PlayCircleOutlined, 
  FileTextOutlined, 
  BarChartOutlined, 
  RobotOutlined,
  GlobalOutlined
} from "@ant-design/icons";

import DashboardPage from "./pages/DashboardPage";
import TasksPage from "./pages/TasksPage";
import ReportPage from "./pages/ReportPage";
import SignalsPage from "./pages/SignalsPage";
import AiReportPage from "./pages/AiReportPage";
import { useAppStore } from "./store/appStore";

const { Header, Content, Sider } = Layout;

function useSelectedKey() {
  const loc = useLocation();
  if (loc.pathname.startsWith("/tasks")) return "tasks";
  if (loc.pathname.startsWith("/report")) return "report";
  if (loc.pathname.startsWith("/signals")) return "signals";
  if (loc.pathname.startsWith("/ai")) return "ai";
  return "dashboard";
}

export default function App() {
  const selected = useSelectedKey();
  const { currentTask, taskHistory } = useAppStore();

  // 计算活动任务数量
  const activeTasksCount = taskHistory.filter(t => t.status === 'running').length;
  const totalTasksCount = taskHistory.length;

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider breakpoint="lg" collapsedWidth={0}>
        <div style={{ padding: 16 }}>
          <Typography.Title level={4} style={{ color: "white", margin: 0 }}>
            CAN Agent
          </Typography.Title>
          <Typography.Text style={{ color: "rgba(255,255,255,0.7)" }}>
            LangGraph Pipeline
          </Typography.Text>
        </div>
        
        {/* 全局状态指示器 */}
        <div style={{ 
          padding: "0 16px 16px", 
          borderBottom: "1px solid rgba(255,255,255,0.1)",
          marginBottom: 16
        }}>
          <Space direction="vertical" size={4} style={{ width: "100%" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <Typography.Text style={{ color: "rgba(255,255,255,0.7)", fontSize: 12 }}>
                任务状态
              </Typography.Text>
              <Badge count={activeTasksCount} size="small" />
            </div>
            
            {currentTask && (
              <div style={{ 
                background: "rgba(255,255,255,0.1)", 
                borderRadius: 6, 
                padding: 8,
                marginTop: 4
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <Typography.Text style={{ color: "white", fontSize: 12 }} code>
                    {currentTask.task_id.slice(0, 8)}...
                  </Typography.Text>
                  <Tag 
                    color={
                      currentTask.status === 'success' ? 'success' : 
                      currentTask.status === 'failed' ? 'error' : 
                      currentTask.status === 'running' ? 'processing' : 'default'
                    }
                    style={{ fontSize: 10, margin: 0 }}
                  >
                    {currentTask.status === 'success' ? '成功' : 
                     currentTask.status === 'failed' ? '失败' : 
                     currentTask.status === 'running' ? '运行中' : '等待'}
                  </Tag>
                </div>
                {currentTask.status === 'running' && currentTask.logs && (
                  <div style={{ marginTop: 4 }}>
                    <div style={{ 
                      background: "rgba(255,255,255,0.2)", 
                      borderRadius: 3, 
                      height: 4,
                      overflow: "hidden"
                    }}>
                      <div style={{
                        background: "#1890ff",
                        height: "100%",
                        width: `${Math.round((currentTask.logs.filter(l => l.status === 'success').length / 9) * 100)}%`,
                        transition: "width 0.3s ease"
                      }} />
                    </div>
                    <Typography.Text style={{ color: "rgba(255,255,255,0.7)", fontSize: 10 }}>
                      {currentTask.logs.filter(l => l.status === 'success').length}/9 阶段完成
                    </Typography.Text>
                  </div>
                )}
              </div>
            )}
            
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
              <Typography.Text style={{ color: "rgba(255,255,255,0.5)", fontSize: 10 }}>
                总任务: {totalTasksCount}
              </Typography.Text>
              <Typography.Text style={{ color: "rgba(255,255,255,0.5)", fontSize: 10 }}>
                活动: {activeTasksCount}
              </Typography.Text>
            </div>
          </Space>
        </div>

        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selected]}
          items={[
            { 
              key: "dashboard", 
              label: <Link to="/">仪表板</Link>,
              icon: <DashboardOutlined />
            },
            { 
              key: "tasks", 
              label: (
                <Space>
                  <Link to="/tasks">任务管理</Link>
                  {activeTasksCount > 0 && (
                    <Badge count={activeTasksCount} size="small" />
                  )}
                </Space>
              ),
              icon: <PlayCircleOutlined />
            },
            { 
              key: "report", 
              label: <Link to="/report">分析报告</Link>,
              icon: <FileTextOutlined />
            },
            { 
              key: "signals", 
              label: <Link to="/signals">信号数据</Link>,
              icon: <BarChartOutlined />
            },
            { 
              key: "ai", 
              label: <Link to="/ai">AI报告</Link>,
              icon: <RobotOutlined />
            },
          ]}
        />
      </Sider>
      <Layout>
        <Header style={{ 
          background: "white", 
          display: "flex", 
          alignItems: "center", 
          justifyContent: "space-between",
          padding: "0 24px"
        }}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            CAN数据分析平台
          </Typography.Title>
          <Space>
            <GlobalOutlined />
            <Typography.Text type="secondary">
              基于LangGraph的智能分析管道
            </Typography.Text>
          </Space>
        </Header>
        <Content style={{ padding: 24, background: "#f5f5f5" }}>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/tasks" element={<TasksPage />} />
            <Route path="/report" element={<ReportPage />} />
            <Route path="/signals" element={<SignalsPage />} />
            <Route path="/ai" element={<AiReportPage />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  );
}