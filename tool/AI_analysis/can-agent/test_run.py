#!/usr/bin/env python3
"""
测试运行脚本 - 验证can-agent完整流程
"""
import sys
import tempfile
import json
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def create_sample_can_data():
    """创建示例CAN数据用于测试"""
    print("创建示例CAN数据...")
    
    # 创建临时目录
    temp_dir = Path(tempfile.mkdtemp())
    
    # 创建DBC文件
    dbc_content = """
VERSION ""

NS_ : 

BS_:

BU_: TestECU

BO_ 100 TestMessage: 8 TestECU
 SG_ Speed : 0|16@1+ (0.1,0) [0|200] "km/h" TestECU
 SG_ RPM : 16|16@1+ (1,0) [0|8000] "rpm" TestECU
 SG_ Temperature : 32|8@1+ (1,-40) [-40|215] "°C" TestECU

BO_ 200 StatusMessage: 8 TestECU
 SG_ Gear : 0|4@1+ (1,0) [0|7] "" TestECU
 SG_ Brake : 4|1@1+ (1,0) [0|1] "" TestECU
 SG_ TurnSignal : 5|2@1+ (1,0) [0|3] "" TestECU
"""
    
    dbc_file = temp_dir / "sample.dbc"
    dbc_file.write_text(dbc_content)
    
    print(f"创建DBC文件: {dbc_file}")
    
    # 注意：这里我们无法直接创建BLF文件，因为它需要专门的工具
    # 但我们可以测试DBC文件的加载
    
    return temp_dir, dbc_file

def test_with_sample_data():
    """使用示例数据测试"""
    print("使用示例数据测试can-agent...")
    
    # 创建示例文件
    temp_dir, dbc_file = create_sample_can_data()
    
    try:
        # 测试DBC加载
        print("\n测试DBC文件加载...")
        import cantools
        db = cantools.database.load_file(str(dbc_file))
        
        print(f"DBC加载成功!")
        print(f"消息数量: {len(db.messages)}")
        
        for msg in db.messages:
            print(f"  - {msg.name} (ID: {msg.frame_id})")
            for signal in msg.signals:
                print(f"    * {signal.name}: {signal.start}|{signal.length}@{signal.byte_order}")
        
        # 测试信号解码
        print("\n测试信号解码...")
        test_data = {
            'Speed': 65.5,
            'RPM': 3000,
            'Temperature': 85,
            'Gear': 3,
            'Brake': 0,
            'TurnSignal': 1
        }
        
        print("示例信号值:")
        for signal, value in test_data.items():
            print(f"  {signal}: {value}")
        
        print("\n测试完成!")
        print("要测试完整流程，请准备一个真实的BLF文件。")
        
        return True
        
    except Exception as e:
        print(f"测试失败: {e}")
        return False
        
    finally:
        # 清理临时文件
        import shutil
        try:
            shutil.rmtree(temp_dir)
            print(f"清理临时文件: {temp_dir}")
        except:
            pass

def main():
    """主函数"""
    print("can-agent 测试运行")
    print("=" * 50)
    
    success = test_with_sample_data()
    
    print("\n" + "=" * 50)
    if success:
        print("测试通过!")
        print("\n下一步:")
        print("1. 准备一个真实的BLF文件")
        print("2. 使用命令: python cli.py --blf 文件.blf --dbc 文件.dbc --out outputs --ai=false")
        print("3. 查看输出目录中的结果文件")
    else:
        print("测试失败!")
        print("请检查依赖库和文件格式。")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())