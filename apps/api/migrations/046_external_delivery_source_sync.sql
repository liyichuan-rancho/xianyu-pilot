-- Migration 046: add an idempotent ownership boundary for delivery sources
-- synchronized by xianyu-product-management ("鱼料台").
--
-- Manual sources keep these columns NULL.  Externally managed sources use the
-- (external_system, external_key) unique key so a retried pipeline request
-- updates the same row instead of creating duplicate delivery sources.

SET NAMES utf8mb4;

SET @ddl = IF(
  EXISTS(SELECT 1 FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'delivery_text_source'
      AND column_name = 'external_system'),
  'SELECT 1',
  'ALTER TABLE `delivery_text_source` ADD COLUMN `external_system` VARCHAR(64) NULL COMMENT ''拥有该货源的外部系统'''
);
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @ddl = IF(
  EXISTS(SELECT 1 FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'delivery_text_source'
      AND column_name = 'external_key'),
  'SELECT 1',
  'ALTER TABLE `delivery_text_source` ADD COLUMN `external_key` VARCHAR(191) NULL COMMENT ''外部系统稳定幂等键'''
);
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @ddl = IF(
  EXISTS(SELECT 1 FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'delivery_text_source'
      AND column_name = 'external_account_id'),
  'SELECT 1',
  'ALTER TABLE `delivery_text_source` ADD COLUMN `external_account_id` BIGINT NULL COMMENT ''外部同步指定的闲鱼账号 ID'''
);
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @ddl = IF(
  EXISTS(SELECT 1 FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'delivery_text_source'
      AND column_name = 'external_goods_id'),
  'SELECT 1',
  'ALTER TABLE `delivery_text_source` ADD COLUMN `external_goods_id` VARCHAR(200) NULL COMMENT ''外部同步指定的闲鱼商品 ID'''
);
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @ddl = IF(
  EXISTS(SELECT 1 FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'delivery_text_source'
      AND column_name = 'content_sha256'),
  'SELECT 1',
  'ALTER TABLE `delivery_text_source` ADD COLUMN `content_sha256` CHAR(64) NULL COMMENT ''同步内容指纹'''
);
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @ddl = IF(
  EXISTS(SELECT 1 FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'delivery_text_source'
      AND index_name = 'uk_delivery_text_source_external'),
  'SELECT 1',
  'CREATE UNIQUE INDEX `uk_delivery_text_source_external` ON `delivery_text_source` (`external_system`, `external_key`)'
);
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @ddl = IF(
  EXISTS(SELECT 1 FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'delivery_text_source'
      AND index_name = 'idx_delivery_text_source_external_goods'),
  'SELECT 1',
  'CREATE INDEX `idx_delivery_text_source_external_goods` ON `delivery_text_source` (`external_account_id`, `external_goods_id`)'
);
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;
