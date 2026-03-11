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
-- The Python application (FastAPI + SQLModel) automatically creates tables 
-- on startup if they don't exist.
-- However, for reference or manual recovery, here is the schema:
-- ==========================================

USE vm_control;

-- Users Table
-- Stores admin and client credentials.
CREATE TABLE IF NOT EXISTS user (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    role VARCHAR(50) DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE,
    discord_webhook_url VARCHAR(512) DEFAULT NULL,
    discord_webhook_public VARCHAR(512) DEFAULT NULL,
    INDEX (username)
);

-- VMs Table
-- Tracks virtual machines managed by the panel.
CREATE TABLE IF NOT EXISTS vm (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    vmx_path VARCHAR(512) NOT NULL UNIQUE,
    owner_id INT,
    expiration_date DATETIME DEFAULT NULL,
    
    -- RDP Settings
    rdp_ip VARCHAR(255) DEFAULT 'remotedesktop.penguinhosting.host',
    rdp_port INT DEFAULT 3389,
    rdp_username VARCHAR(255) DEFAULT 'Administrator',
    
    -- Guest Credentials (for vmrun operations)
    guest_username VARCHAR(255) DEFAULT NULL,
    guest_password VARCHAR(255) DEFAULT NULL,
    
    -- VNC Settings
    vnc_port INT DEFAULT NULL,
    vnc_password VARCHAR(8) DEFAULT NULL,
    vnc_enabled BOOLEAN DEFAULT FALSE,
    
    -- Task Tracking
    task_state VARCHAR(255) DEFAULT NULL,
    task_progress INT DEFAULT 0,
    task_message VARCHAR(255) DEFAULT NULL,
    
    FOREIGN KEY (owner_id) REFERENCES user(id)
);

-- PortMapping Table
-- Tracks network port forwarding rules associated with VMs.
CREATE TABLE IF NOT EXISTS portmapping (
    id INT AUTO_INCREMENT PRIMARY KEY,
    protocol VARCHAR(10) NOT NULL,
    host_port INT NOT NULL,
    guest_port INT NOT NULL,
    guest_ip VARCHAR(255) NOT NULL,
    vm_id INT,
    description VARCHAR(255),
    INDEX (protocol),
    INDEX (host_port),
    FOREIGN KEY (vm_id) REFERENCES vm(id)
);

-- Audit Logs Table
-- Records important actions for security and history.
CREATE TABLE IF NOT EXISTS auditlog (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    action VARCHAR(255) NOT NULL,
    vm_id INT DEFAULT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    details TEXT,
    FOREIGN KEY (user_id) REFERENCES user(id),
    FOREIGN KEY (vm_id) REFERENCES vm(id)
);
