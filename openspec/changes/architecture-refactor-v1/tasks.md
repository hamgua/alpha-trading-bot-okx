## 1. Phase 1:循环依赖修复

- [ ] 1.1 在 config/models.py 中定义 ConfigUpdaterProtocol 接口
- [ ] 1.2 在 ai/optimizer/config_updater.py 中实现 ConfigUpdater 类
- [ ] 1.3 重构 ai/optimizer 模块使用 Protocol 而非直接引用 config
- [ ] 1.4 验证无循环依赖（import 测试）
- [ ] 1.5 运行现有测试确保无回归

## 2. Phase 2: AdaptiveTradingBot 拆分

- [ ] 2.1 创建 core/managers/ 目录结构
- [ ] 2.2 提取 MarketRegimeManager 类
- [ ] 2.3 提取 StrategyExecutionManager 类
- [ ] 2.4 提取 RiskControlManager 类
- [ ] 2.5 提取 ParameterManager 类
- [ ] 2.6 提取 LearningManager 类
- [ ] 2.7 重构 AdaptiveTradingBot 为门面协调类
- [ ] 2.8 更新 main.py 导入（如果需要）
- [ ] 2.9 运行现有测试确保无回归

## 3. Phase 3: 异常处理统一

- [ ] 3.1 完善 core/exceptions.py 异常类定义
- [ ] 3.2 添加异常处理规范文档到 docs/
- [ ] 3.3 重构 ai/ 模块异常处理
- [ ] 3.4 重构 exchange/ 模块异常处理
- [ ] 3.5 重构 core/ 模块异常处理
- [ ] 3.6 运行现有测试确保无回归

## 4. Phase 4: 类型提示补全

- [ ] 4.1 添加 mypy 配置（如果不存在）
- [ ] 4.2 在 core/exceptions.py 添加类型注解
- [ ] 4.3 在 core/managers/ 添加类型注解
- [ ] 4.4 在 ai/optimizer/ 添加类型注解
- [ ] 4.5 运行 mypy 检查并修复错误
- [ ] 4.6 添加类型检查到 pre-commit（可选）

## 5. Verification

- [ ] 5.1 运行完整测试套件
- [ ] 5.2 代码格式化（black/isort）
- [ ] 5.3 类型检查通过
- [ ] 5.4 代码审查（可选）
