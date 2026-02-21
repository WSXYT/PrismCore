# PrismCore 项目规则

## 语言规范
- 所有代码注释使用简体中文
- 所有文档使用简体中文
- 计划文件使用简体中文
- 对话使用简体中文

## 代码规范
- 遵循 PEP8 规范
- 所有耗时操作必须在 QThread 中执行，禁止阻塞 UI 线程
- 使用 MVVM 架构：Model（业务逻辑）、View（界面）、ViewModel（信号适配）
- Windows API 调用统一封装在 src/utils/winapi.py 中

## 架构
- UI 框架：PySide6 + QFluentWidgets
- 四页导航：首页、清理、加速、工具箱
- 信号槽解耦：View 不直接调用 Model，通过 ViewModel 中转
