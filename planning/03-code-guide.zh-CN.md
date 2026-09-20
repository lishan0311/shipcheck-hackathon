# 当前代码架构

现在已经按指定技术栈迁移。网站继续使用英文，这份说明用中文帮助你理解。

## 先认识三个目录

- frontend：React + TypeScript 网页；Vite 负责开发和构建，Tailwind 负责样式，React Router 负责页面路由。
- backend：Python + FastAPI 接口；Pydantic 验证数据，处理文档、核对和人工复核，并连接 Supabase。
- model：scikit-learn 分类器、训练数据、TF-IDF、Logistic Regression 和 joblib 模型文件。

## 建议阅读顺序

1. frontend/src/App.tsx：邮件工作台、详情及复核页面的入口。
2. frontend/src/api.ts：网页如何用 Fetch API 请求后端。
3. backend/server.py：后端有哪些接口。
4. backend/pipeline.py：邮件分类、分流和核对的流程。
5. backend/comparison.py：七字段提取与比较规则。
6. model/classifier.py：AI 如何判断邮件类别。

其他文件各司其职：types.ts 定义前端类型，schemas.py 验证后端数据，documents.py 读取 PDF、Word、Excel 和 OCR，repository.py 保存到 Supabase，review.py 处理人工修改和审计记录。

## 一次操作如何流动

点击 Run AI check → React 发 Fetch 请求 → FastAPI 验证输入 → Supabase 保存邮件和附件 → AI 分类 → 按需核对 → 保存报告 → React 显示结果。

人工复核会新增报告，不覆盖原报告，并保存修改人、原因和前后值。

## 本地启动

在项目根目录运行 python run.py。已有虚拟环境和前端构建时，会自动使用它们。

开发网页时，在 frontend 目录执行 npm.cmd run dev，访问 http://127.0.0.1:5173；后端仍在 8000。

测试命令：.venv/Scripts/python.exe -m pytest -q。

## Supabase 配置

填写根目录 .env 中的 SUPABASE_URL 和 SUPABASE_SERVICE_ROLE_KEY，再把 ALLOW_DEMO_MODE 改成 false。

尚未配置时，只有明确开启 ALLOW_DEMO_MODE=true 才会使用临时内存演示，重启会清空新结果。这不是 SQLite，也不是 Supabase。旧 SQLite 文件保留，可按 docs/DEPLOYMENT.md 迁移。

## 部署文件

- supabase/migrations/001_shipcheck.sql：数据库表、原子保存函数和私有存储桶。
- Dockerfile：构建 React，安装 Python 和 Tesseract，再启动 FastAPI。
- render.yaml：Render 部署前端和后端。
- .github/workflows/ci.yml：GitHub 自动运行测试和前端构建。

详细启动、环境变量和部署步骤见 README.md 和 docs/DEPLOYMENT.md。
