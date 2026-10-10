-- =============================================================
-- KnowledgeHub 数据库初始化脚本
-- 目标：PostgreSQL 18.4
-- 作用：创建专用账号、专用数据库，并启用所需扩展
-- 用法：psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -f scripts/init_db.sql
-- 说明：创建扩展需要超级用户权限，故本脚本以 postgres 执行；
--       业务运行期请使用专用账号 kh_app，不要用 postgres 超管。
-- =============================================================

-- 1) 创建专用账号 kh_app（幂等：已存在则跳过）
--    注意：生产环境请修改下方密码，并通过 .env 注入，不要提交明文到仓库。
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'kh_app') THEN
    CREATE ROLE kh_app WITH LOGIN PASSWORD '123456';
    RAISE NOTICE '已创建角色 kh_app';
  ELSE
    RAISE NOTICE '角色 kh_app 已存在，跳过';
  END IF;
END
$$;

-- 2) 创建专用数据库 knowledgehub（幂等）
SELECT 'CREATE DATABASE knowledgehub OWNER kh_app'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'knowledgehub')\gexec

-- 3) 切换到目标库并启用扩展
\connect knowledgehub

CREATE EXTENSION IF NOT EXISTS vector;      -- pgvector：向量类型与 HNSW 索引
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- 中文关键词/模糊检索（三元组）
CREATE EXTENSION IF NOT EXISTS pgcrypto;    -- 加密函数
CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; -- UUID 生成

-- 4) 授权
GRANT ALL PRIVILEGES ON DATABASE knowledgehub TO kh_app;
GRANT ALL ON SCHEMA public TO kh_app;
ALTER SCHEMA public OWNER TO kh_app;

-- 5) 结果确认
SELECT current_database() AS db, extname, extversion
FROM pg_extension ORDER BY extname;
