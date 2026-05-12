#!/usr/bin/env python3
"""
快速测试脚本 - 验证can-agent基本功能
"""
import sys
import tempfile
import json
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def create_test_files():
    """创建测试用的BLF和DBC文件"""
    print("创建测试文件...")
    
    # 创建临时目录
    temp_dir = Path(tempfile.mkdtemp())
    
    # 创建一个简单的DBC文件内容
    dbc_content = """
VERSION ""

NS_ : 

BS_:

BU_: TestECU

BO_ 100 TestMessage: 8 TestECU
 SG_ TestSignal1 : 0|8@1+ (1,0) [0|255] "" TestECU
 SG_ TestSignal2 : 8|8@1+ (1,0) [0|255] "" TestECU

BO_ 200 AnotherMessage: 8 TestECU
 SG_ AnotherSignal : 0|16@1+ (0.1,-50) [-50|150] "km/h" TestECU
"""
    
    dbc_file = temp_dir / "test.dbc"
    dbc_file.write_text(dbc_content)
    
    print(f"创建DBC文件: {dbc_file}")
    print(f"临时目录: {temp_dir}")
    
    return temp_dir, dbc_file

def test_dbc_loading(dbc_file):
    """测试DBC文件加载"""
    print(f"\n测试DBC文件加载...")
    
    try:
        import cantools
        db = cantools.database.load_file(str(dbc_file))
        
        print(f"DBC加载成功!")
        print(f"消息数量: {len(db.messages)}")
        
        for msg in db.messages:
            print(f"  - {msg.name} (ID: {msg.frame_id})")
            for signal in msg.signals:
                print(f"    * {signal.name}: {signal.start}|{signal.length}@{signal.byte_order}")
        
        return True
        
    except Exception as e:
        print(f"DBC加载失败: {e}")
        return False

def test_ai_service():
    """测试AI服务连接"""
    print(f"\n测试AI服务连接...")
    
    try:
        from core.ai_client import call_chat_completions
        
        # 测试连接
        result = call_chat_completions(
            base_url="http://localhost:8000/v1",
            api_key="",
            model="gpt-3.5-turbo",
            payload={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "test"}],
                "max_tokens": 5
            },
            timeout_s=5
        )
        
        if result.ok:
            print("AI服务连接成功!")
            return True
        else:
            print(f"AI服务连接失败: {result.error}")
            print("这是正常的，如果没有运行AI服务的话")
            return False
            
    except Exception as e:
        print(f"AI服务测试异常: {e}")
        return False

def main():
    """主测试函数"""
    print("can-agent 快速测试开始")
    
    # 创建测试文件
    temp_dir, dbc_file = create_test_files()
    
    try:
        # 测试DBC加载
        dbc_ok = test_dbc_loading(dbc_file)
        
        # 测试AI服务
        ai_ok = test_ai_service()
        
        # 总结
        print(f"\n{'='*50}")
        print("测试结果:")
        print(f"  DBC加载: {'通过' if dbc_ok else '失败'}")
        print(f"  AI服务: {'通过' if ai_ok else '未连接'}")

        print(f"\n下一步:")
        if dbc_ok:
            print("  DBC文件处理正常")
            print("  准备一个真实的BLF文件进行完整测试")
        else:
            print("  需要检查DBC文件格式")

        if not ai_ok:
            print("  如需AI功能，请配置AI服务")
            print("  或者使用 --ai=false 参数禁用AI功能")

        print(f"\n清理临时文件: {temp_dir}")
        
    finally:
        # 清理临时文件
        import shutil
        try:
            shutil.rmtree(temp_dir)
        except:
            pass
    
    return 0

if __name__ == "__main__":
    sys.exit(main())