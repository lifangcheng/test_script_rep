import pandas as pd
import sys
import json

# 设置输出编码
sys.stdout.reconfigure(encoding='utf-8')

# 读取解码后的数据
df = pd.read_parquet('microwave_analysis/MT516 26A V2L 微波炉-20260126170402_CAN/decoded.parquet')

print('数据分析报告')
print('=' * 50)

print(f'数据形状: {df.shape}')
print(f'总数据行数: {len(df)}')
print(f'时间范围: {df["timestamp"].min():.2f} 到 {df["timestamp"].max():.2f} 秒')
print(f'持续时间: {df["timestamp"].max() - df["timestamp"].min():.2f} 秒')

print('\n信号分析:')
print('-' * 30)
signals = df['signal'].unique()
print(f'提取到的信号数量: {len(signals)}')
for signal in signals:
    signal_data = df[df['signal'] == signal]
    print(f'\n信号: {signal}')
    print(f'  数据点数: {len(signal_data)}')
    print(f'  CAN ID: {signal_data["can_id"].iloc[0]} (0x{hex(int(signal_data["can_id"].iloc[0]))})')
    print(f'  消息: {signal_data["message"].iloc[0]}')
    print(f'  值范围: {signal_data["value"].min():.2f} 到 {signal_data["value"].max():.2f}')
    print(f'  平均值: {signal_data["value"].mean():.2f}')

    # 检查单位
    unit = signal_data['unit'].iloc[0] if 'unit' in signal_data.columns else 'N/A'
    if unit and str(unit) != 'nan':
        print(f'  单位: {unit}')

print('\nCAN ID分析:')
print('-' * 30)
can_ids = df['can_id'].unique()
print(f'唯一的CAN ID数量: {len(can_ids)}')
for can_id in can_ids:
    can_data = df[df['can_id'] == can_id]
    print(f'\nCAN ID: {can_id} (0x{hex(int(can_id))})')
    print(f'  信号数量: {len(can_data["signal"].unique())}')
    print(f'  消息: {can_data["message"].iloc[0]}')
    print(f'  数据点数: {len(can_data)}')

print('\n统计分析:')
print('-' * 30)
print('信号统计:')
signal_counts = df['signal'].value_counts()
for signal, count in signal_counts.items():
    print(f'  {signal}: {count} 行 ({count/len(df)*100:.1f}%)')

# 查看报告文件
print('\n' + '=' * 50)
print('异常检测报告:')
try:
    with open('microwave_analysis/MT516 26A V2L 微波炉-20260126170402_CAN/report.json', 'r', encoding='utf-8') as f:
        report = json.load(f)

    print(f'总异常数: {report["stats"]["anomalies"]}')
    print(f'信号数量: {report["stats"]["signals"]}')
    print(f'帧数量: {report["stats"]["frames"]}')

    if report["anomalies"]:
        print('\n检测到的异常:')
        for anomaly in report["anomalies"]:
            print(f'  信号: {anomaly["signal"]}')
            print(f'  严重性: {anomaly["severity"]}')
            print(f'  时间: {anomaly["start_iso"]} 到 {anomaly["end_iso"]}')
            print(f'  持续时长: {anomaly["end"] - anomaly["start"]:.2f} 秒')
            print(f'  CAN ID: {anomaly["can_id_hex"]}')
            print(f'  触发规则: {anomaly["rule_name"]}')
            print('  ---')
except Exception as e:
    print(f'读取报告时出错: {e}')