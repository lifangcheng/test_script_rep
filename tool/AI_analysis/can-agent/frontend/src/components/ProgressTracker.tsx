import { Card, Progress, Steps, Tag, Typography, Space, Alert, Timeline } from 'antd';
import { 
  CheckCircleOutlined, 
  ClockCircleOutlined, 
  CloseCircleOutlined,
  LoadingOutlined,
  FileTextOutlined,
  SettingOutlined,
  BarChartOutlined,
  RobotOutlined
} from '@ant-design/icons';
import React from 'react';

interface LogEntry {
  stage: string;
  status: 'pending' | 'running' | 'success' | 'failed';
  error?: {
    code: string;
    message: string;
    fix: string;
  };
  timestamp?: number;
}

interface ProgressTrackerProps {
  taskId: string;
  status: string;
  logs: LogEntry[];
  error?: any;
  outputDir?: string;
}

const stageIcons: Record<string, React.ReactNode> = {
  validate_input: <FileTextOutlined />,
  parse_blf: <FileTextOutlined />,
  decode_dbc: <SettingOutlined />,
  build_dataframe: <BarChartOutlined />,
  anomaly_detect: <BarChartOutlined />,
  summarize: <BarChartOutlined />,
  report_generate: <FileTextOutlined />,
  signal_index: <BarChartOutlined />,
  ai_analyze: <RobotOutlined />,
};

const stageNames: Record<string, string> = {
  validate_input: '验证输入',
  parse_blf: '解析BLF文件',
  decode_dbc: 'DBC解码',
  build_dataframe: '构建数据框',
  anomaly_detect: '异常检测',
  summarize: '数据汇总',
  report_generate: '生成报告',
  signal_index: '信号索引',
  ai_analyze: 'AI分析',
};

export default function ProgressTracker({ taskId, status, logs, error, outputDir }: ProgressTrackerProps) {
  // 计算总体进度
  const totalStages = 9;
  const completedStages = logs.filter(log => log.status === 'success').length;
  const progressPercent = Math.round((completedStages / totalStages) * 100);
  
  // 获取当前活动阶段
  const currentStage = logs.find(log => log.status === 'running');

  // 转换日志为时间线格式
  const timelineItems = logs.map((log) => {
    let icon;
    let color;
    
    switch (log.status) {
      case 'success':
        icon = <CheckCircleOutlined />;
        color = 'green';
        break;
      case 'failed':
        icon = <CloseCircleOutlined />;
        color = 'red';
        break;
      case 'running':
        icon = <LoadingOutlined />;
        color = 'blue';
        break;
      default:
        icon = <ClockCircleOutlined />;
        color = 'gray';
    }
    
    return {
      dot: icon,
      color: color,
      children: (
        <div>
          <Typography.Text strong>
            {stageNames[log.stage] || log.stage}
          </Typography.Text>
          <div>
            <Tag color={color === 'green' ? 'success' : color === 'red' ? 'error' : 'processing'}>
              {log.status === 'success' ? '完成' : 
               log.status === 'failed' ? '失败' : 
               log.status === 'running' ? '运行中' : '等待'}
            </Tag>
          </div>
          {log.error && (
            <Alert
              message={log.error.message}
              description={log.error.fix}
              type="error"
              showIcon
              style={{ marginTop: 8, fontSize: 12 }}
            />
          )}
        </div>
      ),
    };
  });

  return (
    <Card 
      title={
        <Space>
          <Typography.Text strong>任务进度</Typography.Text>
          <Tag color={status === 'success' ? 'success' : status === 'failed' ? 'error' : 'processing'}>
            {status === 'success' ? '成功' : 
             status === 'failed' ? '失败' : 
             status === 'running' ? '运行中' : '等待'}
          </Tag>
          <Typography.Text code style={{ fontSize: 12 }}>
            {taskId}
          </Typography.Text>
        </Space>
      }
      extra={
        outputDir && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            输出目录: {outputDir}
          </Typography.Text>
        )
      }
    >
      {/* 总体进度条 */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <Typography.Text>总体进度</Typography.Text>
          <Typography.Text>{progressPercent}%</Typography.Text>
        </div>
        <Progress 
          percent={progressPercent} 
          status={status === 'failed' ? 'exception' : status === 'success' ? 'success' : 'active'}
          strokeColor={status === 'failed' ? '#ff4d4f' : undefined}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
          <Typography.Text type="secondary">
            {completedStages}/{totalStages} 阶段完成
          </Typography.Text>
          {currentStage && (
            <Typography.Text type="secondary">
              当前: {stageNames[currentStage.stage] || currentStage.stage}
            </Typography.Text>
          )}
        </div>
      </div>

      {/* 阶段步骤条 */}
      <div style={{ marginBottom: 24 }}>
        <Typography.Text strong style={{ marginBottom: 16, display: 'block' }}>
          处理阶段
        </Typography.Text>
        <Steps
          current={completedStages}
          status={status === 'failed' ? 'error' : 'process'}
          size="small"
          items={Object.entries(stageNames).map(([key, name]) => {
            const log = logs.find(l => l.stage === key);
            const isCompleted = log?.status === 'success';
            const isFailed = log?.status === 'failed';
            const isRunning = log?.status === 'running';
            
            return {
              title: name,
              icon: stageIcons[key],
              status: isCompleted ? 'finish' : isFailed ? 'error' : isRunning ? 'process' : 'wait',
            };
          })}
        />
      </div>

      {/* 详细时间线 */}
      <div>
        <Typography.Text strong style={{ marginBottom: 16, display: 'block' }}>
          详细日志
        </Typography.Text>
        <Timeline items={timelineItems} />
      </div>

      {/* 错误信息 */}
      {error && (
        <Alert
          message="任务执行失败"
          description={
            <div>
              <p><strong>错误代码:</strong> {error.code}</p>
              <p><strong>错误信息:</strong> {error.message}</p>
              <p><strong>修复建议:</strong> {error.fix}</p>
            </div>
          }
          type="error"
          showIcon
          style={{ marginTop: 16 }}
        />
      )}
    </Card>
  );
}