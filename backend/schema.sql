CREATE DATABASE IF NOT EXISTS tiktok_automator CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE tiktok_automator;

CREATE TABLE IF NOT EXISTS accounts (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  chrome_profile VARCHAR(100) NOT NULL,
  chrome_user_data_dir TEXT NOT NULL,
  speed DECIMAL(3,2) NOT NULL DEFAULT 1.00,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS upload_history (
  id INT AUTO_INCREMENT PRIMARY KEY,
  account_id INT NOT NULL,
  video_filename VARCHAR(255) NOT NULL,
  status ENUM('pending','uploading','success','failed') NOT NULL DEFAULT 'pending',
  duration_seconds INT NOT NULL DEFAULT 0,
  error_message TEXT NULL,
  uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_upload_history_account FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
  INDEX idx_upload_history_account_status (account_id, status),
  INDEX idx_upload_history_filename_account (video_filename, account_id),
  INDEX idx_upload_history_uploaded_at (uploaded_at)
);

CREATE TABLE IF NOT EXISTS settings (
  setting_key VARCHAR(120) PRIMARY KEY,
  setting_value TEXT NOT NULL
);

INSERT INTO settings (setting_key, setting_value) VALUES
('hashtags','#viral #fyp #trending'),
('description_template','{title} {hashtags}'),
('delay_between_uploads','25'),
('videos_folder',''),
('max_daily_per_account','30'),
('tiktok_upload_url','https://www.tiktok.com/upload'),
('tiktok_file_input_selector','input[type="file"]'),
('tiktok_description_selector','div[contenteditable="true"]'),
('tiktok_upload_button_selector','[data-e2e="submit-button"], [data-e2e="post_video_button"]'),
('tiktok_success_selector','[data-e2e="upload-success"], [data-e2e="upload-success-message"]'),
('tiktok_captcha_selector','iframe[src*="captcha"], div[class*="captcha"]')
ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value);
