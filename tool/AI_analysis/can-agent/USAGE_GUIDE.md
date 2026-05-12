# can-agent 使用指南

## 问题诊断与解决

### 🔍 常见问题及解决方案

#### 1. 运行后没有输出

**可能原因：**
- BLF文件路径错误或文件不存在
- DBC文件路径错误或文件不存在
- DBC文件中的CAN ID与BLF数据不匹配
- 依赖库未正确安装

**解决方案：**
```bash
# 1. 检查文件路径
python cli.py --blf "完整路径/文件.blf" --dbc "完整路径/文件.dbc" --out outputs

# 2. 使用调试脚本测试
python debug_test.py "文件.blf" "文件.dbc"

# 3. 检查依赖库
pip list | findstr -i "python-can cantools"
```

#### 2. AI功能无法使用

**可能原因：**
- AI服务未启动
- API端点配置错误
- 网络连接问题

**解决方案：**
```bash
# 1. 禁用AI功能进行测试
python cli.py --blf "文件.blf" --dbc "文件.dbc" --out outputs --ai=false

# 2. 检查AI服务配置
# 默认使用 http://localhost:8000/v1
# 如需修改，请编辑 config/loader.py 中的 DEFAULT_AI_BASE_URL
```

### 🛠️ 调试工具

#### 1. 快速测试脚本
```bash
python quick_test.py
```
测试基本功能，验证DBC文件加载和AI服务连接。

#### 2. 详细调试脚本
```bash
python debug_test.py "文件.blf" "文件.dbc"
```
全面测试BLF读取、DBC解码和AI功能。

### 📋 使用步骤

#### 步骤1：验证环境
```bash
# 检查依赖
pip install -r requirements.txt

# 运行快速测试
python quick_test.py
```

#### 步骤2：准备文件
- 确保BLF文件包含有效的CAN数据
- 确保DBC文件格式正确且与BLF数据匹配

#### 步骤3：运行分析
```bash
# 基本用法（禁用AI）
python cli.py --blf "your_file.blf" --dbc "your_file.dbc" --out outputs --ai=false

# 启用AI功能（需要AI服务）
python cli.py --blf "your_file.blf" --dbc "your_file.dbc" --out outputs --ai
```

#### 步骤4：查看结果
输出文件保存在指定的输出目录中：
- `status.json` - 处理状态和日志
- `decoded.parquet` - 解码后的信号数据
- `anomalies.json` - 异常检测结果
- `ai_report.md` - AI分析报告（如果启用）

### 🔧 配置说明

#### AI服务配置
默认配置在 `config/loader.py` 中：
```python
DEFAULT_AI_BASE_URL = "http://localhost:8000/v1"
DEFAULT_AI_API_KEY = ""
DEFAULT_AI_MODEL = "gpt-3.5-turbo"
```

如需修改，请：
1. 编辑配置文件
2. 或使用自定义配置文件：`--config your_config.json`

#### 支持的文件格式
- **BLF文件**：Vector Binary Log Format，包含原始CAN数据
- **DBC文件**：CAN数据库文件，包含信号定义和解码规则

### 📊 输出文件说明

#### status.json
包含处理状态、错误信息和详细日志：
```json
{
  "status": "success|failed",
  "error": {
    "stage": "失败阶段",
    "code": "错误代码",
    "message": "错误信息",
    "fix": "修复建议"
  },
  "logs": [
    {
      "stage": "阶段名称",
      "status": "success|failed|running",
      "error": null
    }
  ]
}
```

#### decoded.parquet
解码后的信号数据，包含以下列：
- `timestamp_ns` - 时间戳（纳秒）
- `channel` - CAN通道
- `can_id` - CAN标识符
- `message` - 消息名称
- `signal` - 信号名称
- `value` - 信号值
- `raw_value` - 原始值

### 🚨 故障排除

#### 错误：BLF文件读取失败
```
解决方案：
1. 检查文件路径是否正确
2. 确认文件未损坏
3. 验证文件格式是否为标准BLF
```

#### 错误：DBC解码失败
```
解决方案：
1. 检查DBC文件格式
2. 确认DBC中的CAN ID与BLF数据匹配
3. 验证信号定义是否正确
```

#### 错误：AI服务连接失败
```
解决方案：
1. 检查AI服务是否运行
2. 验证API端点配置
3. 使用 --ai=false 禁用AI功能进行测试
```

### 💡 最佳实践

1. **首次使用**：先用 `--ai=false` 测试基本功能
2. **文件准备**：确保BLF和DBC文件来自同一系统
3. **调试模式**：使用调试脚本定位问题
4. **逐步验证**：先测试DBC加载，再测试完整流程

### 📞 获取帮助

如果问题仍然存在：
1. 运行调试脚本获取详细错误信息
2. 检查 `status.json` 中的错误日志
3. 确认所有依赖库版本兼容

---

**注意**：本工具需要Python 3.8+环境，并依赖python-can和cantools库。