-- ==========================================
-- VM Control Panel - MySQL Setup Script
-- ==========================================

-- 1. Create the Database
-- We use utf8mb4 for full Unicode support
CREATE DATABASE IF NOT EXISTS vm_control 
CHARACTER SET utf8mb4 
COLLATE utf8mb4_unicode_ci;

-- 2. Create a Dedicated Database User
-- It is highly recommended NOT to use 'root' for the application.
-- Replace 'vm_admin' and 'StrongPassword123!' with your desired credentials.
CREATE USER IF NOT EXISTS 'vm_admin'@'localhost' IDENTIFIED BY 'StrongPassword123!';

-- 3. Grant Permissions
-- Allow the user to read/write to the vm_control database.
GRANT ALL PRIVILEGES ON vm_control.* TO 'vm_admin'@'localhost';

-- 4. Apply Privileges
FLUSH PRIVILEGES;

-- ==========================================
-- NOTE ON TABLES:
-- You do NOT need to manually create the tables (user, vm, auditlog).
-- The Python application (FastAPI + SQLModel) is configured to automatically 
-- detect if tables are missing and create them on the first startup.
-- 
-- Ensure you update your .env file or app/core/config.py with:
-- DATABASE_URL="mysql+pymysql://vm_admin:StrongPassword123!@localhost/vm_control"
-- ==========================================
