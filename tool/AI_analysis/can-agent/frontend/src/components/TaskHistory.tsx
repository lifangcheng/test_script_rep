import { Card, List, Tag, Typography, Space, Button, Empty, Tooltip } from 'antd';
import { 
  HistoryOutlined, 
  DeleteOutlined, 
  EyeOutlined,
  ClockCircleOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined
} from '@ant-design/icons';
import { useAppStore, type TaskStatus } from '../store/appStore';
import { useNavigate } from 'react-router-dom';

export default function TaskHistory() {
  const { taskHistory, clearHistory, setCurrentTask } = useAppStore();
  const navigate = useNavigate();

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'success':
        return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
      case 'failed':
        return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
      case 'running':
        return <LoadingOutlined style={{ color: '#1890ff' }} />;
      default:
        return <ClockCircleOutlined style={{ color: '#d9d9d9' }} />;
    }
  };

  const getStatusTag = (status: string) => {
    const colorMap: Record<string, string> = {
      success: 'success',
      failed: 'error',
      running: 'processing',
      pending: 'default',
    };
    
    const textMap: Record<string, string> = {
      success: '成功',
      failed: '失败',
      running: '运行中',
      pending: '等待',
    };
    
    return (
      <Tag color={colorMap[status] || 'default'}>
        {textMap[status] || status}
      </Tag>
    );
  };

  const formatTime = (timestamp?: number) => {
    if (!timestamp) return '未知时间';
    return new Date(timestamp).toLocaleString('zh-CN');
  };

  const handleViewTask = (task: TaskStatus) => {
    setCurrentTask(task);
    navigate('/tasks');
  };

  if (taskHistory.length === 0) {
    return (
      <Card 
        title={
          <Space>
            <HistoryOutlined />
            <span>任务历史</span>
          </Space>
        }
      >
        <Empty 
          description="暂无任务历史记录" 
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      </Card>
    );
  }

  return (
    <Card 
      title={
        <Space>
          <HistoryOutlined />
          <span>任务历史</span>
          <Tag color="blue">{taskHistory.length} 个任务</Tag>
        </Space>
      }
      extra={
        <Button 
          type="text" 
          danger 
          icon={<DeleteOutlined />}
          onClick={clearHistory}
          size="small"
        >
          清空历史
        </Button>
      }
    >
      <List
        itemLayout="horizontal"
        dataSource={taskHistory}
        renderItem={(task) => (
          <List.Item
            actions={[
              <Tooltip title="查看详情">
                <Button 
                  type="text" 
                  icon={<EyeOutlined />}
                  onClick={() => handleViewTask(task)}
                  size="small"
                />
              </Tooltip>
            ]}
          >
            <List.Item.Meta
              avatar={getStatusIcon(task.status)}
              title={
                <Space>
                  <Typography.Text code style={{ fontSize: 12 }}>
                    {task.task_id.slice(0, 8)}...
                  </Typography.Text>
                  {getStatusTag(task.status)}
                </Space>
              }
              description={
                <div>
                  <div style={{ marginBottom: 4 }}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      创建时间: {formatTime(task.created_at)}
                    </Typography.Text>
                  </div>
                  {task.output_dir && (
                    <div>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        输出目录: {task.output_dir}
                      </Typography.Text>
                    </div>
                  )}
                  {task.error && (
                    <div style={{ marginTop: 4 }}>
                      <Typography.Text type="danger" style={{ fontSize: 12 }}>
                        错误: {task.error.message || '未知错误'}
                      </Typography.Text>
                    </div>
                  )}
                </div>
              }
            />
          </List.Item>
        )}
      />
    </Card>
  );
}