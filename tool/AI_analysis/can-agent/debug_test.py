#!/usr/bin/env python3
"""
调试脚本 - 测试can-agent的各个组件
"""
import sys
import json
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from core.blf_reader import read_blf
from core.dbc_decoder import decode_with_dbc
from core.types import CoreResult
import pandas as pd


def test_blf_reading(blf_path: str) -> bool:
    """测试BLF文件读取"""
    print(f"\n=== 测试BLF读取: {blf_path} ===")
    
    if not Path(blf_path).exists():
        print(f"BLF文件不存在: {blf_path}")
        return False
    
    try:
        # 测试读取前100条消息
        result = read_blf(blf_path, max_msgs=100)
        
        if not result.ok:
            print(f"BLF读取失败: {result.error}")
            return False

        messages = result.value
        print(f"成功读取 {len(messages)} 条CAN消息")
        
        if messages:
            print(f"第一条消息: {messages[0]}")
            print(f"最后一条消息: {messages[-1]}")

            # 统计CAN ID分布
            can_ids = [msg.can_id for msg in messages]
            unique_ids = set(can_ids)
            print(f"唯一CAN ID数量: {len(unique_ids)}")
            print(f"CAN ID示例: {list(unique_ids)[:10]}")
        
        return True
        
    except Exception as e:
        print(f"BLF读取异常: {e}")
        return False


def test_dbc_decoding(blf_path: str, dbc_path: str) -> bool:
    """测试DBC解码"""
    print(f"\n=== 测试DBC解码 ===")
    print(f"BLF: {blf_path}")
    print(f"DBC: {dbc_path}")
    
    if not Path(dbc_path).exists():
        print(f"DBC文件不存在: {dbc_path}")
        return False
    
    try:
        # 先读取一些BLF消息
        blf_result = read_blf(blf_path, max_msgs=50)
        if not blf_result.ok:
            print(f"无法读取BLF用于测试: {blf_result.error}")
            return False

        raw_msgs = blf_result.value
        print(f"准备解码 {len(raw_msgs)} 条消息")
        
        # 测试DBC解码
        decode_result = decode_with_dbc(dbc_path, raw_msgs)
        
        if not decode_result.ok:
            print(f"DBC解码失败: {decode_result.error}")
            return False

        df = decode_result.value
        print(f"成功解码，得到 {len(df)} 行数据")
        
        if not df.empty:
            print(f"DataFrame列: {list(df.columns)}")
            print(f"唯一信号: {df['signal'].nunique()}")
            print(f"信号示例: {df['signal'].unique()[:10]}")
            print(f"前5行数据:")
            print(df.head())
        
        return True
        
    except Exception as e:
        print(f"DBC解码异常: {e}")
        return False


def test_ai_config() -> bool:
    """测试AI配置"""
    print(f"\n=== 测试AI配置 ===")
    
    try:
        from core.ai_client import call_chat_completions
        
        # 测试默认配置
        test_payload = {
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 10
        }
        
        result = call_chat_completions(
            base_url="http://localhost:8000/v1",
            api_key="",
            model="gpt-3.5-turbo",
            payload=test_payload,
            timeout_s=10
        )
        
        if result.ok:
            print("AI服务连接成功")
            return True
        else:
            print(f"AI服务连接失败: {result.error}")
            print("这是正常的，如果没有运行AI服务的话")
            return False
            
    except Exception as e:
        print(f"AI配置测试异常: {e}")
        return False


def main():
    """主测试函数"""
    print("can-agent 调试测试开始")
    
    # 检查命令行参数
    if len(sys.argv) < 3:
        print("用法: python debug_test.py <blf_file> <dbc_file>")
        print("示例: python debug_test.py test.blf test.dbc")
        return 1
    
    blf_file = sys.argv[1]
    dbc_file = sys.argv[2]
    
    print(f"BLF文件: {blf_file}")
    print(f"DBC文件: {dbc_file}")
    
    # 执行测试
    tests = [
        ("BLF读取", lambda: test_blf_reading(blf_file)),
        ("DBC解码", lambda: test_dbc_decoding(blf_file, dbc_file)),
        ("AI配置", test_ai_config),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name}测试异常: {e}")
            results.append((test_name, False))
    
    # 输出总结
    print(f"\n{'='*50}")
    print("测试结果总结:")
    for test_name, result in results:
        status = "通过" if result else "失败"
        print(f"  {test_name}: {status}")
    
    # 建议
    print(f"\n建议:")
    if not results[0][1]:  # BLF测试失败
        print("  - 检查BLF文件路径和格式")
        print("  - 确保BLF文件包含有效的CAN数据")

    if not results[1][1]:  # DBC测试失败
        print("  - 检查DBC文件路径和格式")
        print("  - 确保DBC文件中的CAN ID与BLF数据匹配")

    if not results[2][1]:  # AI测试失败
        print("  - 如需AI功能，请配置AI服务")
        print("  - 或者使用 --ai=false 参数禁用AI功能")
    
    return 0 if all(result for _, result in results) else 1


if __name__ == "__main__":
    sys.exit(main())